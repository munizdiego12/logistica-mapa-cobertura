import re
import sqlite3
from pathlib import Path

from backend import ibge
from backend.ibge import (
    CODIGO_UF,
    gravar_sqlite,
    indice_por_uf_e_nome,
    ler_municipios_csv,
    normalizar_nome,
    validar_municipios,
)

RAIZ = Path(__file__).resolve().parents[2]


def _m(codigo="3550308", nome="São Paulo", uf="SP"):
    return {"codigo": codigo, "nome": nome, "uf": uf}


def test_normalizar_nome_tira_acento_caixa_e_espacos():
    assert normalizar_nome("São  Luís") == "SAO LUIS"
    assert normalizar_nome("  Brasília ") == "BRASILIA"
    assert normalizar_nome("Alta Floresta D'Oeste") == "ALTA FLORESTA D'OESTE"
    assert normalizar_nome(None) == ""


def test_csv_de_municipios_e_valido_e_tem_todas_as_ufs():
    municipios = ler_municipios_csv()
    assert validar_municipios(municipios) == []
    assert {m["uf"] for m in municipios} == set(CODIGO_UF)
    assert len(municipios) == 5571


def test_codigos_conhecidos():
    indice = indice_por_uf_e_nome(ler_municipios_csv())
    assert indice[("SP", "SAO PAULO")] == 3550308
    assert indice[("DF", "BRASILIA")] == 5300108
    assert indice[("SC", "FLORIANOPOLIS")] == 4205407
    assert indice[("RJ", "RIO DE JANEIRO")] == 3304557


def test_validador_detecta_codigo_invalido_uf_incoerente_e_repetido():
    assert any("7 dígitos" in e for e in validar_municipios([_m(codigo="355030")]))
    assert any("não pertence" in e for e in validar_municipios([_m(uf="RJ")]))
    assert any("UF inválida" in e for e in validar_municipios([_m(uf="XX")]))
    assert any("nome vazio" in e for e in validar_municipios([_m(nome=" ")]))
    assert any("repetido" in e for e in validar_municipios([_m(), _m()]))
    assert any("quantidade inesperada" in e for e in validar_municipios([_m()]))


def test_upsert_sqlite_idempotente_e_atualiza_nome():
    conn = sqlite3.connect(":memory:")
    municipios = [_m(), _m("3304557", "Rio de Janeiro", "RJ")]
    assert gravar_sqlite(conn, municipios) == (2, 0)
    assert gravar_sqlite(conn, municipios) == (0, 2)
    assert gravar_sqlite(conn, [_m(nome="São Paulo (corrigido)")]) == (0, 1)
    assert conn.execute("SELECT COUNT(*) FROM ibge_municipios").fetchone()[0] == 2
    assert conn.execute("SELECT nome, nome_normalizado FROM ibge_municipios WHERE codigo = 3550308").fetchone() == (
        "São Paulo (corrigido)", "SAO PAULO (CORRIGIDO)")


def test_busca_por_uf_e_nome_normalizado_no_banco():
    conn = sqlite3.connect(":memory:")
    gravar_sqlite(conn, ler_municipios_csv())
    achou = conn.execute(
        "SELECT codigo FROM ibge_municipios WHERE uf = ? AND nome_normalizado = ?", ("DF", normalizar_nome("Brasília"))
    ).fetchone()
    assert achou == (5300108,)
    assert conn.execute(
        "SELECT codigo FROM ibge_municipios WHERE uf = ? AND nome_normalizado = ?", ("SP", normalizar_nome("Cidade Inexistente"))
    ).fetchone() is None


def test_nenhum_codigo_ibge_fixo_no_codigo_do_app():
    for arquivo in ("main.py", "database.py"):
        texto = (RAIZ / "backend" / arquivo).read_text(encoding="utf-8")
        assert not re.search(r"\b(3550308|2304400)\b", texto), f"código IBGE fixo em {arquivo}"
        assert "ESTADOS_IBGE_BRASIL" not in texto


def test_carga_de_municipios_nunca_apaga_tabela():
    texto = " ".join([*ibge.SCHEMA_IBGE_MUNICIPIOS, ibge.UPSERT_POSTGRES, ibge.UPSERT_SQLITE])
    script = (RAIZ / "scripts" / "carregar_municipios.py").read_text(encoding="utf-8")
    for t in (texto, script, Path(ibge.__file__).read_text(encoding="utf-8")):
        assert not re.search(r"DROP\s+(TABLE|INDEX|SCHEMA|DATABASE)", t, re.IGNORECASE)
        assert not re.search(r"TRUNCATE", t, re.IGNORECASE)
