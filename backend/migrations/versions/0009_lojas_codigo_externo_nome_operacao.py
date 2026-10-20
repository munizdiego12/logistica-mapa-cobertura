"""lojas.codigo_externo, lojas.nome_operacao e lojas.nome_operacao_chave (Etapa 6c)

- `codigo_externo`: código da loja no sistema de origem (`store_id` da exportação do Superset). Único quando preenchido,
  sem diferença de maiúsculas ou espaços nas pontas.
- `nome_operacao`: nome da loja usado na operação (ex.: "SDA Mooca"; `store_name` do Superset). Único quando preenchido,
  sem diferença de maiúsculas, acentos nem espaços.
- `nome_operacao_chave`: a chave de comparação do nome de operação (sem acentos, sem espaços, minúsculas), calculada pelo
  aplicativo ao gravar. Existe porque o Postgres não deixa criar índice único "sem acento" sem a extensão `unaccent` (que
  não é imutável). O índice único fica nesta chave.

Idempotente (IF NOT EXISTS); nenhum DROP, TRUNCATE ou DELETE; não altera nenhum dado existente.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-20
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

COMANDOS = [
    "ALTER TABLE lojas ADD COLUMN IF NOT EXISTS codigo_externo VARCHAR(40)",
    "ALTER TABLE lojas ADD COLUMN IF NOT EXISTS nome_operacao VARCHAR(120)",
    "ALTER TABLE lojas ADD COLUMN IF NOT EXISTS nome_operacao_chave VARCHAR(120)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_lojas_codigo_externo ON lojas (lower(btrim(codigo_externo))) WHERE codigo_externo IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_lojas_nome_operacao_chave ON lojas (nome_operacao_chave) WHERE nome_operacao_chave IS NOT NULL",
]


def upgrade() -> None:
    for comando in COMANDOS:
        op.execute(comando)


def downgrade() -> None:
    # De propósito não apaga nada: desfazer perderia os códigos e nomes de operação já cadastrados.
    pass
