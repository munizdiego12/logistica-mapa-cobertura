"""lojas (Etapa 6a): cadastro de lojas com coordenadas fixas, janelas de entrega e auditoria

A filial já faz parte do nome da loja (ex.: "Atacadão Guarujá"): NÃO existe coluna filial. `uf`, `endereco` e `cidade`
são opcionais (linhas do Google My Maps não trazem Estado nem cidade). A cidade + uf dão o código IBGE do hub. As capacidades de peso e de volume são opcionais e só
informativas: nunca bloqueiam nada. Janelas de entrega: manhã 08-13 e tarde 13-18 (sempre), noite 18-21 (NULL = a
loja não usa a noite). Loja não é apagada: é desativada (`ativo = false`). O nome é único entre as lojas (sem
diferença de maiúsculas ou espaços), inclusive as desativadas.

Idempotente (IF NOT EXISTS); nenhum DROP, TRUNCATE ou DELETE; não mexe em nenhuma tabela existente.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

COMANDOS = [
    """
    CREATE TABLE IF NOT EXISTS lojas (
        id SERIAL PRIMARY KEY,
        nome VARCHAR(120) NOT NULL,
        uf VARCHAR(2),
        endereco VARCHAR(250),
        cidade VARCHAR(120),
        lat DOUBLE PRECISION NOT NULL,
        lng DOUBLE PRECISION NOT NULL,
        ativo BOOLEAN NOT NULL DEFAULT TRUE,
        capacidade_peso NUMERIC(12, 3),
        capacidade_volume NUMERIC(12, 3),
        janela_manha_inicio TIME NOT NULL DEFAULT '08:00',
        janela_manha_fim TIME NOT NULL DEFAULT '13:00',
        janela_tarde_inicio TIME NOT NULL DEFAULT '13:00',
        janela_tarde_fim TIME NOT NULL DEFAULT '18:00',
        janela_noite_inicio TIME DEFAULT '18:00',
        janela_noite_fim TIME DEFAULT '21:00',
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        atualizado_por VARCHAR(200),
        CONSTRAINT ck_lojas_nome CHECK (length(btrim(nome)) > 0),
        CONSTRAINT ck_lojas_lat_brasil CHECK (lat BETWEEN -34 AND 6),
        CONSTRAINT ck_lojas_lng_brasil CHECK (lng BETWEEN -74 AND -34),
        CONSTRAINT ck_lojas_capacidade_peso CHECK (capacidade_peso IS NULL OR capacidade_peso > 0),
        CONSTRAINT ck_lojas_capacidade_volume CHECK (capacidade_volume IS NULL OR capacidade_volume > 0),
        CONSTRAINT ck_lojas_janela_manha CHECK (janela_manha_inicio < janela_manha_fim),
        CONSTRAINT ck_lojas_janela_tarde CHECK (janela_tarde_inicio < janela_tarde_fim),
        CONSTRAINT ck_lojas_janela_noite CHECK (
            (janela_noite_inicio IS NULL AND janela_noite_fim IS NULL)
            OR (janela_noite_inicio IS NOT NULL AND janela_noite_fim IS NOT NULL AND janela_noite_inicio < janela_noite_fim)
        )
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_lojas_nome ON lojas (lower(btrim(nome)))",
    "CREATE INDEX IF NOT EXISTS ix_lojas_ativo_nome ON lojas (ativo, nome)",
]


def upgrade() -> None:
    for comando in COMANDOS:
        op.execute(comando)


def downgrade() -> None:
    # De propósito não apaga nada: desfazer a criação perderia o cadastro de lojas.
    pass
