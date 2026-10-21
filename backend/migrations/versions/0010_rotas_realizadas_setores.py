"""rotas_realizadas.setores (Etapa 8): setores cardeais de cada rota confirmada

Texto com os setores da rota (ex.: "N,NE"), preenchido ao confirmar as rotas. É a base da regra de rotação (o mesmo motorista não deve
repetir a mesma região em turnos diferentes no mesmo dia). NULL nas rotas antigas. O `turno`, que já existia, passa a ser gravado.

Idempotente (IF NOT EXISTS); nenhum DROP, TRUNCATE ou DELETE; não altera nenhum dado existente.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

COMANDOS = [
    "ALTER TABLE rotas_realizadas ADD COLUMN IF NOT EXISTS setores TEXT",
]


def upgrade() -> None:
    for comando in COMANDOS:
        op.execute(comando)


def downgrade() -> None:
    # De propósito não apaga nada: desfazer perderia os setores já gravados.
    pass
