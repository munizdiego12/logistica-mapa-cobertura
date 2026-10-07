"""Testes da carga nacional do CNEFE: agregação em partes, conflito entre UFs, limite de tamanho e download."""
import importlib.util
import sqlite3
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.cnefe import (
    COLUNAS_CNEFE,
    AgregadorPrefixos,
    FAIXAS_PREFIXO_POR_UF,
    LimiteExcedido,
    _haversine_km,
    agregar_prefixos,
    analisar_conflitos,
    gravar_sqlite,
    prefixo_na_uf,
)

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("carregar_cnefe", RAIZ / "scripts" / "carregar_cnefe.py")
carregar_cnefe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(carregar_cnefe)


def _linhas_aleatorias(n, semente=7):
    gen = np.random.default_rng(semente)
    prefixos = [f"{p:05d}" for p in gen.integers(1000, 1020, size=n)]
    localidades = ["CENTRO", "BOSQUE", "VITORIA", "ZETA", "", "ALFA", "  "]
    return pd.DataFrame({
        "COD_MUNICIPIO": [str(x) for x in gen.choice([1200401, 1200302, 1200609], size=n)],
        "CEP": [p + f"{c:03d}" for p, c in zip(prefixos, gen.integers(0, 1000, size=n))],
        "LATITUDE": [f"{x:.6f}" for x in gen.uniform(-11.0, -8.0, size=n)],
        "LONGITUDE": [f"{x:.6f}" for x in gen.uniform(-73.0, -67.0, size=n)],
        "NV_GEO_COORD": [str(x) for x in gen.choice([1, 1, 1, 2, 3, 4, 5, 6], size=n)],
        "DSC_LOCALIDADE": [localidades[i] for i in gen.integers(0, len(localidades), size=n)],
    })[COLUNAS_CNEFE]


def _referencia(df, uf):
    """Algoritmo direto em pandas (tudo em memória), usado só para conferir o agregador em partes."""
    d = df.copy()
    d["prefixo"] = d["CEP"].str[:5]
    d["lat"], d["lon"], d["mun"] = d["LATITUDE"].astype(float), d["LONGITUDE"].astype(float), d["COD_MUNICIPIO"].astype(int)
    saida = {}
    for prefixo, g in d.groupby("prefixo"):
        exatos = g[g["NV_GEO_COORD"].isin(["1", "2"])]
        usados = exatos if len(exatos) else g
        lat, lon = float(np.median(usados["lat"])), float(np.median(usados["lon"]))
        disp = float(np.percentile(_haversine_km(lat, lon, usados["lat"].to_numpy(), usados["lon"].to_numpy()), 90))
        nomes = g["DSC_LOCALIDADE"].str.strip()
        contagem = nomes[nomes != ""].value_counts()
        if contagem.empty:
            localidade, pct = None, 0.0
        else:
            localidade = min(contagem[contagem == contagem.max()].index)
            pct = round(100.0 * contagem.max() / len(g), 1)
        saida[prefixo] = {
            "uf": uf, "cod_municipio": int(g["mun"].mode().iloc[0]), "localidade": localidade, "localidade_pct": pct,
            "lat": round(lat, 6), "lon": round(lon, 6), "n_enderecos": len(g), "n_pontos_exatos": len(exatos),
            "dispersao_km": round(disp, 3),
        }
    return saida


def _em_blocos(df, tamanho):
    return [df.iloc[i:i + tamanho] for i in range(0, len(df), tamanho)]


def test_agregacao_em_partes_e_identica_a_agregacao_em_memoria():
    df = _linhas_aleatorias(4000)
    esperado = _referencia(df, "SP")
    for tamanho in (4000, 1000, 333, 97):  # o tamanho das partes não pode mudar o resultado
        linhas, est = agregar_prefixos(_em_blocos(df, tamanho), "SP")
        obtido = {l["prefixo"]: l for l in linhas}
        assert set(obtido) == set(esperado) and est["linhas_lidas"] == 4000
        for prefixo, ref in esperado.items():
            for campo, valor in ref.items():
                if isinstance(valor, float):
                    assert obtido[prefixo][campo] == pytest.approx(valor, abs=1e-9), (tamanho, prefixo, campo)
                else:
                    assert obtido[prefixo][campo] == valor, (tamanho, prefixo, campo)


def _df_sp_com_cep_trocado():
    """SP com 3 prefixos: 17693 (certo), 71693 (17693 digitado errado, cai na faixa do DF) e 31317 (13317 errado, faixa de MG)."""
    linhas = (
        [("3554706", f"17693{i:03d}", "-22.4", "-48.1", "1", "CENTRO") for i in range(15)]
        + [("3554706", f"71693{i:03d}", "-22.4", "-48.1", "1", "CHACARA TOMAZINI") for i in range(15)]
        + [("3508405", "31317000", "-23.3", "-47.1", "1", "CAI")]
    )
    return pd.DataFrame(linhas, columns=COLUNAS_CNEFE)


def test_prefixos_fora_da_faixa_da_uf_sao_descartados_e_listados():
    linhas, est = agregar_prefixos([_df_sp_com_cep_trocado()], "SP")
    assert [l["prefixo"] for l in linhas] == ["17693"]  # só o que pertence a SP vira linha
    assert est["enderecos_fora_da_uf"] == 16 and est["linhas_lidas"] == 31
    assert {(f["prefixo"], f["n_enderecos"]) for f in est["prefixos_fora_da_uf"]} == {("71693", 15), ("31317", 1)}
    assert est["prefixos_fora_da_uf"][0]["cod_municipio"] in (3554706, 3508405)


def test_sem_validar_faixa_da_uf_mantem_todos():
    linhas, est = agregar_prefixos([_df_sp_com_cep_trocado()], "SP", validar_faixa_uf=False)
    assert [l["prefixo"] for l in linhas] == ["17693", "31317", "71693"] and est["prefixos_fora_da_uf"] == []


def test_faixas_por_uf_sao_27_e_nao_se_sobrepoem():
    assert set(FAIXAS_PREFIXO_POR_UF) == set(carregar_cnefe.CODIGOS_UF)
    todas = sorted((ini, fim, uf) for uf, faixas in FAIXAS_PREFIXO_POR_UF.items() for ini, fim in faixas)
    for (ini, fim, uf), (prox_ini, _, prox_uf) in zip(todas, todas[1:]):
        assert ini <= fim and fim < prox_ini, f"{uf} {ini}-{fim} sobrepõe {prox_uf}"


def test_prefixo_na_uf_nas_fronteiras_e_nas_faixas_intercaladas_de_df_e_go():
    assert prefixo_na_uf(1000, "SP") and prefixo_na_uf(19999, "SP") and not prefixo_na_uf(20000, "SP")
    assert prefixo_na_uf(70089, "DF") and prefixo_na_uf(72799, "DF") and not prefixo_na_uf(72800, "DF")
    assert prefixo_na_uf(72800, "GO") and prefixo_na_uf(72999, "GO") and prefixo_na_uf(73000, "DF") and prefixo_na_uf(73700, "GO")
    assert prefixo_na_uf(69300, "RR") and not prefixo_na_uf(69300, "AM") and prefixo_na_uf(69400, "AM") and prefixo_na_uf(69900, "AC")


def test_agregador_guarda_so_coordenadas_int32_e_nao_segura_a_parte_na_memoria():
    agregador = AgregadorPrefixos("SP")
    for bloco in _em_blocos(_linhas_aleatorias(2000), 250):
        agregador.adicionar(bloco)
    assert agregador._exatos, "esperava pontos exatos guardados"
    for lats, lons in list(agregador._exatos.values()) + list(agregador._aprox.values()):
        for arr in lats + lons:
            assert arr.dtype == np.int32  # 4 bytes por coordenada: 8 bytes por endereço
            assert arr.base is None  # cópia própria: não mantém a parte lida inteira viva
        assert len(lats) <= 64  # os pedaços são juntados, não acumulam milhares de arrays pequenos


def test_finalizar_libera_a_memoria_dos_prefixos():
    agregador = AgregadorPrefixos("SP")
    agregador.adicionar(_linhas_aleatorias(500))
    agregador.finalizar()
    assert not (agregador._n or agregador._exatos or agregador._aprox or agregador._mun or agregador._loc)


def _linha(prefixo, uf, n, lat=-9.97):
    return {
        "prefixo": prefixo, "uf": uf, "cod_municipio": 1200401, "localidade": "CENTRO", "localidade_pct": 100.0,
        "lat": lat, "lon": -67.81, "n_enderecos": n, "n_pontos_exatos": n, "dispersao_km": 1.0, "fonte": "IBGE, CNEFE 2022",
    }


def test_prefixo_de_outra_uf_so_substitui_se_tiver_mais_enderecos():
    conn = sqlite3.connect(":memory:")
    gravar_sqlite(conn, [_linha("70089", "DF", 2)])

    relatorio = {}
    assert gravar_sqlite(conn, [_linha("70089", "SP", 1, lat=-23.5)], relatorio=relatorio) == (0, 0)  # CEP digitado errado
    assert relatorio["mantidas"] == 1 and relatorio["conflitos"][0]["substitui"] is False
    assert conn.execute("SELECT uf, n_enderecos FROM cep_prefixos WHERE prefixo = '70089'").fetchone() == ("DF", 2)

    assert gravar_sqlite(conn, [_linha("70089", "GO", 50)]) == (0, 1)  # outra UF com muito mais endereços vence
    assert conn.execute("SELECT uf, n_enderecos FROM cep_prefixos WHERE prefixo = '70089'").fetchone() == ("GO", 50)

    assert gravar_sqlite(conn, [_linha("70089", "GO", 3)]) == (0, 1)  # recarregar a MESMA UF sempre atualiza
    assert conn.execute("SELECT n_enderecos FROM cep_prefixos WHERE prefixo = '70089'").fetchone() == (3,)


def test_analisar_conflitos_so_considera_ufs_diferentes():
    existentes = {"70089": ("DF", 2), "69900": ("AC", 10)}
    conflitos = analisar_conflitos(existentes, [_linha("70089", "SP", 5), _linha("69900", "AC", 99), _linha("11111", "SP", 1)])
    assert [(c["prefixo"], c["substitui"]) for c in conflitos] == [("70089", True)]


def test_limite_de_tamanho_para_e_desfaz_a_gravacao():
    conn = sqlite3.connect(":memory:")
    gravar_sqlite(conn, [_linha("69900", "AC", 5)])
    with pytest.raises(LimiteExcedido) as erro:
        gravar_sqlite(conn, [_linha(f"{p:05d}", "AC", 5) for p in range(1000, 6000)], limite_bytes=1)
    assert erro.value.limite_bytes == 1 and erro.value.tamanho_bytes > 1
    assert conn.execute("SELECT COUNT(*) FROM cep_prefixos").fetchone()[0] == 1  # nada da UF que estourou ficou gravado
    relatorio = {}
    gravar_sqlite(conn, [_linha("69901", "AC", 5)], limite_bytes=100 * 1_000_000, relatorio=relatorio)
    assert relatorio["tamanho_bytes"] > 0 and conn.execute("SELECT COUNT(*) FROM cep_prefixos").fetchone()[0] == 2


def test_ordem_das_ufs_vai_das_menores_para_as_maiores():
    todas = carregar_cnefe.ordem_ufs()
    assert len(todas) == 27 and todas[:3] == ["RR", "AP", "AC"] and todas[-4:] == ["RJ", "BA", "MG", "SP"]
    tamanhos = [carregar_cnefe.TAMANHO_DOWNLOAD_MB[u] for u in todas]
    assert tamanhos == sorted(tamanhos)
    assert "AC" not in carregar_cnefe.ordem_ufs(pular=["AC", "DF"]) and len(carregar_cnefe.ordem_ufs(pular=["AC", "DF"])) == 25
    assert carregar_cnefe.ordem_ufs(["SP", "DF", "AC"]) == ["AC", "DF", "SP"]


def test_tabelas_de_apoio_cobrem_as_27_ufs():
    ufs = set(carregar_cnefe.CODIGOS_UF)
    assert ufs == set(carregar_cnefe.TAMANHO_DOWNLOAD_MB) == set(carregar_cnefe.PREFIXOS_ESPERADOS)
    assert sum(carregar_cnefe.PREFIXOS_ESPERADOS.values()) == 24649  # prefixos da lista oficial do IBGE


def _zip_falso(pasta, uf="AC"):
    cod = carregar_cnefe.CODIGOS_UF[uf]
    csv = "\n".join(
        ["COD_MUNICIPIO;CEP;LATITUDE;LONGITUDE;NV_GEO_COORD;DSC_LOCALIDADE;EXTRA"]
        + [f"1200401;699001{i:02d};-9.9{i};-67.8{i};1;BOSQUE;x" for i in range(10)]
    )
    caminho = Path(pasta) / f"{cod}_{uf}.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr(f"{cod}_{uf}.csv", csv)
    return caminho


def _destino(tmp_path):
    return lambda: carregar_cnefe.DestinoSqlite(str(tmp_path / "t.db"))


def test_processar_uf_grava_e_apaga_o_download(tmp_path):
    zip_ = _zip_falso(tmp_path)
    r = carregar_cnefe.processar_uf("AC", tmp_path, _destino(tmp_path), 100_000_000, manter_download=False)
    assert r["prefixos"] == 1 and r["novas"] == 1 and r["enderecos"] == 10 and r["apagado"] is True
    assert not zip_.exists()


def test_processar_uf_mantem_o_download_quando_pedido(tmp_path):
    zip_ = _zip_falso(tmp_path)
    carregar_cnefe.processar_uf("AC", tmp_path, _destino(tmp_path), 100_000_000, manter_download=True)
    assert zip_.exists()


def test_processar_uf_estourando_o_limite_nao_grava_e_guarda_o_download(tmp_path):
    zip_ = _zip_falso(tmp_path)
    with pytest.raises(LimiteExcedido):
        carregar_cnefe.processar_uf("AC", tmp_path, _destino(tmp_path), 1, manter_download=False)
    assert zip_.exists()  # não foi gravado: o arquivo fica para tentar de novo sem baixar outra vez
    conn = sqlite3.connect(tmp_path / "t.db")
    assert conn.execute("SELECT COUNT(*) FROM cep_prefixos").fetchone()[0] == 0


def test_processar_uf_ja_acima_do_limite_nem_baixa_a_proxima(tmp_path, monkeypatch):
    _zip_falso(tmp_path)
    carregar_cnefe.processar_uf("AC", tmp_path, _destino(tmp_path), 100_000_000, manter_download=False)  # cria a tabela
    chamadas = []
    monkeypatch.setattr(carregar_cnefe, "baixar_uf", lambda *a, **k: chamadas.append(a))
    with pytest.raises(LimiteExcedido):
        carregar_cnefe.processar_uf("DF", tmp_path, _destino(tmp_path), 1, manter_download=False)
    assert chamadas == []  # parou antes de baixar


def test_processar_uf_recusa_arquivo_com_muitos_ceps_de_outra_uf(tmp_path):
    cod = carregar_cnefe.CODIGOS_UF["AC"]
    csv = "\n".join(
        ["COD_MUNICIPIO;CEP;LATITUDE;LONGITUDE;NV_GEO_COORD;DSC_LOCALIDADE"]
        + [f"1200401;699001{i:02d};-9.9;-67.8;1;A" for i in range(50)]
        + [f"1200401;017001{i:02d};-9.9;-67.8;1;A" for i in range(50)]  # metade com CEP de SP: arquivo errado?
    )
    caminho = tmp_path / f"{cod}_AC.zip"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr(f"{cod}_AC.csv", csv)
    with pytest.raises(RuntimeError, match="fora da faixa da UF"):
        carregar_cnefe.processar_uf("AC", tmp_path, _destino(tmp_path), 100_000_000, manter_download=False)
    assert caminho.exists()
    assert sqlite3.connect(tmp_path / "t.db").execute("SELECT name FROM sqlite_master WHERE name = 'cep_prefixos'").fetchone() is None


def test_script_nao_tem_credencial_nem_comando_destrutivo():
    import re

    texto = (RAIZ / "scripts" / "carregar_cnefe.py").read_text(encoding="utf-8")
    assert not re.search(r"\bDROP\s+(TABLE|INDEX|SCHEMA|DATABASE)\b", texto, re.IGNORECASE)
    assert not re.search(r"\bTRUNCATE\b", texto, re.IGNORECASE)
    assert not re.search(r"postgres(ql)?://[^\s\"']+:[^\s\"'@]+@(?!host)", texto)
