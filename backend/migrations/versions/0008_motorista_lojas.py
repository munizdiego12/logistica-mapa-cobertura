"""motorista_lojas, motoristas.codigo e motoristas.telefone (Etapa 6b)

- `motorista_lojas`: lojas de cada motorista (muitos para muitos). Chave composta (motorista, loja). Loja desativada
  depois continua vinculada: só o operador remove um vínculo, nunca a desativação da loja.
- `motoristas.codigo`: código único do motorista (ex.: MOT-0001), a chave do sistema. Único quando preenchido, sem
  diferença de maiúsculas ou espaços (o app também tira os acentos antes de gravar). Aceita NULL só para os motoristas
  antigos de teste, já desativados: a regra "obrigatório" para cadastro novo é do aplicativo.
- `motoristas.telefone`: opcional, só dígitos (10 ou 11, com DDD). Dado pessoal: o app o mascara nas listas.

Idempotente (IF NOT EXISTS, com o CHECK dentro da definição da coluna); nenhum DROP, TRUNCATE ou DELETE; não altera
nenhum dado existente.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-16
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

COMANDOS = [
    "ALTER TABLE motoristas ADD COLUMN IF NOT EXISTS codigo VARCHAR(40)",
    """
    ALTER TABLE motoristas
        ADD COLUMN IF NOT EXISTS telefone VARCHAR(11)
        CONSTRAINT ck_motoristas_telefone CHECK (telefone IS NULL OR length(telefone) IN (10, 11))
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_motoristas_codigo ON motoristas (lower(btrim(codigo))) WHERE codigo IS NOT NULL",
    """
    CREATE TABLE IF NOT EXISTS motorista_lojas (
        motorista_id INTEGER NOT NULL REFERENCES motoristas (id),
        loja_id INTEGER NOT NULL REFERENCES lojas (id),
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        atualizado_por VARCHAR(200),
        PRIMARY KEY (motorista_id, loja_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_motorista_lojas_loja ON motorista_lojas (loja_id)",
]


def upgrade() -> None:
    for comando in COMANDOS:
        op.execute(comando)


def downgrade() -> None:
    # De propósito não apaga nada: desfazer perderia códigos, telefones e vínculos já cadastrados.
    pass
