"""motoristas.valor_rota: valor próprio por rota do motorista (opcional)

Cada motorista pode ter um valor próprio por rota (por exemplo, quando muda de loja); NULL = "usa o valor base" do
tipo de veículo. Edição da 0004 não é possível (já foi publicada), por isso esta revisão nova.

Idempotente: `ADD COLUMN IF NOT EXISTS` com o CHECK dentro da própria definição da coluna, então a coluna e a
regra (valor_rota IS NULL OR valor_rota >= 0) entram juntas ou, se a coluna já existe, nada é refeito. Não mexe em
nenhum dado existente. Nenhum DROP, TRUNCATE ou DELETE.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

COMANDOS = [
    """
    ALTER TABLE motoristas
        ADD COLUMN IF NOT EXISTS valor_rota NUMERIC(10, 2)
        CONSTRAINT ck_motoristas_valor_rota CHECK (valor_rota IS NULL OR valor_rota >= 0)
    """,
]


def upgrade() -> None:
    for comando in COMANDOS:
        op.execute(comando)


def downgrade() -> None:
    # De propósito não apaga nada: remover a coluna perderia os valores próprios já cadastrados.
    pass
