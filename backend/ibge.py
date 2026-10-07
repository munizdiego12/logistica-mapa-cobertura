"""
Tabela de municípios do IBGE (código, nome, UF): schema, leitura/validação do CSV e gravação.

Serve para trocar os códigos IBGE fixos por busca real (cidade + UF -> código) e para dar nome ao
código de município que o CNEFE traz (cep_prefixos.cod_municipio).

Fonte: API de localidades do IBGE (gratuita). O CSV em scripts/data/municipios_ibge.csv é um retrato
dela, para a carga não depender da API; scripts/carregar_municipios.py --baixar o atualiza.
"""
import csv
import gzip
import json
import unicodedata
import urllib.request
from pathlib import Path

CAMINHO_CSV_PADRAO = Path(__file__).resolve().parent.parent / "scripts" / "data" / "municipios_ibge.csv"
URL_API_MUNICIPIOS = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado"

COLUNAS_CSV = ["codigo", "nome", "uf"]

# Os dois primeiros dígitos do código do município identificam a UF.
CODIGO_UF = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17, "MA": 21, "PI": 22,
    "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27, "SE": 28, "BA": 29, "MG": 31, "ES": 32,
    "RJ": 33, "SP": 35, "PR": 41, "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}

# Nunca faz DROP. Sintaxe aceita por Postgres e SQLite.
SCHEMA_IBGE_MUNICIPIOS = [
    """
    CREATE TABLE IF NOT EXISTS ibge_municipios (
        codigo INTEGER PRIMARY KEY,
        nome TEXT NOT NULL,
        uf VARCHAR(2) NOT NULL,
        nome_normalizado TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ibge_municipios_uf_nome ON ibge_municipios(uf, nome_normalizado)",
]

_COLUNAS_DB = ["codigo", "nome", "uf", "nome_normalizado"]
UPSERT_POSTGRES = (
    "INSERT INTO ibge_municipios (codigo, nome, uf, nome_normalizado) VALUES %s "
    "ON CONFLICT (codigo) DO UPDATE SET nome = EXCLUDED.nome, uf = EXCLUDED.uf, "
    "nome_normalizado = EXCLUDED.nome_normalizado RETURNING (xmax = 0) AS inserido"
)
UPSERT_SQLITE = (
    "INSERT INTO ibge_municipios (codigo, nome, uf, nome_normalizado) VALUES (?, ?, ?, ?) "
    "ON CONFLICT (codigo) DO UPDATE SET nome = EXCLUDED.nome, uf = EXCLUDED.uf, "
    "nome_normalizado = EXCLUDED.nome_normalizado"
)


def normalizar_nome(nome) -> str:
    """Maiúsculas, sem acentos e com espaços simples: 'São  Luís' -> 'SAO LUIS'. Usado na busca por nome."""
    sem_acento = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(sem_acento.upper().split())


def baixar_municipios_api(url: str = URL_API_MUNICIPIOS) -> list:
    with urllib.request.urlopen(url, timeout=60) as resposta:
        bruto = resposta.read()
    if bruto[:2] == b"\x1f\x8b":  # a API do IBGE responde em gzip
        bruto = gzip.decompress(bruto)
    dados = json.loads(bruto.decode("utf-8"))
    return sorted(
        ({"codigo": str(d["municipio-id"]), "nome": d["municipio-nome"], "uf": d["UF-sigla"]} for d in dados),
        key=lambda m: int(m["codigo"]),
    )


def escrever_municipios_csv(municipios: list, caminho=CAMINHO_CSV_PADRAO) -> None:
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS_CSV, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(municipios)


def ler_municipios_csv(caminho=CAMINHO_CSV_PADRAO) -> list:
    with open(caminho, encoding="utf-8", newline="") as f:
        leitor = csv.DictReader(f)
        if leitor.fieldnames != COLUNAS_CSV:
            raise ValueError(f"Cabeçalho do CSV deve ser {COLUNAS_CSV}, veio {leitor.fieldnames}")
        return list(leitor)


def validar_municipios(municipios: list) -> list:
    """Devolve a lista de erros (vazia = válido): código de 7 dígitos coerente com a UF, nome preenchido, sem repetição."""
    erros, vistos = [], set()
    for n, m in enumerate(municipios, start=2):
        codigo, uf = m.get("codigo", ""), m.get("uf")
        rotulo = f"linha {n} ({m.get('nome', '?')}/{uf})"
        if not (len(codigo) == 7 and codigo.isdigit()):
            erros.append(f"{rotulo}: código deve ter 7 dígitos")
            continue
        if uf not in CODIGO_UF:
            erros.append(f"{rotulo}: UF inválida")
        elif int(codigo) // 100000 != CODIGO_UF[uf]:
            erros.append(f"{rotulo}: código {codigo} não pertence à UF {uf}")
        if not (m.get("nome") or "").strip():
            erros.append(f"{rotulo}: nome vazio")
        if codigo in vistos:
            erros.append(f"{rotulo}: código {codigo} repetido")
        vistos.add(codigo)
    if not 5500 <= len(municipios) <= 5600:
        erros.append(f"quantidade inesperada de municípios: {len(municipios)} (esperado ~5.571)")
    return erros


def _tuplas(municipios: list) -> list:
    return [(int(m["codigo"]), m["nome"], m["uf"], normalizar_nome(m["nome"])) for m in municipios]


def indice_por_uf_e_nome(municipios: list) -> dict:
    """{(uf, nome normalizado): código} para casar nomes de cidade com o código IBGE."""
    return {(m["uf"], normalizar_nome(m["nome"])): int(m["codigo"]) for m in municipios}


def gravar_sqlite(conn, municipios: list) -> tuple:
    """Upsert em SQLite. Devolve (novos, atualizados)."""
    for comando in SCHEMA_IBGE_MUNICIPIOS:
        conn.execute(comando)
    existentes = {r[0] for r in conn.execute("SELECT codigo FROM ibge_municipios")}
    conn.executemany(UPSERT_SQLITE, _tuplas(municipios))
    conn.commit()
    novos = sum(1 for m in municipios if int(m["codigo"]) not in existentes)
    return novos, len(municipios) - novos


def gravar_postgres(conn, municipios: list) -> tuple:
    """Upsert em Postgres (conexão psycopg2), em uma única transação. Devolve (novos, atualizados)."""
    from psycopg2.extras import execute_values

    with conn, conn.cursor() as cur:
        for comando in SCHEMA_IBGE_MUNICIPIOS:
            cur.execute(comando)
        resultado = execute_values(cur, UPSERT_POSTGRES, _tuplas(municipios), fetch=True)
    novos = sum(1 for (inserido,) in resultado if inserido)
    return novos, len(resultado) - novos
