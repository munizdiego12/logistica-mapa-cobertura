"""Revisão 0003 (tabelas antigas): idempotente, sem apagar nada e igual ao esquema que o app usa."""
import importlib.util
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import cnefe
import ibge
from database import Operador

BACKEND = Path(__file__).resolve().parents[1]
ARQUIVO = BACKEND / "migrations" / "versions" / "0003_tabelas_antigas.py"


def _migracao():
    spec = importlib.util.spec_from_file_location("migracao_0003", ARQUIVO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _colunas(conn, tabela):
    return {l[1]: (l[2].upper(), bool(l[3])) for l in conn.execute(f"PRAGMA table_info({tabela})")}


def _aplicar_no_sqlite(conn, comandos):
    for comando in comandos:
        if "ADD COLUMN IF NOT EXISTS" in comando:  # o SQLite não tem essa sintaxe; ela é conferida em texto
            continue
        conn.execute(comando.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY").replace("DEFAULT NOW()", "DEFAULT CURRENT_TIMESTAMP"))


def test_so_cria_nunca_apaga_e_tudo_e_idempotente():
    comandos = _migracao().COMANDOS
    for c in comandos:
        assert not re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\b", c, re.IGNORECASE), c
        assert re.search(r"IF NOT EXISTS", c), c
    assert _migracao().down_revision == "0002"


def test_roda_duas_vezes_e_preserva_dados():
    conn = sqlite3.connect(":memory:")
    comandos = _migracao().COMANDOS
    _aplicar_no_sqlite(conn, comandos)
    conn.execute("INSERT INTO operadores (nome, email, senha_hash, ativo) VALUES ('Maria', 'm@z.com', 'x', 1)")
    conn.execute("INSERT INTO ibge_municipios VALUES (1200401, 'Rio Branco', 'AC', 'RIO BRANCO')")
    _aplicar_no_sqlite(conn, comandos)  # segunda vez: banco que já existe, com dados
    assert conn.execute("SELECT count(*) FROM operadores").fetchone() == (1,)
    assert conn.execute("SELECT count(*) FROM ibge_municipios").fetchone() == (1,)


def test_colunas_da_migracao_iguais_ao_esquema_do_app():
    """Se o app mudar uma tabela antiga, este teste lembra de criar uma revisão nova (a 0003 é histórico congelado)."""
    da_migracao = sqlite3.connect(":memory:")
    _aplicar_no_sqlite(da_migracao, _migracao().COMANDOS)

    do_app = sqlite3.connect(":memory:")
    do_app.execute(cnefe.SCHEMA_CEP_PREFIXOS)
    for comando in ibge.SCHEMA_IBGE_MUNICIPIOS:
        do_app.execute(comando)
    for tabela in ("cep_prefixos", "ibge_municipios"):
        assert _colunas(da_migracao, tabela) == _colunas(do_app, tabela), tabela

    # operadores: o ORM é a fonte; compara nomes e obrigatoriedade das colunas
    esperadas = {c.name: (not c.nullable) for c in Operador.__table__.columns}
    reais = {nome: obrigatoria for nome, (_tipo, obrigatoria) in _colunas(da_migracao, "operadores").items()}
    assert {n: o for n, o in reais.items() if n != "id"} == {n: o for n, o in esperadas.items() if n != "id"}

    # geocode_cache: as colunas que o app grava e lê (database.cache_get / cache_set)
    assert set(_colunas(da_migracao, "geocode_cache")) == {"chave", "lat", "lon", "cidade", "uf", "cep", "bairro", "status", "criado_em"}


def test_alembic_gera_o_sql_completo_sem_conectar_e_sem_apagar():
    import os
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-m", "alembic", "-c", str(BACKEND / "alembic.ini"), "upgrade", "head", "--sql"],
                       cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace", env={**env, "DATABASE_URL": "postgresql://u:p@h/db"}, timeout=120)
    assert r.returncode == 0, r.stderr
    sql = r.stdout
    for tabela in ("operadores", "geocode_cache", "cep_prefixos", "ibge_municipios"):
        assert f"CREATE TABLE IF NOT EXISTS {tabela}" in sql
    assert "CREATE TABLE item_pesos" in sql
    assert "CREATE TABLE IF NOT EXISTS tipos_veiculo" in sql and "CREATE TABLE IF NOT EXISTS motoristas" in sql
    assert "ON CONFLICT (nome) DO NOTHING" in sql
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE)\b", sql, re.IGNORECASE)
