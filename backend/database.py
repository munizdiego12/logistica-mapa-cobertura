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
import math
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


async def consultar_ceps_por_raio(lat_origem: float, lon_origem: float, raio_km: float):
    pool = await get_pool()
    if not pool:
        return []

    query = """
        SELECT cep_inicial, cep_final, uf, cidade, bairro, lat, lon,
               (6371 * acos(
                   LEAST(1.0, GREATEST(-1.0,
                       cos(radians($1)) * cos(radians(lat)) *
                       cos(radians(lon) - radians($2)) + 
                       sin(radians($1)) * sin(radians(lat))
                   ))
               )) AS distancia_km
        FROM ceps_reais
        WHERE (6371 * acos(
                   LEAST(1.0, GREATEST(-1.0,
                       cos(radians($1)) * cos(radians(lat)) *
                       cos(radians(lon) - radians($2)) + 
                       sin(radians($1)) * sin(radians(lat))
                   ))
               )) <= $3
        ORDER BY distancia_km ASC;
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(query, lat_origem, lon_origem, raio_km)

    resultados = []
    for row in rows:
        dist = float(row['distancia_km'])
        cep_ini_fmt = f"{str(row['cep_inicial']).zfill(8)[:5]}-{str(row['cep_inicial']).zfill(8)[5:]}"
        cep_fim_fmt = f"{str(row['cep_final']).zfill(8)[:5]}-{str(row['cep_final']).zfill(8)[5:]}"

        resultados.append({
            "ibge": 3550308,
            "uf": row['uf'],
            "cidade": row['cidade'],
            "bairro": row['bairro'],
            "cep_inicial": str(row['cep_inicial']).zfill(8),
            "cep_final": str(row['cep_final']).zfill(8),
            "faixa_completa": f"{cep_ini_fmt} a {cep_fim_fmt}",
            "distancia_km": round(dist, 2),
            "dias_sla": 1 if dist <= 12 else 2,
            "lat": float(row['lat']),
            "lon": float(row['lon'])
        })

    return resultados