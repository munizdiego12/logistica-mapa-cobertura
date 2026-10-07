"""
Faixas de CEP manuais (Etapa 2b, fase 1): schema da tabela ceps_reais, leitura e validação do CSV.

Módulo sem dependência de banco nem de rede: é usado pelo init_db (database.py), pelo
carregador (scripts/carregar_faixas.py) e pelos testes.
"""
import csv
from pathlib import Path

CAMINHO_CSV_PADRAO = Path(__file__).resolve().parent.parent / "scripts" / "data" / "faixas_cep.csv"

COLUNAS_CSV = ["cep_inicial", "cep_final", "uf", "cidade", "bairro", "lat", "lon", "ibge"]

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

# Caixa que contém o território brasileiro (inclui as ilhas oceânicas).
LAT_MIN, LAT_MAX = -34.0, 6.0
LON_MIN, LON_MAX = -74.0, -28.0

# Nunca faz DROP: recriar o schema é seguro em banco novo ou já populado.
SCHEMA_CEPS_REAIS = [
    """
    CREATE TABLE IF NOT EXISTS ceps_reais (
        id SERIAL PRIMARY KEY,
        cep_inicial VARCHAR(8) NOT NULL,
        cep_final VARCHAR(8) NOT NULL,
        uf VARCHAR(2) NOT NULL,
        cidade VARCHAR(100) NOT NULL,
        bairro VARCHAR(100) NOT NULL,
        lat NUMERIC(10, 7) NOT NULL,
        lon NUMERIC(10, 7) NOT NULL
    )
    """,
    "ALTER TABLE ceps_reais ADD COLUMN IF NOT EXISTS fonte TEXT NOT NULL DEFAULT 'manual'",
    "ALTER TABLE ceps_reais ADD COLUMN IF NOT EXISTS precisao TEXT NOT NULL DEFAULT 'faixa'",
    "ALTER TABLE ceps_reais ADD COLUMN IF NOT EXISTS ibge INTEGER",
    "CREATE INDEX IF NOT EXISTS idx_ceps_coords ON ceps_reais(lat, lon)",
]

# Separado porque falha se um banco antigo já tiver faixas duplicadas.
INDICE_UNICO_CEPS_REAIS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ceps_reais_faixa ON ceps_reais(cep_inicial, cep_final)"
)

UPSERT_CEPS_REAIS = """
    INSERT INTO ceps_reais (cep_inicial, cep_final, uf, cidade, bairro, lat, lon, fonte, precisao, ibge)
    VALUES %s
    ON CONFLICT (cep_inicial, cep_final) DO UPDATE SET
        uf = EXCLUDED.uf,
        cidade = EXCLUDED.cidade,
        bairro = EXCLUDED.bairro,
        lat = EXCLUDED.lat,
        lon = EXCLUDED.lon,
        fonte = EXCLUDED.fonte,
        precisao = EXCLUDED.precisao,
        ibge = EXCLUDED.ibge
    RETURNING (xmax = 0) AS inserido
"""


def ler_faixas_csv(caminho=CAMINHO_CSV_PADRAO) -> list:
    """Lê o CSV (UTF-8) e devolve uma lista de dicts com valores em texto (CEP mantém zeros à esquerda)."""
    with open(caminho, encoding="utf-8", newline="") as f:
        leitor = csv.DictReader(f)
        if leitor.fieldnames != COLUNAS_CSV:
            raise ValueError(f"Cabeçalho do CSV deve ser {COLUNAS_CSV}, veio {leitor.fieldnames}")
        return list(leitor)


def validar_faixas(faixas: list) -> list:
    """Devolve a lista de erros encontrados (vazia = válido). Não altera os dados."""
    erros = []
    validas = []  # (cep_inicial, cep_final, descricao) das linhas com CEP legível

    for n, f in enumerate(faixas, start=2):  # linha 1 do CSV é o cabeçalho
        rotulo = f"linha {n} ({f.get('cidade', '?')} {f.get('cep_inicial', '?')}-{f.get('cep_final', '?')})"
        ini, fim = f.get("cep_inicial", ""), f.get("cep_final", "")

        if not (len(ini) == 8 and ini.isdigit() and len(fim) == 8 and fim.isdigit()):
            erros.append(f"{rotulo}: CEP deve ter exatamente 8 dígitos")
        elif int(ini) > int(fim):
            erros.append(f"{rotulo}: cep_inicial maior que cep_final")
        else:
            validas.append((int(ini), int(fim), rotulo))

        if f.get("uf") not in UFS:
            erros.append(f"{rotulo}: UF inválida '{f.get('uf')}'")
        for campo in ("cidade", "bairro"):
            if not (f.get(campo) or "").strip():
                erros.append(f"{rotulo}: {campo} vazio")

        ibge = f.get("ibge") or ""
        if not (len(ibge) == 7 and ibge.isdigit()):
            erros.append(f"{rotulo}: código IBGE deve ter 7 dígitos")

        try:
            lat, lon = float(f["lat"]), float(f["lon"])
        except (KeyError, TypeError, ValueError):
            erros.append(f"{rotulo}: lat/lon ausentes ou não numéricas")
        else:
            if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
                erros.append(f"{rotulo}: coordenada ({lat}, {lon}) fora do Brasil")

    # Sobreposição: com as faixas ordenadas, cada uma deve começar depois do maior fim já visto.
    validas.sort()
    maior_fim, rotulo_maior = -1, ""
    for ini, fim, rotulo in validas:
        if ini <= maior_fim:
            erros.append(f"{rotulo}: sobrepõe {rotulo_maior}")
        if fim > maior_fim:
            maior_fim, rotulo_maior = fim, rotulo

    return erros
