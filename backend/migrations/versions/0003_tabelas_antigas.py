"""tabelas antigas (operadores, geocode_cache, cep_prefixos, ibge_municipios) sob controle do Alembic

Até aqui essas tabelas eram criadas só pelo init_db do app e pelos scripts de carga. Esta revisão as descreve em
SQL idempotente (CREATE ... IF NOT EXISTS): num banco novo cria tudo; no Neon de produção, onde elas já existem
com dados, não faz nada (não apaga, não recria, não altera dados). O SQL é uma cópia congelada do esquema atual:
mudanças futuras entram em revisões novas, nunca editando esta.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Somente criação idempotente: nenhum DROP, TRUNCATE, DELETE nem ALTER que remova coisa.
COMANDOS = [
    """
    CREATE TABLE IF NOT EXISTS operadores (
        id SERIAL PRIMARY KEY,
        nome VARCHAR NOT NULL,
        email VARCHAR NOT NULL,
        senha_hash VARCHAR NOT NULL,
        ativo BOOLEAN,
        criado_em TIMESTAMP
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_operadores_email ON operadores (email)",
    "CREATE INDEX IF NOT EXISTS ix_operadores_id ON operadores (id)",
    """
    CREATE TABLE IF NOT EXISTS geocode_cache (
        chave       TEXT PRIMARY KEY,
        lat         DOUBLE PRECISION,
        lon         DOUBLE PRECISION,
        cidade      TEXT,
        uf          TEXT,
        cep         TEXT,
        bairro      TEXT,
        status      TEXT DEFAULT 'VALIDO',
        criado_em   TIMESTAMP DEFAULT NOW()
    )
    """,
    "ALTER TABLE geocode_cache ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'VALIDO'",
    """
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
    """,
    "ALTER TABLE cep_prefixos ADD COLUMN IF NOT EXISTS localidade TEXT",
    "ALTER TABLE cep_prefixos ADD COLUMN IF NOT EXISTS localidade_pct REAL",
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


def upgrade() -> None:
    for comando in COMANDOS:
        op.execute(comando)


def downgrade() -> None:
    # De propósito não apaga nada: desfazer a criação de tabelas que já têm dados em produção perderia dados.
    pass
