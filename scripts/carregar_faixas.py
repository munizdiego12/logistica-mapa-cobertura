"""
Carrega as faixas de CEP manuais (scripts/data/faixas_cep.csv) na tabela ceps_reais.

Faz upsert pela chave (cep_inicial, cep_final): nunca apaga a tabela nem linhas existentes,
então pode ser rodado quantas vezes for preciso.

Uso:
    python scripts/carregar_faixas.py --validar     # só valida o CSV, sem tocar no banco
    python scripts/carregar_faixas.py               # valida e carrega (exige DATABASE_URL)

A URL de conexão NUNCA deve ficar escrita no código-fonte. Configure antes de rodar:
    export DATABASE_URL="postgresql://usuario:senha@host/nome_do_banco"   (Linux/macOS)
    $env:DATABASE_URL="postgresql://usuario:senha@host/nome_do_banco"     (PowerShell)
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.faixas_cep import (  # noqa: E402
    CAMINHO_CSV_PADRAO,
    INDICE_UNICO_CEPS_REAIS,
    SCHEMA_CEPS_REAIS,
    UPSERT_CEPS_REAIS,
    ler_faixas_csv,
    validar_faixas,
)

FONTE = "manual"
PRECISAO = "faixa"


def main():
    parser = argparse.ArgumentParser(description="Carrega as faixas de CEP manuais em ceps_reais (upsert).")
    parser.add_argument("--csv", default=str(CAMINHO_CSV_PADRAO), help="caminho do CSV de faixas")
    parser.add_argument("--validar", action="store_true", help="só valida o CSV, sem conectar no banco")
    args = parser.parse_args()

    faixas = ler_faixas_csv(args.csv)
    erros = validar_faixas(faixas)
    if erros:
        print(f"CSV inválido ({len(erros)} erro(s)); nada foi gravado:")
        for erro in erros:
            print(f"  - {erro}")
        sys.exit(1)
    print(f"CSV válido: {len(faixas)} faixas.")
    if args.validar:
        return

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        sys.exit("ERRO: a variável de ambiente DATABASE_URL não está definida.")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    import psycopg2
    from psycopg2.extras import execute_values

    linhas = [
        (f["cep_inicial"], f["cep_final"], f["uf"], f["cidade"], f["bairro"],
         float(f["lat"]), float(f["lon"]), FONTE, PRECISAO, int(f["ibge"]))
        for f in faixas
    ]

    conn = psycopg2.connect(database_url)
    try:
        with conn, conn.cursor() as cur:  # um único commit: ou grava tudo, ou nada
            for comando in SCHEMA_CEPS_REAIS:
                cur.execute(comando)
            try:
                cur.execute(INDICE_UNICO_CEPS_REAIS)
            except psycopg2.Error as e:
                sys.exit(
                    "ERRO: não foi possível criar o índice único (cep_inicial, cep_final). "
                    f"A tabela ceps_reais já tem faixas duplicadas; remova-as e rode de novo.\n{e}"
                )
            resultado = execute_values(cur, UPSERT_CEPS_REAIS, linhas, fetch=True)
    finally:
        conn.close()

    novas = sum(1 for (inserido,) in resultado if inserido)
    print(f"Sucesso: {novas} faixa(s) nova(s), {len(resultado) - novas} atualizada(s).")


if __name__ == "__main__":
    main()
