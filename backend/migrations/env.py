"""
Ambiente do Alembic (assíncrono, com asyncpg).

A URL do banco vem SOMENTE da variável de ambiente DATABASE_URL (nunca de arquivo). O psycopg2 pode estar
bloqueado no Windows, por isso as migrations rodam com asyncpg. Veja backend/alembic.ini para os comandos.

target_metadata = None: as migrations são escritas à mão (as tabelas antigas continuam sendo criadas pelo
init_db do app; o Alembic cuida das tabelas novas, a partir de item_pesos).
"""
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from db_url import mascarar_senha, url_sqlalchemy_asyncpg

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _url_do_ambiente() -> tuple:
    bruto = os.getenv("DATABASE_URL")
    if not bruto:
        raise RuntimeError(
            "Defina a variável de ambiente DATABASE_URL (a string do banco) antes de rodar o Alembic, por exemplo:\n"
            '  $env:DATABASE_URL = "<string do Neon>"   (PowerShell)'
        )
    try:
        return url_sqlalchemy_asyncpg(bruto)
    except ValueError as erro:
        raise RuntimeError(f"DATABASE_URL inválida ({erro}): {mascarar_senha(bruto)}") from erro


def run_migrations_offline() -> None:
    """Gera o SQL sem conectar (alembic upgrade head --sql)."""
    context.configure(
        url="postgresql+asyncpg://",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _executar(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _executar_online() -> None:
    url, connect_args = _url_do_ambiente()
    engine = create_async_engine(url, poolclass=pool.NullPool, connect_args=connect_args)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_executar)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_executar_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
