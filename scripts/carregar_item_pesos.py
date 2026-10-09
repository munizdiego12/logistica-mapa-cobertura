"""
Carga inicial da tabela item_pesos a partir do CSV revisado (exportado do Google Sheets em português).

Só LÊ o arquivo e mostra um resumo, a menos que você passe --gravar. Nada é gravado sem a sua confirmação.
Usa asyncpg (o psycopg2 pode estar bloqueado no Windows) e lê a conexão SOMENTE da variável DATABASE_URL.

A tabela é criada antes pelo Alembic (dentro de backend/):  python -m alembic upgrade head

Passo 1 — só o resumo (não conecta no banco):
    python scripts/carregar_item_pesos.py --csv data/peso/item_pesos_revisado.csv

Passo 2 — gravar (mostra a previsão e pede a confirmação; PowerShell, string do banco só na sessão):
    $env:DATABASE_URL = "<string do Neon>"
    python scripts/carregar_item_pesos.py --csv data/peso/item_pesos_revisado.csv --gravar
    Remove-Item Env:DATABASE_URL

Regras:
    - aceita ';' ou ',' como separador e vírgula ou ponto como decimal; UTF-8 ou Windows-1252;
    - ignora as linhas com peso em branco ("sem peso"); --incluir-sem-peso as coloca na fila "sem peso";
    - nunca sobrescreve um peso que um operador editou na tela (--sobrescrever-editados muda isso);
    - o CSV deve ficar em data/peso/ (fora do git: o repositório é público).
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
from backend.item_pesos import (  # noqa: E402
    PESO_SUSPEITO_ALTO_KG,
    PESO_SUSPEITO_BAIXO_KG,
    esta_protegido_do_git,
    gravar_carga,
    ler_csv,
    prever_carga,
    resumir,
    separar_para_gravar,
)

CSV_PADRAO = RAIZ / "data" / "peso" / "item_pesos_revisado.csv"
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
                "ERRO: a tabela item_pesos ainda não existe no banco. Crie-a antes, dentro de backend/:\n"
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


def imprimir_resumo(caminho: Path, resultado, resumo: dict, incluir_sem_peso: bool) -> None:
    print(f"Arquivo: {caminho}")
    print(f"  separador: '{resultado.delimitador}' | codificação: {resultado.codificacao} | coluna de peso: \"{resultado.coluna_peso}\"")
    print(f"  linhas lidas: {resumo['linhas']}")
    print(f"  COM PESO (serão gravadas): {resumo['com_peso']}")
    destino = "serão colocadas na fila 'sem peso'" if incluir_sem_peso else "ignoradas; use --incluir-sem-peso para colocá-las na fila"
    print(f"  SEM PESO ({destino}): {resumo['sem_peso']}")
    print(f"  INVÁLIDAS (ignoradas): {resumo['invalido']}")
    for numero, id_sku, motivo in resumo["invalidos_exemplos"]:
        print(f"      linha {numero} (sku {id_sku}): {motivo}")
    if resumo["invalido"] > len(resumo["invalidos_exemplos"]):
        print(f"      ... e mais {resumo['invalido'] - len(resumo['invalidos_exemplos'])}")
    if resumo["duplicado_ignorado"]:
        print(f"  Repetidas (vale a última linha do mesmo SKU): {resumo['duplicado_ignorado']}")
    if resumo["total_suspeitos"]:
        print(f"  Para conferir (peso acima de {PESO_SUSPEITO_ALTO_KG} kg ou abaixo de {float(PESO_SUSPEITO_BAIXO_KG) * 1000:g} g, mas válidos): {resumo['total_suspeitos']}")
        for numero, id_sku, peso, nome in resumo["suspeitos"]:
            print(f"      linha {numero} (sku {id_sku}): {peso:g} kg  {nome[:50]}")
    for aviso in resultado.avisos:
        print(f"  Aviso: {aviso}")


def imprimir_previsao(previsao: dict) -> None:
    print("Previsão no banco:")
    print(f"  itens novos: {previsao['novos']}")
    print(f"  itens já existentes que serão atualizados: {previsao['atualizados']}")
    print(f"  itens PRESERVADOS (um operador editou o peso na tela): {previsao['preservados_editados']}")
    if previsao["sem_peso_novos"] or previsao["sem_peso_ja_existentes"]:
        print(f"  sem peso: {previsao['sem_peso_novos']} novos na fila; {previsao['sem_peso_ja_existentes']} já existiam (não mudam)")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Carga inicial de item_pesos a partir do CSV revisado (mostra o resumo; só grava com --gravar).")
    parser.add_argument("--csv", default=str(CSV_PADRAO), help="CSV revisado (padrão: data/peso/item_pesos_revisado.csv)")
    parser.add_argument("--gravar", action="store_true", help="grava no banco (DATABASE_URL) depois de mostrar a previsão e pedir confirmação")
    parser.add_argument("--sim", action="store_true", help="com --gravar, não pede a confirmação digitada")
    parser.add_argument("--incluir-sem-peso", action="store_true", help="coloca na fila 'sem peso' os itens com peso em branco")
    parser.add_argument("--sobrescrever-editados", action="store_true", help="permite sobrescrever pesos que um operador editou na tela")
    args = parser.parse_args(argv)

    caminho = Path(args.csv)
    if not caminho.exists():
        disponiveis = sorted(p.name for p in (RAIZ / "data" / "peso").glob("*.csv")) if (RAIZ / "data" / "peso").exists() else []
        sys.exit(
            f"ERRO: não achei {caminho}.\n"
            + (f"CSVs em data/peso/: {', '.join(disponiveis)}. Use --csv com o nome certo." if disponiveis
               else "Coloque o CSV revisado em data/peso/ (pasta fora do git) e use --csv com o nome do arquivo.")
        )
    if not esta_protegido_do_git(caminho):
        print(f"AVISO: {caminho} está no repositório e não é ignorado pelo git: não faça commit deste arquivo.", file=sys.stderr)

    try:
        resultado = ler_csv(caminho)
    except ValueError as erro:
        sys.exit(f"ERRO: {erro}")
    resumo = resumir(resultado)
    imprimir_resumo(caminho, resultado, resumo, args.incluir_sem_peso)

    com_peso, sem_peso = separar_para_gravar(resultado, args.incluir_sem_peso)
    if not args.gravar:
        print("\nNada foi gravado (nem conectei no banco). Se o resumo estiver certo, rode de novo com --gravar.")
        return
    if not com_peso and not sem_peso:
        sys.exit("\nNada a gravar.")

    url = os.getenv("DATABASE_URL")
    if not url:
        sys.exit("\nERRO: defina a variável de ambiente DATABASE_URL (a string do banco) para gravar.")
    try:
        dsn = dsn_asyncpg(url)
    except ValueError as erro:
        sys.exit(f"\nERRO: DATABASE_URL inválida ({erro}): {mascarar_senha(url)}")

    previsao = asyncio.run(com_conexao(dsn, lambda c: prever_carga(c, com_peso, sem_peso, args.sobrescrever_editados)))
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
    asyncio.run(com_conexao(dsn, lambda c: gravar_carga(c, com_peso, sem_peso, args.sobrescrever_editados)))
    print(f"Gravado: {len(com_peso)} item(ns) com peso" + (f" e {len(sem_peso)} sem peso na fila" if sem_peso else "") + ".")


if __name__ == "__main__":
    main()
