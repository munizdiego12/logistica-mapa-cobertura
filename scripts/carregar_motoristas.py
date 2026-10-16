"""
Carga dos motoristas a partir de um CSV (Etapa 6b).

Só LÊ o arquivo e mostra um resumo, a menos que você passe --gravar. Nada é gravado sem a sua confirmação digitada.
Usa asyncpg (o psycopg2 pode estar bloqueado no Windows) e lê a conexão SOMENTE da variável DATABASE_URL.

As tabelas e colunas são criadas antes pelo Alembic (dentro de backend/):  python -m alembic upgrade head   (revisão 0008)
As lojas precisam estar cadastradas antes (scripts/carregar_lojas.py).

Colunas aceitas (reconhecidas pelo NOME do cabeçalho, em qualquer ordem, sem diferença de maiúsculas, acentos ou espaços):
    Código (obrigatória: é a chave da carga); Nome; Tipo de veículo (Passeio, Carro de passeio, Utilitário, Fiorino,
    Fiorino/Utilitário e variações); Lojas (nomes separados por ';' ou '|', exatamente como estão cadastradas; se o CSV
    usa ';' como separador, use '|' entre as lojas ou coloque a célula entre aspas); Diária (opcional; vírgula ou ponto
    decimal); Telefone (opcional; com DDD).

Passo 1 — resumo. Para conferir os nomes das lojas o script lê as lojas do banco (SÓ LEITURA); se DATABASE_URL não estiver
definida, o resumo avisa e segue sem conferir as lojas:
    $env:DATABASE_URL = "<string do Neon>"
    python scripts/carregar_motoristas.py --csv data/motoristas/motoristas.csv

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
    ROTULOS_DAS_COLUNAS, conferir_lojas, gravar_carga, ler_csv_motoristas, ler_lojas, para_gravar, prever_carga, resumir,
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


def imprimir_resumo(caminho: Path, resultado, resumo: dict) -> None:
    ex = resumo["exemplos"]
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
        for nome, quantas in nao.most_common(ex):
            print(f"      \"{nome}\": {quantas} motorista(s)")
        if len(nao) > ex:
            print(f"      ... e mais {len(nao) - ex}")
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
            conferir_lojas(resultado, cadastradas)
    resumo = resumir(resultado)
    imprimir_resumo(caminho, resultado, resumo)
    if aviso_lojas:
        print(f"\nAVISO: {aviso_lojas}")

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
