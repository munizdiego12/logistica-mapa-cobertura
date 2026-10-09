"""baseline: marca o ponto de partida do Alembic (nada a criar)

As tabelas que já existem (operadores, geocode_cache, cep_prefixos, ibge_municipios) continuam sendo criadas
pelo init_db do app e pelos scripts de carga; o Alembic passa a cuidar das tabelas NOVAS, a partir de item_pesos.
Esta revisão não altera o banco: serve só para o Alembic ter uma origem.

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
