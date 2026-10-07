"""
Base nacional de CEP via CNEFE 2022 do IBGE (Etapa 2b, fase 2): agregação por prefixo de 5 dígitos.

Cada prefixo (XXXXX-000 a XXXXX-999) vira uma linha com o ponto central (mediana das coordenadas
dos endereços), a quantidade de endereços, a dispersão (raio que contém 90% dos pontos) e a
localidade (bairro) mais frequente, com o percentual de endereços que ela representa.

Sem acesso a rede nem a banco na parte de agregação: o download e a gravação ficam em
scripts/carregar_cnefe.py. As funções de gravação recebem a conexão pronta.
"""
import numpy as np
import pandas as pd

from backend.faixas_cep import LAT_MAX, LAT_MIN, LON_MAX, LON_MIN

FONTE = "IBGE, CNEFE 2022"

# NV_GEO_COORD: 1 = coordenada original do Censo; 2 = original modificada (apartamentos no mesmo número).
# 3 a 6 são estimativas (sem coordenada, face de quadra, localidade, setor) e puxariam a mediana para
# o centro do setor, então só entram no cálculo se o prefixo não tiver nenhum ponto de nível 1 ou 2.
NIVEIS_COORDENADA_EXATA = ("1", "2")

COLUNAS_CNEFE = ["COD_MUNICIPIO", "CEP", "LATITUDE", "LONGITUDE", "NV_GEO_COORD", "DSC_LOCALIDADE"]

COLUNAS_SAIDA = [
    "prefixo", "uf", "cod_municipio", "localidade", "localidade_pct", "lat", "lon",
    "n_enderecos", "n_pontos_exatos", "dispersao_km", "fonte",
]

# Nunca faz DROP. Sintaxe aceita por Postgres e SQLite.
SCHEMA_CEP_PREFIXOS = """
    CREATE TABLE IF NOT EXISTS cep_prefixos (
        prefixo VARCHAR(5) PRIMARY KEY,
        uf VARCHAR(2) NOT NULL,
        cod_municipio INTEGER NOT NULL,
        localidade TEXT,
        localidade_pct REAL,
        lat DOUBLE PRECISION NOT NULL,
        lon DOUBLE PRECISION NOT NULL,
        n_enderecos INTEGER NOT NULL,
        n_pontos_exatos INTEGER NOT NULL,
        dispersao_km REAL NOT NULL,
        fonte TEXT NOT NULL DEFAULT 'IBGE, CNEFE 2022'
    )
"""

# Colunas acrescentadas depois da primeira versão da tabela (a do AC já gravada no Neon não as tem).
COLUNAS_ACRESCENTADAS = {"localidade": "TEXT", "localidade_pct": "REAL"}
MIGRACOES_POSTGRES = [
    f"ALTER TABLE cep_prefixos ADD COLUMN IF NOT EXISTS {coluna} {tipo}"
    for coluna, tipo in COLUNAS_ACRESCENTADAS.items()
]

_ATUALIZAR = ", ".join(f"{c} = EXCLUDED.{c}" for c in COLUNAS_SAIDA if c != "prefixo")
_COLUNAS_SQL = ", ".join(COLUNAS_SAIDA)

UPSERT_POSTGRES = (
    f"INSERT INTO cep_prefixos ({_COLUNAS_SQL}) VALUES %s "
    f"ON CONFLICT (prefixo) DO UPDATE SET {_ATUALIZAR} RETURNING (xmax = 0) AS inserido"
)
UPSERT_SQLITE = (
    f"INSERT INTO cep_prefixos ({_COLUNAS_SQL}) VALUES ({', '.join('?' * len(COLUNAS_SAIDA))}) "
    f"ON CONFLICT (prefixo) DO UPDATE SET {_ATUALIZAR}"
)


def _haversine_km(lat0: float, lon0: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    lat1, lon1 = np.radians(lat0), np.radians(lon0)
    lat2, lon2 = np.radians(lats), np.radians(lons)
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


class _Vocabulario:
    """Troca o nome da localidade por um inteiro (economiza memória em UFs com milhões de endereços)."""

    def __init__(self):
        self._ids = {}
        self.nomes = []

    def codigos(self, serie: pd.Series) -> pd.Series:
        valores = serie.astype("string").fillna("").str.strip()
        for v in valores.unique():
            if v not in self._ids:
                self._ids[v] = len(self.nomes)
                self.nomes.append(v)
        return valores.map(self._ids).astype("int32")

    def id_vazio(self) -> int:
        return self._ids.get("", -1)


def limpar_chunk(chunk: pd.DataFrame, vocabulario: _Vocabulario = None) -> tuple:
    """Devolve (linhas válidas já tipadas, quantidade descartada). Descarta CEP fora de 8 dígitos e coordenada inválida."""
    vocabulario = vocabulario or _Vocabulario()
    cep = chunk["CEP"].astype("string").str.strip()
    lat = pd.to_numeric(chunk["LATITUDE"], errors="coerce")
    lon = pd.to_numeric(chunk["LONGITUDE"], errors="coerce")
    valido = (
        cep.str.fullmatch(r"\d{8}").fillna(False).astype(bool)
        & lat.between(LAT_MIN, LAT_MAX)
        & lon.between(LON_MIN, LON_MAX)
        & pd.to_numeric(chunk["COD_MUNICIPIO"], errors="coerce").notna()
    )
    limpo = pd.DataFrame({
        "prefixo": cep[valido].str[:5].astype("int32"),
        "mun": pd.to_numeric(chunk.loc[valido, "COD_MUNICIPIO"]).astype("int32"),
        "lat": lat[valido].astype("float64"),
        "lon": lon[valido].astype("float64"),
        "loc": vocabulario.codigos(chunk.loc[valido, "DSC_LOCALIDADE"]).to_numpy(),
        "exato": chunk.loc[valido, "NV_GEO_COORD"].astype("string").str.strip().isin(NIVEIS_COORDENADA_EXATA).to_numpy(),
    })
    return limpo, int((~valido).sum())


def _localidade_mais_frequente(codigos: pd.Series, vocabulario: _Vocabulario) -> tuple:
    """(nome, % dos endereços do prefixo) da localidade mais frequente; empate resolvido pelo nome. Sem nome: (None, 0.0)."""
    contagem = codigos[codigos != vocabulario.id_vazio()].value_counts()
    if contagem.empty:
        return None, 0.0
    candidatos = contagem[contagem == contagem.max()].index
    nome = min(vocabulario.nomes[i] for i in candidatos)
    return nome, round(100.0 * int(contagem.max()) / len(codigos), 1)


def agregar_prefixos(chunks, uf: str) -> tuple:
    """
    Agrega os endereços por prefixo de CEP de 5 dígitos.

    chunks: iterável de DataFrames com as colunas de COLUNAS_CNEFE (strings, como vêm do CSV).
    Devolve (lista de dicts com as COLUNAS_SAIDA, estatísticas do processamento).
    """
    vocabulario = _Vocabulario()
    partes, lidas, descartadas = [], 0, 0
    for chunk in chunks:
        lidas += len(chunk)
        limpo, descartes = limpar_chunk(chunk, vocabulario)
        descartadas += descartes
        partes.append(limpo)

    estatisticas = {"linhas_lidas": lidas, "linhas_descartadas": descartadas, "prefixos": 0, "prefixos_sem_ponto_exato": 0}
    if not partes or sum(len(p) for p in partes) == 0:
        return [], estatisticas
    todos = pd.concat(partes, ignore_index=True)

    saida = []
    for prefixo, g in todos.groupby("prefixo", sort=True):
        exatos = g[g["exato"]]
        usados = exatos if len(exatos) else g
        lat, lon = float(np.median(usados["lat"])), float(np.median(usados["lon"]))
        dispersao = float(np.percentile(_haversine_km(lat, lon, usados["lat"].to_numpy(), usados["lon"].to_numpy()), 90))
        localidade, localidade_pct = _localidade_mais_frequente(g["loc"], vocabulario)
        saida.append({
            "prefixo": f"{int(prefixo):05d}",
            "uf": uf,
            "cod_municipio": int(g["mun"].mode().iloc[0]),  # município com mais endereços no prefixo
            "localidade": localidade,
            "localidade_pct": localidade_pct,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "n_enderecos": int(len(g)),
            "n_pontos_exatos": int(len(exatos)),
            "dispersao_km": round(dispersao, 3),
            "fonte": FONTE,
        })

    estatisticas["prefixos"] = len(saida)
    estatisticas["prefixos_sem_ponto_exato"] = sum(1 for r in saida if r["n_pontos_exatos"] == 0)
    return saida, estatisticas


def _tuplas(linhas: list) -> list:
    return [tuple(l[c] for c in COLUNAS_SAIDA) for l in linhas]


def gravar_sqlite(conn, linhas: list) -> tuple:
    """Upsert em SQLite. Devolve (novas, atualizadas)."""
    conn.execute(SCHEMA_CEP_PREFIXOS)
    # SQLite não tem ADD COLUMN IF NOT EXISTS: acrescenta só o que falta (banco criado numa versão anterior).
    atuais = {r[1] for r in conn.execute("PRAGMA table_info(cep_prefixos)")}
    for coluna, tipo in COLUNAS_ACRESCENTADAS.items():
        if coluna not in atuais:
            conn.execute(f"ALTER TABLE cep_prefixos ADD COLUMN {coluna} {tipo}")
    existentes = {r[0] for r in conn.execute("SELECT prefixo FROM cep_prefixos")}
    conn.executemany(UPSERT_SQLITE, _tuplas(linhas))
    conn.commit()
    novas = sum(1 for l in linhas if l["prefixo"] not in existentes)
    return novas, len(linhas) - novas


def gravar_postgres(conn, linhas: list) -> tuple:
    """Upsert em Postgres (conexão psycopg2), em uma única transação. Devolve (novas, atualizadas)."""
    from psycopg2.extras import execute_values

    with conn, conn.cursor() as cur:
        cur.execute(SCHEMA_CEP_PREFIXOS)
        for comando in MIGRACOES_POSTGRES:
            cur.execute(comando)
        resultado = execute_values(cur, UPSERT_POSTGRES, _tuplas(linhas), fetch=True)
    novas = sum(1 for (inserido,) in resultado if inserido)
    return novas, len(resultado) - novas
