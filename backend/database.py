"""
Camada de persistência do Zubale Routing Core.

Guarda o resultado de geocodificação (endereço -> lat/lon) em um banco Postgres
gratuito do Render, para nunca precisar geocodificar o mesmo endereço duas vezes,
mesmo depois de o servidor reiniciar ou "dormir" (plano free).

Se a variável de ambiente DATABASE_URL não estiver configurada, o sistema
continua funcionando normalmente, só que sem persistência entre reinícios
(usa apenas o cache em memória do processo).
"""

import os
import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_pool = None


def _normalizar_dsn(url: str) -> str:
    # O Render fornece a URL como "postgres://...", mas o asyncpg exige "postgresql://"
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


async def get_pool():
    global _pool
    if _pool is None and DATABASE_URL:
        try:
            _pool = await asyncpg.create_pool(
                dsn=_normalizar_dsn(DATABASE_URL),
                min_size=1,
                max_size=5,
                command_timeout=10,
            )
        except Exception as e:
            print(f"[database] Falha ao conectar no Postgres, seguindo sem persistência: {e}")
            _pool = None
    return _pool


async def init_db():
    """Cria a tabela de cache de geocodificação, se ainda não existir. Chamar no startup."""
    pool = await get_pool()
    if not pool:
        print("[database] DATABASE_URL não configurada — cache de geocodificação NÃO é persistente.")
        return
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geocode_cache (
                chave       TEXT PRIMARY KEY,
                lat         DOUBLE PRECISION NOT NULL,
                lon         DOUBLE PRECISION NOT NULL,
                cidade      TEXT,
                uf          TEXT,
                cep         TEXT,
                bairro      TEXT,
                criado_em   TIMESTAMP DEFAULT NOW()
            )
            """
        )
    print("[database] Cache de geocodificação persistente (Postgres) pronto.")


async def cache_get(chave: str):
    pool = await get_pool()
    if not pool:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT lat, lon, cidade, uf, cep, bairro FROM geocode_cache WHERE chave = $1",
            chave,
        )
        if row:
            return (row["lat"], row["lon"], row["cidade"], row["uf"], row["cep"], row["bairro"])
    return None


async def cache_set(chave: str, resultado: tuple):
    pool = await get_pool()
    if not pool:
        return
    lat, lon, cidade, uf, cep, bairro = resultado
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO geocode_cache (chave, lat, lon, cidade, uf, cep, bairro)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (chave) DO UPDATE SET
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                cidade = EXCLUDED.cidade,
                uf = EXCLUDED.uf,
                cep = EXCLUDED.cep,
                bairro = EXCLUDED.bairro
            """,
            chave, lat, lon, cidade, uf, cep, bairro,
        )


async def cache_stats():
    """Só para diagnóstico: quantos endereços já estão salvos permanentemente."""
    pool = await get_pool()
    if not pool:
        return {"persistente": False, "total_enderecos": 0}
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM geocode_cache")
    return {"persistente": True, "total_enderecos": total}
