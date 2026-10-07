"""
Carga offline do CNEFE 2022 (IBGE) por prefixo de CEP de 5 dígitos (Etapa 2b, fase 2).

Baixa o CSV da UF (fica em data/cnefe/, fora do git), calcula por prefixo a mediana das coordenadas,
o número de endereços e a dispersão (raio com 90% dos pontos) e grava na tabela cep_prefixos com
upsert pela chave (prefixo): nunca apaga a tabela nem linhas existentes.

Uso (testado só com o AC; UFs grandes exigem mais memória, ~30 bytes por endereço):
    python scripts/carregar_cnefe.py --uf AC --sqlite data/cnefe/teste_ac.db   # SQLite local
    python scripts/carregar_cnefe.py --uf AC                                   # Postgres via DATABASE_URL

A URL do Postgres NUNCA deve ficar escrita em arquivo. Configure só na sessão:
    export DATABASE_URL="postgresql://usuario:senha@host/nome_do_banco"   (Linux/macOS)
    $env:DATABASE_URL="postgresql://usuario:senha@host/nome_do_banco"     (PowerShell)

Fonte dos dados: IBGE, CNEFE 2022. Exportações que usem esta tabela devem trazer essa atribuição.
"""
import argparse
import os
import sqlite3
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from backend.cnefe import COLUNAS_CNEFE, agregar_prefixos, gravar_postgres, gravar_sqlite  # noqa: E402

URL_BASE = (
    "https://ftp.ibge.gov.br/Cadastro_Nacional_de_Enderecos_para_Fins_Estatisticos/"
    "Censo_Demografico_2022/Arquivos_CNEFE/CSV/UF/"
)
CODIGOS_UF = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17, "MA": 21, "PI": 22,
    "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27, "SE": 28, "BA": 29, "MG": 31, "ES": 32,
    "RJ": 33, "SP": 35, "PR": 41, "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}
RAIZ = Path(__file__).resolve().parent.parent
PASTA_PADRAO = RAIZ / "data" / "cnefe"
LINHAS_POR_BLOCO = 500_000


def baixar_uf(uf: str, pasta: Path) -> Path:
    nome = f"{CODIGOS_UF[uf]}_{uf}.zip"
    destino = pasta / nome
    if destino.exists():
        print(f"Usando arquivo já baixado: {destino}")
        return destino
    pasta.mkdir(parents=True, exist_ok=True)
    print(f"Baixando {URL_BASE}{nome} ...")
    parcial = destino.with_suffix(".zip.parcial")
    urllib.request.urlretrieve(URL_BASE + nome, parcial)
    parcial.replace(destino)
    print(f"Baixado: {destino.stat().st_size / 1e6:.1f} MB")
    return destino


def ler_blocos(arquivo_zip: Path):
    with zipfile.ZipFile(arquivo_zip) as z:
        nome_csv = next(n for n in z.namelist() if n.lower().endswith(".csv"))
        with z.open(nome_csv) as f:
            yield from pd.read_csv(
                f, sep=";", dtype=str, usecols=COLUNAS_CNEFE, encoding="utf-8", chunksize=LINHAS_POR_BLOCO
            )


def main():
    parser = argparse.ArgumentParser(description="Agrega o CNEFE 2022 por prefixo de CEP e grava com upsert.")
    parser.add_argument("--uf", required=True, choices=sorted(CODIGOS_UF), help="UF a processar")
    parser.add_argument("--sqlite", metavar="ARQUIVO", help="grava num SQLite local em vez do Postgres")
    parser.add_argument("--pasta", default=str(PASTA_PADRAO), help="onde guardar o download (padrão: data/cnefe)")
    args = parser.parse_args()

    database_url = None
    if not args.sqlite:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            sys.exit("ERRO: defina DATABASE_URL (Postgres) ou use --sqlite ARQUIVO para um teste local.")
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)

    arquivo = baixar_uf(args.uf, Path(args.pasta))
    linhas, est = agregar_prefixos(ler_blocos(arquivo), args.uf)
    print(
        f"Endereços lidos: {est['linhas_lidas']:,} | descartados: {est['linhas_descartadas']:,} | "
        f"prefixos: {est['prefixos']} | prefixos sem ponto de nível 1/2: {est['prefixos_sem_ponto_exato']}"
    )
    if not linhas:
        sys.exit("ERRO: nenhum prefixo calculado; nada foi gravado.")

    if args.sqlite:
        Path(args.sqlite).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(args.sqlite)
        try:
            novas, atualizadas = gravar_sqlite(conn, linhas)
        finally:
            conn.close()
        destino = f"SQLite {args.sqlite}"
    else:
        import psycopg2

        conn = psycopg2.connect(database_url)
        try:
            novas, atualizadas = gravar_postgres(conn, linhas)
        finally:
            conn.close()
        destino = "Postgres (DATABASE_URL)"
    print(f"Sucesso em {destino}: {novas} prefixo(s) novo(s), {atualizadas} atualizado(s).")


if __name__ == "__main__":
    main()
