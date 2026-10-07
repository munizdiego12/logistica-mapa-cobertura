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

# Caixa que contém o território brasileiro (inclui as ilhas oceânicas): descarta coordenadas fora do país.
LAT_MIN, LAT_MAX = -34.0, 6.0
LON_MIN, LON_MAX = -74.0, -28.0

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

# Um CEP digitado errado no CNEFE pode criar, no arquivo de uma UF, um prefixo que é de outra. Recarregar a
# mesma UF sempre atualiza; uma UF diferente só substitui o prefixo já gravado se tiver MAIS endereços.
_SO_SE_MESMA_UF_OU_MAIOR = "WHERE cep_prefixos.uf = EXCLUDED.uf OR EXCLUDED.n_enderecos > cep_prefixos.n_enderecos"

UPSERT_POSTGRES = (
    f"INSERT INTO cep_prefixos ({_COLUNAS_SQL}) VALUES %s "
    f"ON CONFLICT (prefixo) DO UPDATE SET {_ATUALIZAR} {_SO_SE_MESMA_UF_OU_MAIOR} RETURNING (xmax = 0) AS inserido"
)
UPSERT_SQLITE = (
    f"INSERT INTO cep_prefixos ({_COLUNAS_SQL}) VALUES ({', '.join('?' * len(COLUNAS_SAIDA))}) "
    f"ON CONFLICT (prefixo) DO UPDATE SET {_ATUALIZAR} {_SO_SE_MESMA_UF_OU_MAIOR}"
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


# Faixas de CEP dos Correios por UF, em prefixos de 5 dígitos (início, fim inclusive). Conferidas contra a lista
# oficial do IBGE: cobrem os 24.649 prefixos sem sobra. Servem para descartar CEPs digitados errado no CNEFE
# (ex.: 17693 digitado como 71693, que cairia na faixa do DF) e não gravá-los como se fossem faixas reais.
FAIXAS_PREFIXO_POR_UF = {
    "SP": [(1000, 19999)], "RJ": [(20000, 28999)], "ES": [(29000, 29999)], "MG": [(30000, 39999)],
    "BA": [(40000, 48999)], "SE": [(49000, 49999)], "PE": [(50000, 56999)], "AL": [(57000, 57999)],
    "PB": [(58000, 58999)], "RN": [(59000, 59999)], "CE": [(60000, 63999)], "PI": [(64000, 64999)],
    "MA": [(65000, 65999)], "PA": [(66000, 68899)], "AP": [(68900, 68999)], "AM": [(69000, 69299), (69400, 69899)],
    "RR": [(69300, 69399)], "AC": [(69900, 69999)], "DF": [(70000, 72799), (73000, 73699)],
    "GO": [(72800, 72999), (73700, 76799)], "RO": [(76800, 76999)], "TO": [(77000, 77999)],
    "MT": [(78000, 78899)], "MS": [(79000, 79999)], "PR": [(80000, 87999)], "SC": [(88000, 89999)],
    "RS": [(90000, 99999)],
}
# Prefixo fora da faixa da UF com tantos endereços ou mais é avisado (pode ser real, não só erro de digitação).
LIMITE_AVISO_ENDERECOS_FORA_DA_UF = 50


def prefixo_na_uf(prefixo: int, uf: str) -> bool:
    return any(ini <= prefixo <= fim for ini, fim in FAIXAS_PREFIXO_POR_UF[uf])


_MICROGRAU = 1_000_000  # coordenadas guardadas como inteiros em microgrados (~0,11 m): 8 bytes por endereço
_MAX_PEDACOS_POR_PREFIXO = 64


def _moda(contagem: dict):
    """Chave mais frequente; empate resolvido pela menor chave."""
    maior = max(contagem.values())
    return min(k for k, v in contagem.items() if v == maior)


class AgregadorPrefixos:
    """
    Agrega os endereços por prefixo de CEP de 5 dígitos lendo o CSV por partes (adicionar uma parte de cada vez).

    Memória: não mantém a UF inteira. Para cada endereço guarda só as duas coordenadas como int32 (8 bytes);
    o resto vira contadores por prefixo. SP (~20 milhões de endereços) fica na casa de 200 MB, contra mais de
    1 GB se juntasse tudo num DataFrame. A mediana continua exata (os pontos têm 6 casas decimais).
    """

    def __init__(self, uf: str, validar_faixa_uf: bool = True):
        self.uf = uf
        self.validar_faixa_uf = validar_faixa_uf
        self._vocabulario = _Vocabulario()
        self._n, self._mun, self._loc = {}, {}, {}
        self._exatos, self._aprox = {}, {}
        self.estatisticas = {
            "linhas_lidas": 0, "linhas_descartadas": 0, "prefixos": 0, "prefixos_sem_ponto_exato": 0,
            "prefixos_fora_da_uf": [], "enderecos_fora_da_uf": 0,
        }

    @staticmethod
    def _somar(contagem: dict, valores: np.ndarray, ignorar=None) -> None:
        chaves, quantidades = np.unique(valores, return_counts=True)
        for k, q in zip(chaves.tolist(), quantidades.tolist()):
            if k != ignorar:
                contagem[k] = contagem.get(k, 0) + q

    @staticmethod
    def _guardar(destino: dict, prefixo: int, lat: np.ndarray, lon: np.ndarray) -> None:
        if len(lat) == 0:
            return
        lats, lons = destino.setdefault(prefixo, ([], []))
        lats.append(lat)
        lons.append(lon)
        if len(lats) >= _MAX_PEDACOS_POR_PREFIXO:  # junta os pedaços para não acumular milhares de arrays pequenos
            lats[:] = [np.concatenate(lats)]
            lons[:] = [np.concatenate(lons)]

    def adicionar(self, chunk: pd.DataFrame) -> None:
        self.estatisticas["linhas_lidas"] += len(chunk)
        limpo, descartes = limpar_chunk(chunk, self._vocabulario)
        self.estatisticas["linhas_descartadas"] += descartes
        if limpo.empty:
            return

        ordem = np.argsort(limpo["prefixo"].to_numpy(), kind="stable")
        prefixo = limpo["prefixo"].to_numpy()[ordem]
        lat = np.rint(limpo["lat"].to_numpy()[ordem] * _MICROGRAU).astype(np.int32)
        lon = np.rint(limpo["lon"].to_numpy()[ordem] * _MICROGRAU).astype(np.int32)
        mun, loc, exato = limpo["mun"].to_numpy()[ordem], limpo["loc"].to_numpy()[ordem], limpo["exato"].to_numpy()[ordem]
        vazio = self._vocabulario.id_vazio()

        valores, inicios = np.unique(prefixo, return_index=True)
        fins = np.append(inicios[1:], len(prefixo))
        for p, i, j in zip(valores.tolist(), inicios.tolist(), fins.tolist()):
            self._n[p] = self._n.get(p, 0) + (j - i)
            self._somar(self._mun.setdefault(p, {}), mun[i:j])
            self._somar(self._loc.setdefault(p, {}), loc[i:j], ignorar=vazio)
            e = exato[i:j]
            # a máscara booleana copia os dados: nada aqui mantém a parte inteira viva na memória
            self._guardar(self._exatos, p, lat[i:j][e], lon[i:j][e])
            if not e.all():
                self._guardar(self._aprox, p, lat[i:j][~e], lon[i:j][~e])

    @staticmethod
    def _juntar(pedacos) -> tuple:
        lats, lons = pedacos
        return np.concatenate(lats), np.concatenate(lons)

    def finalizar(self) -> tuple:
        """Devolve (lista de dicts com as COLUNAS_SAIDA, estatísticas). Libera a memória de cada prefixo ao terminá-lo."""
        saida = []
        for prefixo in sorted(self._n):
            exatos = self._exatos.pop(prefixo, None)
            aproximados = self._aprox.pop(prefixo, None)
            if self.validar_faixa_uf and not prefixo_na_uf(prefixo, self.uf):
                n = self._n.pop(prefixo)
                self._loc.pop(prefixo, None)
                self.estatisticas["enderecos_fora_da_uf"] += n
                self.estatisticas["prefixos_fora_da_uf"].append(
                    {"prefixo": f"{prefixo:05d}", "n_enderecos": n, "cod_municipio": int(_moda(self._mun.pop(prefixo)))}
                )
                continue
            if exatos:
                lat_i, lon_i = self._juntar(exatos)
                n_exatos = len(lat_i)
            else:  # sem nenhum ponto de nível 1/2: usa todos e sinaliza com n_pontos_exatos = 0
                lat_i, lon_i = self._juntar(aproximados)
                n_exatos = 0
            lats, lons = lat_i.astype(np.float64) / _MICROGRAU, lon_i.astype(np.float64) / _MICROGRAU
            lat, lon = float(np.median(lats)), float(np.median(lons))
            dispersao = float(np.percentile(_haversine_km(lat, lon, lats, lons), 90))

            n = self._n.pop(prefixo)
            contagem_loc = self._loc.pop(prefixo)
            if contagem_loc:
                maior = max(contagem_loc.values())
                localidade = min(self._vocabulario.nomes[k] for k, v in contagem_loc.items() if v == maior)
                localidade_pct = round(100.0 * maior / n, 1)
            else:
                localidade, localidade_pct = None, 0.0

            saida.append({
                "prefixo": f"{int(prefixo):05d}",
                "uf": self.uf,
                "cod_municipio": int(_moda(self._mun.pop(prefixo))),  # município com mais endereços no prefixo
                "localidade": localidade,
                "localidade_pct": localidade_pct,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "n_enderecos": int(n),
                "n_pontos_exatos": int(n_exatos),
                "dispersao_km": round(dispersao, 3),
                "fonte": FONTE,
            })

        self.estatisticas["prefixos"] = len(saida)
        self.estatisticas["prefixos_sem_ponto_exato"] = sum(1 for r in saida if r["n_pontos_exatos"] == 0)
        return saida, self.estatisticas


def agregar_prefixos(chunks, uf: str, validar_faixa_uf: bool = True) -> tuple:
    """
    Agrega os endereços por prefixo de CEP de 5 dígitos.

    chunks: iterável de DataFrames com as colunas de COLUNAS_CNEFE (strings, como vêm do CSV); consumido uma
    parte por vez. Devolve (lista de dicts com as COLUNAS_SAIDA, estatísticas do processamento). Com
    `validar_faixa_uf`, prefixos fora da faixa de CEP da UF são descartados e listados nas estatísticas.
    """
    agregador = AgregadorPrefixos(uf, validar_faixa_uf)
    for chunk in chunks:
        agregador.adicionar(chunk)
    return agregador.finalizar()


def _tuplas(linhas: list) -> list:
    return [tuple(l[c] for c in COLUNAS_SAIDA) for l in linhas]


class LimiteExcedido(Exception):
    """A tabela passaria do limite de tamanho; nada daquela UF foi gravado."""

    def __init__(self, tamanho_bytes: int, limite_bytes: int):
        super().__init__(f"tabela com {tamanho_bytes / 1e6:.1f} MB passaria do limite de {limite_bytes / 1e6:.0f} MB")
        self.tamanho_bytes, self.limite_bytes = tamanho_bytes, limite_bytes


SQL_TAMANHO_POSTGRES = "SELECT COALESCE(pg_total_relation_size(to_regclass('cep_prefixos')), 0)"


def tamanho_tabela_sqlite(conn) -> int:
    """Tamanho do arquivo SQLite (só a tabela de prefixos mora nele nos testes): páginas x tamanho da página."""
    return conn.execute("PRAGMA page_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]


def tamanho_tabela_postgres(conn) -> int:
    """pg_total_relation_size de cep_prefixos (dados + índices + TOAST); 0 se a tabela ainda não existe."""
    with conn.cursor() as cur:
        cur.execute(SQL_TAMANHO_POSTGRES)
        tamanho = cur.fetchone()[0]
    conn.rollback()  # só leitura: encerra a transação aberta pelo SELECT
    return int(tamanho)


def analisar_conflitos(existentes: dict, linhas: list) -> list:
    """Prefixos que já estão gravados com OUTRA UF. `substitui` diz se a linha nova (mais endereços) vence."""
    conflitos = []
    for l in linhas:
        atual = existentes.get(l["prefixo"])
        if atual and atual[0] != l["uf"]:
            conflitos.append({
                "prefixo": l["prefixo"], "uf_existente": atual[0], "n_existente": atual[1],
                "uf_nova": l["uf"], "n_novo": l["n_enderecos"], "substitui": l["n_enderecos"] > atual[1],
            })
    return conflitos


def gravar_sqlite(conn, linhas: list, limite_bytes: int = None, relatorio: dict = None) -> tuple:
    """
    Upsert em SQLite. Devolve (novas, atualizadas). `relatorio` (opcional) recebe conflitos, mantidas e tamanho.
    Com `limite_bytes`, se a tabela passar do limite a gravação é desfeita e LimiteExcedido é levantada.
    """
    conn.execute(SCHEMA_CEP_PREFIXOS)
    # SQLite não tem ADD COLUMN IF NOT EXISTS: acrescenta só o que falta (banco criado numa versão anterior).
    atuais = {r[1] for r in conn.execute("PRAGMA table_info(cep_prefixos)")}
    for coluna, tipo in COLUNAS_ACRESCENTADAS.items():
        if coluna not in atuais:
            conn.execute(f"ALTER TABLE cep_prefixos ADD COLUMN {coluna} {tipo}")
    existentes = {p: (uf, n) for p, uf, n in conn.execute("SELECT prefixo, uf, n_enderecos FROM cep_prefixos")}
    conflitos = analisar_conflitos(existentes, linhas)
    conn.executemany(UPSERT_SQLITE, _tuplas(linhas))
    tamanho = tamanho_tabela_sqlite(conn)
    if limite_bytes is not None and tamanho > limite_bytes:
        conn.rollback()
        raise LimiteExcedido(tamanho, limite_bytes)
    conn.commit()
    mantidas = sum(1 for c in conflitos if not c["substitui"])
    novas = sum(1 for l in linhas if l["prefixo"] not in existentes)
    if relatorio is not None:
        relatorio.update(conflitos=conflitos, mantidas=mantidas, tamanho_bytes=tamanho)
    return novas, len(linhas) - novas - mantidas


def gravar_postgres(conn, linhas: list, limite_bytes: int = None, relatorio: dict = None) -> tuple:
    """
    Upsert em Postgres (conexão psycopg2), em uma única transação. Devolve (novas, atualizadas).
    Com `limite_bytes`, se a tabela passar do limite a transação é desfeita e LimiteExcedido é levantada.
    """
    from psycopg2.extras import execute_values

    with conn, conn.cursor() as cur:
        cur.execute(SCHEMA_CEP_PREFIXOS)
        for comando in MIGRACOES_POSTGRES:
            cur.execute(comando)
        cur.execute(
            "SELECT prefixo, uf, n_enderecos FROM cep_prefixos WHERE prefixo = ANY(%s)", ([l["prefixo"] for l in linhas],)
        )
        existentes = {p: (uf, n) for p, uf, n in cur.fetchall()}
        conflitos = analisar_conflitos(existentes, linhas)
        resultado = execute_values(cur, UPSERT_POSTGRES, _tuplas(linhas), fetch=True)
        cur.execute(SQL_TAMANHO_POSTGRES)
        tamanho = int(cur.fetchone()[0])
        if limite_bytes is not None and tamanho > limite_bytes:
            raise LimiteExcedido(tamanho, limite_bytes)  # sai do `with conn`: desfaz a transação
    novas = sum(1 for (inserido,) in resultado if inserido)
    if relatorio is not None:
        relatorio.update(conflitos=conflitos, mantidas=len(linhas) - len(resultado), tamanho_bytes=tamanho)
    return novas, len(resultado) - novas
