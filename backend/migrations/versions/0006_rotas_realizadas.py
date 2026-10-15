"""rotas_realizadas: registro das rotas confirmadas (uma linha por rota/viagem confirmada)

Cada confirmação de resultado grava uma linha por rota, com o motorista de cada rota. `execucao_id` agrupa as rotas
de uma mesma roteirização e `numero_rota` identifica a rota dentro dela: a combinação é única, então confirmar o
mesmo resultado duas vezes não duplica. Desfazer a confirmação marca as linhas como 'cancelada' (não apaga), e só
as 'confirmada' contam (rotas feitas por motorista no dia). `data` é o dia no horário de America/Sao_Paulo.

Idempotente (IF NOT EXISTS), sem DROP/TRUNCATE/DELETE e sem mexer em nenhuma tabela existente.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

COMANDOS = [
    """
    CREATE TABLE IF NOT EXISTS rotas_realizadas (
        id SERIAL PRIMARY KEY,
        execucao_id VARCHAR(64) NOT NULL,
        numero_rota INTEGER NOT NULL,
        motorista_id INTEGER NOT NULL REFERENCES motoristas (id),
        data DATE NOT NULL,
        loja_hub TEXT,
        turno VARCHAR(20),
        qtd_pedidos INTEGER NOT NULL DEFAULT 0,
        distancia_km NUMERIC(10, 2) NOT NULL DEFAULT 0,
        status VARCHAR(12) NOT NULL DEFAULT 'confirmada',
        criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        criado_por VARCHAR(200),
        CONSTRAINT ck_rotas_realizadas_status CHECK (status IN ('confirmada', 'cancelada')),
        CONSTRAINT ck_rotas_realizadas_qtd CHECK (qtd_pedidos >= 0),
        CONSTRAINT ck_rotas_realizadas_km CHECK (distancia_km >= 0)
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_rotas_realizadas_execucao_rota ON rotas_realizadas (execucao_id, numero_rota)",
    "CREATE INDEX IF NOT EXISTS ix_rotas_realizadas_dia_motorista ON rotas_realizadas (data, motorista_id) WHERE status = 'confirmada'",
]


def upgrade() -> None:
    for comando in COMANDOS:
        op.execute(comando)


def downgrade() -> None:
    # De propósito não apaga nada: o registro de rotas confirmadas é histórico.
    pass
