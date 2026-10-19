"""
Carga dos motoristas a partir de um CSV (Etapa 6b).

Só LÊ o arquivo e mostra um resumo, a menos que você passe --gravar. Nada é gravado sem a sua confirmação digitada.
Usa asyncpg (o psycopg2 pode estar bloqueado no Windows) e lê a conexão SOMENTE da variável DATABASE_URL.

As tabelas e colunas são criadas antes pelo Alembic (dentro de backend/):  python -m alembic upgrade head   (revisão 0008)
As lojas precisam estar cadastradas antes (scripts/carregar_lojas.py).

Colunas aceitas (reconhecidas pelo NOME do cabeçalho, em qualquer ordem, sem diferença de maiúsculas, acentos ou espaços; o resumo
mostra qual cabeçalho foi reconhecido para cada campo):
    Código, Codigo ou ID (obrigatória: é a chave da carga); Nome, Nome Motorista ou Motorista; Tipo de veículo, Veículo ou Tipo (Passeio, Carro de passeio, Utilitário, Fiorino,
    Fiorino/Utilitário e variações); Lojas ou Loja (nomes separados por ';' ou '|'; o casamento ignora hífens, pontuação, acentos e maiúsculas, e trata "ATC" no início como "Atacadão" e "Av" como "Avenida"; nome que casa com mais de uma loja é ambíguo e não vira vínculo; se o CSV
    usa ';' como separador, use '|' entre as lojas ou coloque a célula entre aspas); Diária (opcional; vírgula ou ponto
    decimal); Telefone, Número, Celular ou Fone (opcional; com DDD; o 55 do país na frente é removido).

Passo 1 — resumo. Para conferir os nomes das lojas o script lê as lojas do banco (SÓ LEITURA); se DATABASE_URL não estiver
definida, o resumo avisa e segue sem conferir as lojas:
    $env:DATABASE_URL = "<string do Neon>"
    python scripts/carregar_motoristas.py --csv data/motoristas/motoristas.csv

Siglas de rede no início do nome da loja (sem diferença de maiúsculas): ATC = Atacadão, SAMS/SAMs = Sam's Club, CRFO = Carrefour.
Para os nomes que as siglas não resolvem: --exportar-apelidos data/motoristas/apelidos.csv escreve um modelo só com os nomes de
loja não encontrados ou ambíguos (nome_na_planilha, motoristas, sugestoes, nome_da_loja); preencha nome_da_loja com o nome exato
de uma loja cadastrada e rode com --apelidos data/motoristas/apelidos.csv (linhas em branco são ignoradas; o arquivo não tem
dado pessoal e fica em data/motoristas/, ignorada pelo git). --listar-todas mostra todas as lojas não encontradas no resumo.

Passo 2 — gravar (mostra a previsão e pede a confirmação digitada; string do banco só na sessão):
    python scripts/carregar_motoristas.py --csv data/motoristas/motoristas.csv --gravar
    Remove-Item Env:DATABASE_URL

Regras:
    - a chave é SEMPRE o código: linha sem código é recusada; nomes repetidos são aceitos se o código for diferente;
      código repetido no arquivo: vale a última linha (e é avisado);
    - telefone é dado pessoal: o resumo mostra só contagens (com, sem, inválidos) e, para as linhas recusadas por telefone
      inválido, o CÓDIGO delas (nunca o número), para você achar e corrigir cada uma na planilha;
    - nunca sobrescreve um motorista que um operador editou na tela (--sobrescrever-editados muda isso), nunca reativa um
      motorista desativado e só acrescenta vínculos com lojas (nunca remove);
    - o CSV deve ficar em data/motoristas/ (fora do git: o repositório é público e o arquivo tem dados pessoais).
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from backend.carga_motoristas import (  # noqa: E402
    ROTULOS_DAS_COLUNAS, conferir_lojas, exportar_apelidos, gravar_carga, ler_apelidos, ler_csv_motoristas, ler_lojas, para_gravar, prever_carga, resumir,
)
from backend.db_url import dsn_asyncpg, mascarar_senha  # noqa: E402
from backend.item_pesos import esta_protegido_do_git  # noqa: E402

PASTA_PADRAO = RAIZ / "data" / "motoristas"
TENTATIVAS = 3
ESPERAS = (2, 5)
ERROS_DE_CONEXAO = (asyncpg.PostgresConnectionError, asyncpg.InterfaceError, OSError, asyncio.TimeoutError)
FRASE_DE_CONFIRMACAO = "GRAVAR"
CAMPOS = ("codigo", "nome", "tipo", "lojas", "diaria", "telefone")


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
                "ERRO: o banco ainda não tem as tabelas/colunas de motoristas (ou de lojas). Crie-as antes, dentro de backend/:\n"
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


async def _ler_lojas_so_leitura(conn):
    async with conn.transaction(readonly=True):
        return await ler_lojas(conn)


def _numeros(linhas, limite) -> str:
    nomes = [str(l.numero) for l in linhas[:limite]]
    return ", ".join(nomes) + (f" ... e mais {len(linhas) - limite}" if len(linhas) > limite else "")


def imprimir_resumo(caminho: Path, resultado, resumo: dict, listar_todas: bool = False) -> None:
    ex = resumo["exemplos"]
    corte = None if listar_todas else ex
    print(f"Arquivo: {caminho}")
    print(f"  separador: '{resultado.delimitador}' | codificação: {resultado.codificacao}")
    reconhecidas = [f"{ROTULOS_DAS_COLUNAS[c]} <- \"{resultado.colunas[c]}\"" for c in CAMPOS if c in resultado.colunas]
    faltando = [ROTULOS_DAS_COLUNAS[c] for c in CAMPOS if c not in resultado.colunas]
    print(f"  colunas reconhecidas: {'; '.join(reconhecidas)}")
    if faltando:
        print(f"  colunas NÃO encontradas (ficam em branco): {', '.join(faltando)}")
    print(f"  linhas lidas: {resumo['linhas']}")
    print(f"  MOTORISTAS VÁLIDOS (serão gravados): {resumo['validas']}")
    print(f"      com telefone: {resumo['com_telefone']} | sem telefone: {resumo['sem_telefone']}")
    print(f"      com diária própria: {resumo['com_valor']} | com lojas: {resumo['com_lojas']}")
    if resumo["nomes_repetidos"]:
        print(f"      nomes repetidos (aceitos, pois os códigos são diferentes): {resumo['nomes_repetidos']}")

    print(f"  SEM CÓDIGO (recusadas): {len(resumo['sem_codigo'])}" + (f" (linhas {_numeros(resumo['sem_codigo'], ex)})" if resumo["sem_codigo"] else ""))
    nao_reconhecidos = resumo["tipos_nao_reconhecidos"]
    print(f"  TIPO DE VEÍCULO NÃO RECONHECIDO (recusadas): {sum(nao_reconhecidos.values())}")
    for tipo, quantas in nao_reconhecidos.most_common(ex):
        print(f"      \"{tipo}\": {quantas} linha(s)")
    print(f"  CÓDIGOS REPETIDOS NO ARQUIVO (vale a última linha): {len(resumo['repetidos'])}")
    for codigo, numeros in resumo["repetidos"][:ex]:
        print(f"      {codigo}: linhas {', '.join(str(n) for n in numeros)}")
    if resumo["lojas_conferidas"]:
        nao = resumo["lojas_nao_encontradas"]
        print(f"  LOJAS NÃO ENCONTRADAS (a linha vale, sem esse vínculo): {len(nao)}")
        for nome, quantas in nao.most_common(corte):
            print(f"      \"{nome}\": {quantas} motorista(s)")
        if corte is not None and len(nao) > corte:
            print(f"      ... e mais {len(nao) - corte} (use --listar-todas para ver todas)")
        amb = resumo["lojas_ambiguas"]
        print(f"  LOJAS AMBÍGUAS (o nome casa com mais de uma loja; o vínculo NÃO é gravado): {len(amb)}")
        for nome, quantas in amb.most_common(corte):
            print(f"      \"{nome}\": {quantas} motorista(s)")
        if corte is not None and len(amb) > corte:
            print(f"      ... e mais {len(amb) - corte} (use --listar-todas para ver todas)")
        if resumo["apelidos_invalidos"] or resumo["ligados_por_apelido"]:
            print(f"  APELIDOS: motoristas ligados a alguma loja por apelido: {resumo['ligados_por_apelido']}")
            print(f"  APELIDOS INVÁLIDOS (ignorados): {len(resumo['apelidos_invalidos'])}")
            for planilha, loja, motivo in resumo["apelidos_invalidos"]:
                print(f"      \"{planilha}\" -> \"{loja}\": {motivo}")
        print(f"  MOTORISTAS que serão gravados SEM algum vínculo de loja (loja não encontrada ou ambígua): {resumo['sem_algum_vinculo']}")
    else:
        print("  LOJAS: não conferi os nomes (veja o aviso abaixo)")

    invalidos_fone = resumo["telefone_invalido"]
    print(f"  TELEFONES INVÁLIDOS (linha recusada): {len(invalidos_fone)}")
    if invalidos_fone:
        print("      códigos para corrigir na planilha (o número não é mostrado): " + ", ".join(l.identificacao for l in invalidos_fone))
    print(f"  INVÁLIDAS (ignoradas, por qualquer motivo): {len(resumo['invalidas'])}")
    for l in resumo["invalidas"][:ex]:
        print(f"      {l.identificacao}: {'; '.join(l.motivos)}")
    if len(resumo["invalidas"]) > ex:
        print(f"      ... e mais {len(resumo['invalidas']) - ex}")
    for aviso in resultado.avisos:
        print(f"  Aviso: {aviso}")


def imprimir_previsao(previsao: dict) -> None:
    print("Previsão no banco:")
    print(f"  motoristas novos: {previsao['novos']}")
    print(f"  motoristas já existentes que serão atualizados: {previsao['atualizados']}")
    print(f"  motoristas PRESERVADOS (um operador editou na tela): {previsao['protegidos']}")


def _dsn_ou_none(url):
    if not url:
        return None
    try:
        return dsn_asyncpg(url)
    except ValueError as erro:
        sys.exit(f"\nERRO: DATABASE_URL inválida ({erro}): {mascarar_senha(url)}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Carga de motoristas a partir de um CSV (mostra o resumo; só grava com --gravar).")
    parser.add_argument("--csv", required=True, help="CSV de motoristas (em data/motoristas/, fora do git)")
    parser.add_argument("--gravar", action="store_true", help="grava no banco (DATABASE_URL) depois de mostrar a previsão e pedir confirmação")
    parser.add_argument("--sim", action="store_true", help="com --gravar, não pede a confirmação digitada")
    parser.add_argument("--apelidos", help="CSV de apelidos (nome_na_planilha, nome_da_loja) para os nomes de loja que as siglas não resolvem")
    parser.add_argument("--exportar-apelidos", help="escreve o modelo de apelidos (só os nomes de loja não encontrados ou ambíguos) neste CSV e não sobrescreve arquivo existente")
    parser.add_argument("--listar-todas", action="store_true", help="mostra no resumo TODAS as lojas não encontradas e ambíguas (por padrão, só as primeiras)")
    parser.add_argument("--sobrescrever-editados", action="store_true", help="permite sobrescrever motoristas que um operador editou na tela")
    args = parser.parse_args(argv)

    caminho = Path(args.csv)
    if not caminho.exists():
        disponiveis = sorted(p.name for p in PASTA_PADRAO.glob("*.csv")) if PASTA_PADRAO.exists() else []
        sys.exit(
            f"ERRO: não achei {caminho}.\n"
            + (f"CSVs em data/motoristas/: {', '.join(disponiveis)}. Use --csv com o nome certo." if disponiveis
               else "Coloque o CSV em data/motoristas/ (pasta fora do git) e use --csv com o nome do arquivo.")
        )
    if not esta_protegido_do_git(caminho):
        print(f"AVISO: {caminho} está no repositório e não é ignorado pelo git: não faça commit deste arquivo (tem dados pessoais).", file=sys.stderr)

    try:
        resultado = ler_csv_motoristas(caminho)
    except ValueError as erro:
        sys.exit(f"ERRO: {erro}")

    apelidos = None
    if args.apelidos:
        try:
            apelidos = ler_apelidos(args.apelidos)
        except (OSError, ValueError) as erro:
            sys.exit(f"ERRO: arquivo de apelidos: {erro}")
    if args.exportar_apelidos and Path(args.exportar_apelidos).exists():
        sys.exit(f"ERRO: {args.exportar_apelidos} já existe: escolha outro nome para não perder o que já foi preenchido.")

    dsn = _dsn_ou_none(os.getenv("DATABASE_URL"))
    aviso_lojas = None
    precisa_conferir_lojas = any(l.lojas_nomes for l in resultado.linhas)
    if precisa_conferir_lojas:
        if dsn is None:
            aviso_lojas = (
                "as lojas NÃO foram conferidas: defina DATABASE_URL (a conexão só lê as lojas, não grava nada) e rode de novo "
                "para ver quais nomes de loja não existem no cadastro."
            )
        else:
            cadastradas = asyncio.run(com_conexao(dsn, _ler_lojas_so_leitura))
            conferir_lojas(resultado, cadastradas, apelidos)
    resumo = resumir(resultado)
    imprimir_resumo(caminho, resultado, resumo, args.listar_todas)
    if aviso_lojas:
        print(f"\nAVISO: {aviso_lojas}")

    if args.exportar_apelidos:
        if not resultado.lojas_conferidas:
            sys.exit("\nERRO: para exportar o modelo de apelidos é preciso conferir as lojas no banco (defina DATABASE_URL; só leitura).")
        quantas = exportar_apelidos(args.exportar_apelidos, resultado, cadastradas)
        print(f"\nModelo de apelidos escrito em {args.exportar_apelidos} ({quantas} nome(s) de loja). Preencha a coluna nome_da_loja com o nome exato de uma loja cadastrada e use --apelidos.")

    linhas = para_gravar(resultado)
    if not args.gravar:
        print("\nNada foi gravado. Se o resumo estiver certo, rode de novo com --gravar.")
        return
    if not linhas:
        sys.exit("\nNada a gravar.")
    if dsn is None:
        sys.exit("\nERRO: defina a variável de ambiente DATABASE_URL (a string do banco) para gravar.")

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
    print(
        f"Gravado: {feito['novos']} motorista(s) novo(s), {feito['atualizados']} atualizado(s), "
        f"{feito['protegidos']} preservado(s), {feito['vinculos']} vínculo(s) com lojas acrescentado(s)."
    )


if __name__ == "__main__":
    main()
