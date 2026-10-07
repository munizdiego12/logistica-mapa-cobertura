import re
import sqlite3
from pathlib import Path

import pandas as pd

from backend import cnefe
from backend.cnefe import COLUNAS_CNEFE, agregar_prefixos, gravar_sqlite

RAIZ = Path(__file__).resolve().parents[2]


def _df(linhas):
    """linhas: (municipio, cep, lat, lon, nivel[, localidade]) em texto, como vêm do CSV do IBGE."""
    completas = [tuple(l) + ("CENTRO",) * (len(COLUNAS_CNEFE) - len(l)) for l in linhas]
    return pd.DataFrame(completas, columns=COLUNAS_CNEFE, dtype=str)


def _por_prefixo(linhas_saida):
    return {l["prefixo"]: l for l in linhas_saida}


def test_mediana_ignora_estimativas_quando_ha_pontos_exatos():
    df = _df([
        ("1200401", "69900100", "-9.96", "-67.80", "1"),
        ("1200401", "69900200", "-9.97", "-67.81", "1"),
        ("1200401", "69900300", "-9.98", "-67.82", "2"),
        ("1200401", "69900400", "-11.00", "-70.00", "6"),  # centro de setor, longe: não deve puxar a mediana
    ])
    saida, est = agregar_prefixos([df], "AC")
    linha = _por_prefixo(saida)["69900"]
    assert (linha["lat"], linha["lon"]) == (-9.97, -67.81)
    assert linha["n_enderecos"] == 4
    assert linha["n_pontos_exatos"] == 3
    assert linha["uf"] == "AC" and linha["fonte"] == "IBGE, CNEFE 2022"
    assert est["prefixos_sem_ponto_exato"] == 0


def test_prefixo_so_com_estimativas_usa_todos_os_pontos_e_sinaliza():
    df = _df([
        ("1200401", "69910100", "-9.90", "-67.80", "3"),
        ("1200401", "69910200", "-9.92", "-67.82", "4"),
        ("1200401", "69910300", "-9.94", "-67.84", "5"),
    ])
    saida, est = agregar_prefixos([df], "AC")
    linha = _por_prefixo(saida)["69910"]
    assert linha["n_pontos_exatos"] == 0
    assert (linha["lat"], linha["lon"]) == (-9.92, -67.82)
    assert est["prefixos_sem_ponto_exato"] == 1


def test_dispersao_zero_para_pontos_iguais_e_positiva_para_espalhados():
    iguais = _df([("1200401", f"6990{i}000", "-9.97", "-67.81", "1") for i in range(5)])
    assert _por_prefixo(agregar_prefixos([iguais], "AC")[0])["69900"]["dispersao_km"] == 0.0

    # ~0,1 grau de longitude em torno de -9.97 equivale a ~11 km: dispersão de ordem de grandeza conhecida
    espalhados = _df([
        ("1200401", "69900001", "-9.97", "-67.71", "1"),
        ("1200401", "69900002", "-9.97", "-67.81", "1"),
        ("1200401", "69900003", "-9.97", "-67.91", "1"),
    ])
    disp = _por_prefixo(agregar_prefixos([espalhados], "AC")[0])["69900"]["dispersao_km"]
    assert 8.0 < disp < 12.0


def test_descarta_cep_malformado_e_coordenada_invalida():
    df = _df([
        ("1200401", "69900100", "-9.97", "-67.81", "1"),   # válido
        ("1200401", "6990010", "-9.97", "-67.81", "1"),    # CEP com 7 dígitos
        ("1200401", "699001AB", "-9.97", "-67.81", "1"),   # CEP não numérico
        ("1200401", "69900100", "48.85", "2.35", "1"),     # fora do Brasil
        ("1200401", "69900100", "abc", "-67.81", "1"),     # lat não numérica
        ("abc", "69900100", "-9.97", "-67.81", "1"),       # município inválido
    ])
    saida, est = agregar_prefixos([df], "AC")
    assert est["linhas_lidas"] == 6 and est["linhas_descartadas"] == 5
    assert _por_prefixo(saida)["69900"]["n_enderecos"] == 1


def test_municipio_e_o_mais_frequente_no_prefixo():
    df = _df([
        ("1200401", "69900100", "-9.97", "-67.81", "1"),
        ("1200302", "69900101", "-9.97", "-67.81", "1"),
        ("1200302", "69900102", "-9.97", "-67.81", "1"),
    ])
    assert _por_prefixo(agregar_prefixos([df], "AC")[0])["69900"]["cod_municipio"] == 1200302


def test_blocos_dao_o_mesmo_resultado_que_um_bloco_so_e_zeros_a_esquerda_sao_mantidos():
    linhas = [
        ("3550308", "01001000", "-23.55", "-46.63", "1"),
        ("3550308", "01001010", "-23.56", "-46.64", "1"),
        ("3550308", "01002000", "-23.57", "-46.65", "1"),
        ("3550308", "01002010", "-23.58", "-46.66", "2"),
    ]
    inteiro, _ = agregar_prefixos([_df(linhas)], "SP")
    em_blocos, _ = agregar_prefixos([_df(linhas[:1]), _df(linhas[1:3]), _df(linhas[3:])], "SP")
    assert inteiro == em_blocos
    assert [l["prefixo"] for l in inteiro] == ["01001", "01002"]


def test_sem_linhas_validas_nao_devolve_prefixos():
    saida, est = agregar_prefixos([_df([("1200401", "x", "-9.97", "-67.81", "1")])], "AC")
    assert saida == [] and est["prefixos"] == 0
    assert agregar_prefixos([], "AC")[0] == []


def test_localidade_e_a_mais_frequente_com_percentual():
    df = _df([
        ("1200401", "69900100", "-9.97", "-67.81", "1", "BOSQUE"),
        ("1200401", "69900101", "-9.97", "-67.81", "1", "BOSQUE"),
        ("1200401", "69900102", "-9.97", "-67.81", "1", "BOSQUE"),
        ("1200401", "69900103", "-9.97", "-67.81", "1", "VITORIA"),
    ])
    linha = _por_prefixo(agregar_prefixos([df], "AC")[0])["69900"]
    assert linha["localidade"] == "BOSQUE"
    assert linha["localidade_pct"] == 75.0


def test_empate_de_localidade_resolve_pelo_nome_e_vazio_nao_conta():
    empate = _df([
        ("1200401", "69900100", "-9.97", "-67.81", "1", "ZETA"),
        ("1200401", "69900101", "-9.97", "-67.81", "1", "ALFA"),
    ])
    assert _por_prefixo(agregar_prefixos([empate], "AC")[0])["69900"]["localidade"] == "ALFA"

    sem_nome = _df([("1200401", "69900100", "-9.97", "-67.81", "1", ""), ("1200401", "69900101", "-9.97", "-67.81", "1", "  ")])
    linha = _por_prefixo(agregar_prefixos([sem_nome], "AC")[0])["69900"]
    assert linha["localidade"] is None and linha["localidade_pct"] == 0.0


def test_gravar_sqlite_migra_banco_criado_sem_localidade():
    """O AC já gravado no Neon foi criado sem localidade: a carga seguinte precisa acrescentar as colunas."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE cep_prefixos (prefixo VARCHAR(5) PRIMARY KEY, uf VARCHAR(2) NOT NULL, cod_municipio INTEGER NOT NULL, "
        "lat DOUBLE PRECISION NOT NULL, lon DOUBLE PRECISION NOT NULL, n_enderecos INTEGER NOT NULL, "
        "n_pontos_exatos INTEGER NOT NULL, dispersao_km REAL NOT NULL, fonte TEXT NOT NULL DEFAULT 'IBGE, CNEFE 2022')"
    )
    conn.execute("INSERT INTO cep_prefixos VALUES ('69900','AC',1200401,-9.97,-67.81,5,5,1.0,'IBGE, CNEFE 2022')")
    linhas, _ = agregar_prefixos([_df([("1200401", "69900100", "-9.97", "-67.81", "1", "BOSQUE")])], "AC")
    assert gravar_sqlite(conn, linhas) == (0, 1)
    assert conn.execute("SELECT localidade, localidade_pct FROM cep_prefixos WHERE prefixo = '69900'").fetchone() == ("BOSQUE", 100.0)
    assert gravar_sqlite(conn, linhas) == (0, 1)  # e a segunda carga não tenta recriar as colunas


def test_upsert_sqlite_e_idempotente_e_atualiza_sem_apagar():
    linhas, _ = agregar_prefixos([_df([
        ("1200401", "69900100", "-9.97", "-67.81", "1"),
        ("1200401", "69901100", "-9.95", "-67.80", "1"),
    ])], "AC")
    conn = sqlite3.connect(":memory:")
    assert gravar_sqlite(conn, linhas) == (2, 0)
    assert gravar_sqlite(conn, linhas) == (0, 2)  # rodar de novo não duplica

    # um valor novo para o mesmo prefixo atualiza a linha; outros prefixos permanecem
    alterada = [dict(linhas[0], lat=-10.0, n_enderecos=999)]
    assert gravar_sqlite(conn, alterada) == (0, 1)
    assert conn.execute("SELECT COUNT(*) FROM cep_prefixos").fetchone()[0] == 2
    assert conn.execute("SELECT lat, n_enderecos FROM cep_prefixos WHERE prefixo = '69900'").fetchone() == (-10.0, 999)


def test_carga_cnefe_nunca_apaga_tabela_e_nao_tem_credencial():
    script = (RAIZ / "scripts" / "carregar_cnefe.py").read_text(encoding="utf-8")
    sql = " ".join([cnefe.SCHEMA_CEP_PREFIXOS, *cnefe.MIGRACOES_POSTGRES, cnefe.UPSERT_POSTGRES, cnefe.UPSERT_SQLITE])
    for texto in (sql, script, Path(cnefe.__file__).read_text(encoding="utf-8")):
        assert not re.search(r"DROP\s+(TABLE|INDEX|SCHEMA|DATABASE)", texto, re.IGNORECASE)
        assert not re.search(r"TRUNCATE", texto, re.IGNORECASE)
    assert "postgresql://usuario:senha@host" in script  # só o exemplo da documentação
    assert "ON CONFLICT (prefixo) DO UPDATE" in cnefe.UPSERT_POSTGRES
