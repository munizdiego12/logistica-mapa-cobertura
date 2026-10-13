"""tipos_veiculo e motoristas (Etapa 5): custo fixo por rota, peso de referência opcional e cadastro de motoristas

SQL idempotente (IF NOT EXISTS / ON CONFLICT DO NOTHING): rodar de novo não recria nada nem desfaz o que um
operador editou. Os dois tipos de veículo já nascem cadastrados. Nenhum DROP, TRUNCATE ou DELETE.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-13
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

COMANDOS = [
    """
    CREATE TABLE IF NOT EXISTS tipos_veiculo (
        id SERIAL PRIMARY KEY,
        nome VARCHAR(60) NOT NULL UNIQUE,
        custo_rota NUMERIC(10, 2) NOT NULL,
        peso_referencia_kg NUMERIC(10, 3),
        ativo BOOLEAN NOT NULL DEFAULT TRUE,
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        atualizado_por VARCHAR(200),
        CONSTRAINT ck_tipos_veiculo_custo CHECK (custo_rota >= 0),
        CONSTRAINT ck_tipos_veiculo_peso_ref CHECK (peso_referencia_kg IS NULL OR (peso_referencia_kg > 0 AND peso_referencia_kg <= 100000))
    )
    """,
    """
    INSERT INTO tipos_veiculo (nome, custo_rota, atualizado_por) VALUES
        ('Carro de passeio', 130.00, 'cadastro inicial (migration)'),
        ('Fiorino/Utilitário', 260.00, 'cadastro inicial (migration)')
    ON CONFLICT (nome) DO NOTHING
    """,
    """
    CREATE TABLE IF NOT EXISTS motoristas (
        id SERIAL PRIMARY KEY,
        nome VARCHAR(120) NOT NULL,
        tipo_veiculo VARCHAR(60) NOT NULL REFERENCES tipos_veiculo (nome),
        ativo BOOLEAN NOT NULL DEFAULT TRUE,
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        atualizado_por VARCHAR(200),
        CONSTRAINT ck_motoristas_nome CHECK (length(btrim(nome)) > 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_motoristas_ativo_nome ON motoristas (ativo, nome)",
]


def upgrade() -> None:
    # peso_referencia_kg (NULL = "sem referência") não é limite: é só um guia para o motor de roteirização.
    # Motorista não é apagado: é desativado (ativo = false), para não quebrar históricos futuros.
    for comando in COMANDOS:
        op.execute(comando)


def downgrade() -> None:
    # De propósito não apaga nada: desfazer a criação perderia o cadastro de motoristas em produção.
    pass
