"""
Carrega os municípios do IBGE (código, nome, UF) na tabela ibge_municipios, com upsert pelo código.

Nunca apaga a tabela nem linhas existentes; pode ser rodado quantas vezes for preciso.

Uso:
    python scripts/carregar_municipios.py --validar             # só valida o CSV, sem tocar no banco
    python scripts/carregar_municipios.py --baixar              # atualiza o CSV a partir da API do IBGE
    python scripts/carregar_municipios.py --sqlite ARQUIVO      # grava num SQLite local
    python scripts/carregar_municipios.py                       # grava no Postgres (exige DATABASE_URL)

A URL do Postgres NUNCA deve ficar escrita em arquivo. Configure só na sessão:
    $env:DATABASE_URL="postgresql://usuario:senha@host/nome_do_banco"     (PowerShell)
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.ibge import (  # noqa: E402
    CAMINHO_CSV_PADRAO,
    baixar_municipios_api,
    escrever_municipios_csv,
    gravar_postgres,
    gravar_sqlite,
    ler_municipios_csv,
    validar_municipios,
)


def main():
    parser = argparse.ArgumentParser(description="Carrega os municípios do IBGE em ibge_municipios (upsert).")
    parser.add_argument("--csv", default=str(CAMINHO_CSV_PADRAO), help="caminho do CSV de municípios")
    parser.add_argument("--validar", action="store_true", help="só valida o CSV, sem conectar no banco")
    parser.add_argument("--baixar", action="store_true", help="atualiza o CSV a partir da API do IBGE antes de seguir")
    parser.add_argument("--sqlite", metavar="ARQUIVO", help="grava num SQLite local em vez do Postgres")
    args = parser.parse_args()

    if args.baixar:
        baixados = baixar_municipios_api()
        erros = validar_municipios(baixados)
        if erros:
            sys.exit("Dados baixados da API são inválidos; CSV não foi alterado:\n  - " + "\n  - ".join(erros))
        escrever_municipios_csv(baixados, args.csv)
        print(f"CSV atualizado a partir da API do IBGE: {len(baixados)} municípios.")

    municipios = ler_municipios_csv(args.csv)
    erros = validar_municipios(municipios)
    if erros:
        print(f"CSV inválido ({len(erros)} erro(s)); nada foi gravado:")
        for erro in erros[:20]:
            print(f"  - {erro}")
        sys.exit(1)
    print(f"CSV válido: {len(municipios)} municípios.")
    if args.validar:
        return

    if args.sqlite:
        Path(args.sqlite).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(args.sqlite)
        try:
            novos, atualizados = gravar_sqlite(conn, municipios)
        finally:
            conn.close()
        destino = f"SQLite {args.sqlite}"
    else:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            sys.exit("ERRO: defina DATABASE_URL (Postgres) ou use --sqlite ARQUIVO para um teste local.")
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        import psycopg2

        conn = psycopg2.connect(database_url)
        try:
            novos, atualizados = gravar_postgres(conn, municipios)
        finally:
            conn.close()
        destino = "Postgres (DATABASE_URL)"
    print(f"Sucesso em {destino}: {novos} município(s) novo(s), {atualizados} atualizado(s).")


if __name__ == "__main__":
    main()
