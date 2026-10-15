"""
Carga das lojas a partir de um CSV (exportado do Google Sheets em português ou do Google My Maps).

Só LÊ o arquivo e mostra um resumo, a menos que você passe --gravar. Nada é gravado sem a sua confirmação.
Usa asyncpg (o psycopg2 pode estar bloqueado no Windows) e lê a conexão SOMENTE da variável DATABASE_URL.

A tabela é criada antes pelo Alembic (dentro de backend/):  python -m alembic upgrade head

Colunas aceitas:
    Nome, Estado, Endereço, Latitude, Longitude   (Endereço pode ficar em branco; a filial já vai no nome, ex.: "Atacadão Guarujá")
    ou o formato do Google My Maps: WKT (POINT (longitude latitude)), name, description (o Estado não vem: a loja entra sem
    Estado e o operador completa na tela "Lojas").

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

from backend.db_url import dsn_asyncpg, mascarar_senha  # noqa: E402
from backend.item_pesos import esta_protegido_do_git  # noqa: E402
from backend.lojas import gravar_carga, ler_csv_lojas, para_gravar, prever_carga, resumir  # noqa: E402

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
        except asyncpg.UndefinedTableError:
            sys.exit(
                "ERRO: a tabela lojas ainda não existe no banco. Crie-a antes, dentro de backend/:\n"
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
    formato = "Google My Maps (WKT, name, description)" if resultado.formato == "my_maps" else "colunas Nome, Estado, Endereço, Latitude, Longitude"
    print(f"Arquivo: {caminho}")
    print(f"  formato: {formato} | separador: '{resultado.delimitador}' | codificação: {resultado.codificacao}")
    print(f"  linhas lidas: {resumo['linhas']}")
    print(f"  LOJAS VÁLIDAS (serão gravadas): {resumo['validas']}")
    print(f"      sem endereço: {resumo['sem_endereco']}")
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


def imprimir_previsao(previsao: dict) -> None:
    print("Previsão no banco:")
    print(f"  lojas novas: {previsao['novas']}")
    print(f"  lojas já existentes que serão atualizadas: {previsao['atualizadas']}")
    print(f"  lojas PRESERVADAS (um operador editou na tela): {previsao['protegidas']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Carga de lojas a partir de um CSV (mostra o resumo; só grava com --gravar).")
    parser.add_argument("--csv", required=True, help="CSV de lojas (em data/lojas/, fora do git)")
    parser.add_argument("--gravar", action="store_true", help="grava no banco (DATABASE_URL) depois de mostrar a previsão e pedir confirmação")
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
