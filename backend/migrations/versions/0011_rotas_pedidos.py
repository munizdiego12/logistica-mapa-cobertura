"""rotas_pedidos (Etapas 9 e 12): os pedidos de cada rota CONFIRMADA

Base do controle de duplicidade ("este pedido já está na Rota N de [motorista] hoje") e do histórico. É gravada ao confirmar as rotas, na mesma
transação que grava `rotas_realizadas`. Pedidos são dado pessoal: guarda só o MÍNIMO (id do pedido, endereço, cidade, UF e volume); nunca nome de
cliente, telefone nem CEP. O `endereco` é apagado (fica NULL e `endereco_apagado_em` recebe a data) depois de cerca de 90 dias da confirmação
(HISTORICO_DIAS); id, cidade, volume e todos os dados da rota ficam. Desfazer a confirmação só marca a rota como cancelada: os pedidos continuam ligados a ela.

Também acrescenta `ix_rotas_realizadas_data` (a limpeza e o histórico filtram por dia). Idempotente (IF NOT EXISTS); nenhum DROP, TRUNCATE ou DELETE;
não altera nenhum dado existente.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-22
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

COMANDOS = [
    """
    CREATE TABLE IF NOT EXISTS rotas_pedidos (
        id SERIAL PRIMARY KEY,
        rota_id INTEGER NOT NULL REFERENCES rotas_realizadas (id),
        ordem INTEGER NOT NULL,
        pedido_id VARCHAR(60) NOT NULL,
        endereco TEXT,
        cidade VARCHAR(120),
        uf VARCHAR(2),
        volume INTEGER NOT NULL DEFAULT 1,
        endereco_apagado_em DATE,
        CONSTRAINT ck_rotas_pedidos_volume CHECK (volume >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_rotas_pedidos_rota ON rotas_pedidos (rota_id)",
    "CREATE INDEX IF NOT EXISTS ix_rotas_pedidos_pedido ON rotas_pedidos (pedido_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_rotas_pedidos_rota_ordem ON rotas_pedidos (rota_id, ordem)",
    "CREATE INDEX IF NOT EXISTS ix_rotas_realizadas_data ON rotas_realizadas (data)",
]


def upgrade() -> None:
    for comando in COMANDOS:
        op.execute(comando)


def downgrade() -> None:
    # De propósito não apaga nada: desfazer perderia o histórico dos pedidos de cada rota.
    pass
