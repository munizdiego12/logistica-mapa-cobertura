"""item_pesos: peso por item (SKU), com quem alterou e quando

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_pesos",
        sa.Column("id_sku", sa.String(40), primary_key=True),
        sa.Column("reference_code", sa.String(60), nullable=True),
        sa.Column("nome", sa.Text(), nullable=True),
        # NULL = ainda sem peso (o item aparece na fila "sem peso").
        sa.Column("peso_kg", sa.Numeric(10, 4), nullable=True),
        sa.Column("fonte", sa.String(100), nullable=True),
        sa.Column("confianca", sa.String(10), nullable=True),
        # Para ordenar a fila "sem peso" pelo que mais sai (não estava na lista original de colunas).
        sa.Column("unidades_vendidas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Quem alterou por último: "Nome (email)" do operador, ou "carga inicial (script)".
        sa.Column("atualizado_por", sa.String(200), nullable=True),
        sa.CheckConstraint("peso_kg IS NULL OR (peso_kg > 0 AND peso_kg <= 1000)", name="ck_item_pesos_peso_plausivel"),
        sa.CheckConstraint("confianca IS NULL OR confianca IN ('alta', 'media', 'baixa')", name="ck_item_pesos_confianca"),
    )
    op.create_index(
        "ix_item_pesos_fila_sem_peso",
        "item_pesos",
        [sa.text("unidades_vendidas DESC")],
        postgresql_where=sa.text("peso_kg IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_item_pesos_fila_sem_peso", table_name="item_pesos")
    op.drop_table("item_pesos")
