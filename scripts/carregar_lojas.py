"""
Carga das lojas a partir de um CSV (exportado do Google Sheets em português ou do Google My Maps).

Só LÊ o arquivo e mostra um resumo, a menos que você passe --gravar. Nada é gravado sem a sua confirmação.
Usa asyncpg (o psycopg2 pode estar bloqueado no Windows) e lê a conexão SOMENTE da variável DATABASE_URL.

A tabela é criada antes pelo Alembic (dentro de backend/):  python -m alembic upgrade head

Colunas aceitas (reconhecidas pelo NOME do cabeçalho, em qualquer ordem, sem diferença de maiúsculas, acentos ou espaços):
    Nome; UF ou Estado; Endereço, Endereco ou Endereço Completo; Cidade; Latitude ou Lat; Longitude, Lng ou Lon
    (ex.: o CSV real tem Nome, UF, Endereço Completo, Cidade, Latitude, Longitude; endereço e cidade podem ficar em branco;
    a filial já vai no nome, ex.: "Atacadão Guarujá")
    ou o formato do Google My Maps: WKT (POINT (longitude latitude)), name, description (o Estado não vem: a loja entra sem
    Estado e o operador completa na tela "Lojas").

Exportação do Superset (reconhecida pelas colunas store_id, store_name e store_point; o resto é ignorado):
    store_name = nome de operação; store_id = código externo; store_city = Cidade; store_state = Estado (por extenso, sem
    acento, ou a sigla); store_address = Endereço; store_point = "latitude;longitude" numa célula só; store_is_active =
    TRUE/FALSE (inativas são ignoradas e contadas); retailer_name = rede (só informativa). A mesma loja aparece em várias
    linhas: o script agrupa por store_id. Cada loja do arquivo é (a) completada, se o código externo já existe no cadastro;
    (b) ligada à loja cadastrada a até 150 m, se houver exatamente uma (recebe código externo e nome de operação, sem mudar
    nome, endereço nem coordenadas); (c) listada como ambígua, se houver mais de uma a até 150 m; (d) criada, se for nova.
    Com DATABASE_URL definida, o resumo consulta o cadastro (só leitura) e mostra o plano; sem ela, só o que o arquivo diz.
    Nada sobrescreve o que já está preenchido.
    Desempate por rede: com mais de uma loja cadastrada a até 150 m, retailer_name escolhe (Atacadao = lojas "Atacadão ...",
    Sam's Club BR = "Sam's Club ...", Carrefour = "Carrefour ..."); se exatamente UMA for da rede, é a escolhida.
    --somente-de-motoristas CSV: lojas NOVAS só são criadas se o nome de operação estiver na coluna Lojas desse CSV de motoristas
    (mesmas siglas ATC/SAMS/CRFO e Av = Avenida do casamento de motoristas); as demais são contadas e não criadas.
    A ligação por proximidade das lojas já cadastradas vale para todas.

Passo 1 — só o resumo (não conecta no banco):
    python scripts/carregar_lojas.py --csv data/lojas/lojas.csv

Passo 2 — gravar (mostra a previsão e pede a confirmação; PowerShell, string do banco só na sessão):
    $env:DATABASE_URL = "<string do Neon>"
    python scripts/carregar_lojas.py --csv data/lojas/lojas.csv --gravar
    Remove-Item Env:DATABASE_URL

Regras:
    - aceita ';' ou ',' como separador, vírgula ou ponto como decimal ("-23,5614"), células entre aspas; UTF-8 ou Windows-1252;
    - latitude entre -34 e 6 e longitude entre -74 e -34 (Brasil); loja com os dois valores trocados é avisada e NÃO é gravada;
    - nome repetido no arquivo: vale a última linha; nome repetido no banco: atualiza (upsert por nome);
    - nunca sobrescreve uma loja que um operador editou na tela (--sobrescrever-editados muda isso);
    - o CSV deve ficar em data/lojas/ (fora do git: o repositório é público).
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from backend import carga_superset  # noqa: E402
from backend.db_url import dsn_asyncpg, mascarar_senha  # noqa: E402
from backend.item_pesos import esta_protegido_do_git  # noqa: E402
from backend.lojas import ROTULOS_DAS_COLUNAS, gravar_carga, ler_csv_lojas, para_gravar, prever_carga, resumir  # noqa: E402

PASTA_PADRAO = RAIZ / "data" / "lojas"
TENTATIVAS = 3
ESPERAS = (2, 5)
ERROS_DE_CONEXAO = (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError, asyncio.TimeoutError)
FRASE_DE_CONFIRMACAO = "GRAVAR"


def conectar(dsn: str):
    """Abre uma conexão nova (corrotina). Os testes trocam esta função."""
    return asyncpg.connect(dsn, timeout=30)


async def com_conexao(dsn: str, operacao, tentativas: int = TENTATIVAS, esperas=ESPERAS, dormir=asyncio.sleep):
    """
    Abre uma conexão NOVA, executa `operacao(conn)` e fecha. Se a conexão cair, reconecta e repete (até `tentativas`):
    o Neon derruba conexões ociosas, então nunca se mantém uma conexão aberta esperando você digitar.
    """
    for tentativa in range(1, tentativas + 1):
        conn = None
        try:
            conn = await conectar(dsn)
            return await operacao(conn)
        except (asyncpg.UndefinedTableError, asyncpg.UndefinedColumnError):
            sys.exit(
                "ERRO: a tabela lojas (ou as colunas código externo e nome de operação) ainda não existe no banco. Crie-as antes, dentro de backend/:\n"
                "  python -m alembic upgrade head"
            )
        except ERROS_DE_CONEXAO as erro:
            if tentativa == tentativas:
                raise
            print(f"  a conexão com o banco caiu ({type(erro).__name__}); reconectando (tentativa {tentativa + 1} de {tentativas}) ...")
            await dormir(esperas[min(tentativa - 1, len(esperas) - 1)] if esperas else 0)
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass  # conexão já quebrada: não há o que fechar


def imprimir_resumo(caminho: Path, resultado, resumo: dict) -> None:
    formato = "Google My Maps (WKT, name, description)" if resultado.formato == "my_maps" else "colunas Nome, UF, Endereço, Cidade, Latitude, Longitude"
    print(f"Arquivo: {caminho}")
    print(f"  formato: {formato} | separador: '{resultado.delimitador}' | codificação: {resultado.codificacao}")
    campos = ("nome", "estado", "endereco", "cidade", "latitude", "longitude") if resultado.formato == "colunas" else ("wkt", "nome", "descricao", "cidade")
    reconhecidas = [f"{ROTULOS_DAS_COLUNAS[c]} <- \"{resultado.colunas[c]}\"" for c in campos if c in resultado.colunas]
    faltando = [ROTULOS_DAS_COLUNAS[c] for c in campos if c not in resultado.colunas]
    print(f"  colunas reconhecidas: {'; '.join(reconhecidas)}")
    if faltando:
        print(f"  colunas NÃO encontradas (ficam em branco): {', '.join(faltando)}")
    print(f"  linhas lidas: {resumo['linhas']}")
    print(f"  LOJAS VÁLIDAS (serão gravadas): {resumo['validas']}")
    print(f"      sem endereço: {resumo['sem_endereco']}")
    print(f"      sem cidade: {resumo['sem_cidade']}" + (" (o código IBGE do hub dessas lojas vem do CEP mais próximo; cadastre a cidade na tela \"Lojas\")" if resumo["sem_cidade"] else ""))
    print(f"      sem Estado: {resumo['sem_uf']}" + (" (o operador completa na tela \"Lojas\")" if resumo["sem_uf"] else ""))
    print(f"  DUPLICADAS (mesmo nome; vale a última linha): {resumo['duplicadas']}")
    for l in [l for l in resultado.linhas if l.status == "duplicada_ignorada"][: resumo["exemplos"]]:
        print(f"      linha {l.numero}: {l.nome} ({l.motivo})")
    print(f"  COM COORDENADA SUSPEITA (NÃO serão gravadas): {resumo['suspeitas']}")
    if resumo["trocadas"]:
        print(f"      AVISO: {len(resumo['trocadas'])} loja(s) com latitude e longitude TROCADAS:")
        for l in resumo["trocadas"][: resumo["exemplos"]]:
            print(f"      linha {l.numero}: {l.nome}: {l.motivo}")
    for l in resumo["fora_do_brasil"][: resumo["exemplos"]]:
        print(f"      linha {l.numero}: {l.nome}: {l.motivo}")
    print(f"  INVÁLIDAS (ignoradas): {len(resumo['invalidas'])}")
    for l in resumo["invalidas"][: resumo["exemplos"]]:
        print(f"      linha {l.numero}{' (' + l.nome + ')' if l.nome else ''}: {l.motivo}")
    if len(resumo["invalidas"]) > resumo["exemplos"]:
        print(f"      ... e mais {len(resumo['invalidas']) - resumo['exemplos']}")
    for aviso in resultado.avisos:
        print(f"  Aviso: {aviso}")


async def _ler_cadastradas_so_leitura(conn):
    async with conn.transaction(readonly=True):
        return await carga_superset.ler_cadastradas(conn)


def _lista(titulo: str, itens: list, exemplos: int, formatar) -> None:
    print(titulo)
    for item in itens[:exemplos]:
        print(f"      {formatar(item)}")
    if len(itens) > exemplos:
        print(f"      ... e mais {len(itens) - exemplos}")


def _numeros_das_linhas(linhas: list) -> str:
    return ", ".join(str(n) for n in linhas[:5]) + (" ..." if len(linhas) > 5 else "")


ROTULOS_SUPERSET = {
    "store_name": "nome de operação", "store_id": "código externo", "store_city": "cidade", "store_state": "estado",
    "store_address": "endereço", "store_point": "coordenadas", "store_is_active": "ativa", "retailer_name": "rede",
}


def imprimir_resumo_superset(caminho: Path, resultado, resumo: dict, plano, exemplos: int = 10, permitidas=None) -> None:
    print(f"Arquivo: {caminho}")
    print(f"  formato: exportação do Superset | separador: '{resultado.delimitador}' | codificação: {resultado.codificacao}")
    reconhecidas = [f"{ROTULOS_SUPERSET[c]} <- \"{resultado.colunas[c]}\"" for c in carga_superset.CAMPOS if c in resultado.colunas]
    print(f"  colunas reconhecidas: {'; '.join(reconhecidas)}")
    faltando = [ROTULOS_SUPERSET[c] for c in carga_superset.CAMPOS if c not in resultado.colunas]
    if faltando:
        print(f"  colunas NÃO encontradas (ficam em branco): {', '.join(faltando)}")
    print(f"  linhas lidas: {resumo['linhas']}")
    print(f"  LOJAS NO ARQUIVO: {resumo['lojas_ativas']} ativas, {resumo['lojas_inativas']} inativas (ignoradas; {resumo['linhas_inativas']} linha(s) inativa(s))")
    print(f"      linhas repetidas agrupadas por store_id: {resumo['repetidas']}")
    if resumo["redes"]:
        redes = sorted(resumo["redes"].items(), key=lambda x: (-x[1], x[0]))[:exemplos]
        print("      redes (só informativo): " + ", ".join(f"{r} ({q})" for r, q in redes))
    _lista(f"  SEM COORDENADA OU INVÁLIDAS (não serão gravadas): {len(resumo['sem_coordenada'])}", resumo["sem_coordenada"], exemplos,
           lambda x: f"store_id {x[0]} ({x[1]}), linha(s) {_numeros_das_linhas(x[2])}: {x[3]}")
    if resumo["linhas_invalidas"]:
        _lista(f"  LINHAS INVÁLIDAS (ignoradas): {len(resumo['linhas_invalidas'])}", resumo["linhas_invalidas"], exemplos,
               lambda x: f"linha {x[0]}: {x[1]}")
    nao_reconhecidos = resumo["estados_nao_reconhecidos"]
    print(f"  ESTADOS NÃO RECONHECIDOS (a loja entra sem UF): {sum(nao_reconhecidos.values())}")
    for estado, quantas in sorted(nao_reconhecidos.items(), key=lambda x: (-x[1], x[0]))[:exemplos]:
        print(f"      \"{estado}\": {quantas} loja(s)")
    if resumo["conflitos_no_arquivo"]:
        _lista(f"  DIVERGÊNCIAS ENTRE LINHAS DO MESMO store_id: {len(resumo['conflitos_no_arquivo'])}", resumo["conflitos_no_arquivo"], exemplos,
               lambda x: f"store_id {x[0]} ({x[1]}): {x[2]}")
    if plano is None:
        print("\n  O cadastro NÃO foi consultado: defina DATABASE_URL (a conexão só lê, não grava) para ver quais lojas já existem,")
        print("  quais serão ligadas por proximidade, as novas, as ambíguas e os nomes em conflito.")
        return
    print(f"  JÁ CADASTRADAS, ligadas pelo código externo (só completa o que está vazio): {resumo['ja_cadastradas']}")
    _lista(f"  JÁ CADASTRADAS, ligadas por proximidade (até 150 m; nome, endereço e coordenadas não mudam): {resumo['por_proximidade']}",
           plano.por_proximidade, exemplos,
           lambda a: f"\"{a.loja.nome_operacao}\" (arquivo) = \"{a.destino['nome']}\" (cadastrada), a {a.distancia_m:.0f} m"
           + (" (desempate por rede)" if a.por_rede else ""))
    print(f"  NOVAS (serão criadas): {resumo['novas']}")
    if permitidas is not None:
        print(f"  FORA DA LISTA DE MOTORISTAS (não criadas): {resumo['fora_da_lista']}")

    def ambigua(a):
        candidatas = "; ".join(f"\"{n}\" a {d:.0f} m" for n, d in a.candidatas[:3])
        return f"\"{a.loja.nome_operacao}\" (store_id {a.loja.codigo_externo}): {a.motivo}" + (f": {candidatas}" if candidatas else "")

    _lista(f"  AMBÍGUAS (NÃO aplicadas): {resumo['ambiguas']}", plano.ambiguas, exemplos, ambigua)
    _lista(f"  NOME EM CONFLITO (NÃO gravadas): {resumo['nome_em_conflito']}", plano.nome_em_conflito, exemplos,
           lambda a: f"\"{a.loja.nome_operacao}\" (store_id {a.loja.codigo_externo}): {a.motivo}")
    if plano.operacao_em_conflito:
        _lista(f"  NOME DE OPERAÇÃO JÁ É DE OUTRA LOJA (a ligação vale, sem esse nome): {len(plano.operacao_em_conflito)}",
               plano.operacao_em_conflito, exemplos, lambda a: f"\"{a.loja.nome_operacao}\" (store_id {a.loja.codigo_externo})")


def carregar_superset(caminho: Path, args) -> None:
    """Exportação do Superset: resumo (com o plano, se houver DATABASE_URL) e, com --gravar, gravação com confirmação."""
    try:
        resultado = carga_superset.ler_superset(caminho)
    except ValueError as erro:
        sys.exit(f"ERRO: {erro}")
    permitidas = None
    if args.somente_de_motoristas:
        try:
            permitidas = carga_superset.lojas_dos_motoristas(args.somente_de_motoristas)
        except (OSError, ValueError) as erro:
            sys.exit(f"ERRO: CSV de motoristas: {erro}")
        print(f"Lojas novas só serão criadas se estiverem na coluna Lojas de {args.somente_de_motoristas} ({len(permitidas)} nome(s) distinto(s)).\n")
    url = os.getenv("DATABASE_URL")
    dsn = None
    if url:
        try:
            dsn = dsn_asyncpg(url)
        except ValueError as erro:
            sys.exit(f"\nERRO: DATABASE_URL inválida ({erro}): {mascarar_senha(url)}")
    plano = None
    if dsn is not None:
        cadastradas = asyncio.run(com_conexao(dsn, _ler_cadastradas_so_leitura))
        plano = carga_superset.planejar(cadastradas, resultado.lojas, permitidas)
    imprimir_resumo_superset(caminho, resultado, carga_superset.resumir(resultado, plano), plano, permitidas=permitidas)

    if not args.gravar:
        print("\nNada foi gravado. Se o resumo estiver certo, rode de novo com --gravar.")
        return
    if dsn is None:
        sys.exit("\nERRO: defina a variável de ambiente DATABASE_URL (a string do banco) para gravar.")
    if not plano.a_gravar:
        sys.exit("\nNada a gravar.")
    completadas = sum(1 for a in plano.ja_cadastradas if a.preencher)
    print(f"\nSerá gravado: {len(plano.novas)} loja(s) nova(s), {len(plano.por_proximidade)} ligada(s) por proximidade, "
          f"{completadas} completada(s). Ambíguas e nomes em conflito NÃO são gravados.")
    if not args.sim:
        try:
            resposta = input(f"\nDigite {FRASE_DE_CONFIRMACAO} para confirmar e gravar no banco: ")
        except EOFError:
            resposta = ""
        if resposta.strip() != FRASE_DE_CONFIRMACAO:
            print("Cancelado: nada foi gravado.")
            return
    try:
        feito = asyncio.run(com_conexao(dsn, lambda c: carga_superset.gravar_carga(c, resultado.lojas, permitidas)))
    except asyncpg.UniqueViolationError:
        sys.exit("\nERRO: alguém cadastrou uma loja com o mesmo nome, código ou nome de operação enquanto a carga rodava. Nada foi gravado: rode de novo.")
    print(f"Gravado: {feito['novas']} loja(s) nova(s), {feito['ligadas']} ligada(s) por proximidade, {feito['completadas']} completada(s).")


def imprimir_previsao(previsao: dict) -> None:
    print("Previsão no banco:")
    print(f"  lojas novas: {previsao['novas']}")
    print(f"  lojas já existentes que serão atualizadas: {previsao['atualizadas']}")
    print(f"  lojas PRESERVADAS (um operador editou na tela): {previsao['protegidas']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Carga de lojas a partir de um CSV (mostra o resumo; só grava com --gravar).")
    parser.add_argument("--csv", required=True, help="CSV de lojas (em data/lojas/, fora do git)")
    parser.add_argument("--gravar", action="store_true", help="grava no banco (DATABASE_URL) depois de mostrar a previsão e pedir confirmação")
    parser.add_argument("--somente-de-motoristas", metavar="CSV_DE_MOTORISTAS",
                        help="exportação do Superset: só cria as lojas NOVAS cujo nome de operação aparece na coluna Lojas deste CSV de motoristas")
    parser.add_argument("--sim", action="store_true", help="com --gravar, não pede a confirmação digitada")
    parser.add_argument("--sobrescrever-editados", action="store_true", help="permite sobrescrever lojas que um operador editou na tela")
    args = parser.parse_args(argv)

    caminho = Path(args.csv)
    if not caminho.exists():
        disponiveis = sorted(p.name for p in PASTA_PADRAO.glob("*.csv")) if PASTA_PADRAO.exists() else []
        sys.exit(
            f"ERRO: não achei {caminho}.\n"
            + (f"CSVs em data/lojas/: {', '.join(disponiveis)}. Use --csv com o nome certo." if disponiveis
               else "Coloque o CSV em data/lojas/ (pasta fora do git) e use --csv com o nome do arquivo.")
        )
    if not esta_protegido_do_git(caminho):
        print(f"AVISO: {caminho} está no repositório e não é ignorado pelo git: não faça commit deste arquivo.", file=sys.stderr)

    if carga_superset.e_exportacao_superset(caminho):
        return carregar_superset(caminho, args)
    if args.somente_de_motoristas:
        sys.exit("ERRO: --somente-de-motoristas só vale para a exportação do Superset.")

    try:
        resultado = ler_csv_lojas(caminho)
    except ValueError as erro:
        sys.exit(f"ERRO: {erro}")
    resumo = resumir(resultado)
    imprimir_resumo(caminho, resultado, resumo)

    linhas = para_gravar(resultado)
    if not args.gravar:
        print("\nNada foi gravado (nem conectei no banco). Se o resumo estiver certo, rode de novo com --gravar.")
        return
    if not linhas:
        sys.exit("\nNada a gravar.")

    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("\nERRO: defina a variável de ambiente DATABASE_URL (a string do banco) para gravar.")
    try:
        dsn = dsn_asyncpg(url)
    except ValueError as erro:
        sys.exit(f"\nERRO: DATABASE_URL inválida ({erro}): {mascarar_senha(url)}")

    previsao = asyncio.run(com_conexao(dsn, lambda c: prever_carga(c, linhas, args.sobrescrever_editados)))
    print()
    imprimir_previsao(previsao)
    if not args.sim:
        try:
            resposta = input(f"\nDigite {FRASE_DE_CONFIRMACAO} para confirmar e gravar no banco: ")
        except EOFError:
            resposta = ""
        if resposta.strip() != FRASE_DE_CONFIRMACAO:
            print("Cancelado: nada foi gravado.")
            return
    feito = asyncio.run(com_conexao(dsn, lambda c: gravar_carga(c, linhas, args.sobrescrever_editados)))
    print(f"Gravado: {feito['novas']} loja(s) nova(s), {feito['atualizadas']} atualizada(s), {feito['protegidas']} preservada(s).")


if __name__ == "__main__":
    main()
