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
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

try:
    import asyncpg
except ImportError:
    asyncpg = None

# Importa as configurações globais
from config import DATABASE_URL as CONFIG_DATABASE_URL

# Obtém a URL vinda de config.py ou direto do os.environ
DATABASE_URL = CONFIG_DATABASE_URL or os.environ.get("DATABASE_URL", "")

_pool = None


def _normalizar_dsn(url: str) -> str:
    """O Render fornece a URL como 'postgres://...', mas o asyncpg e o SQLAlchemy exigem 'postgresql://'."""
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url
# Normaliza a URL principal do banco de dados
URL_NORMALIZADA = _normalizar_dsn(DATABASE_URL)

# --- Configuração SQLAlchemy (Síncrono para ORM / Auth) ---
url_sqlalchemy = URL_NORMALIZADA if URL_NORMALIZADA else "sqlite:///./sql_app.db"

connect_args = {"check_same_thread": False} if url_sqlalchemy.startswith("sqlite") else {}

engine = create_engine(url_sqlalchemy, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency para injeção da sessão de banco de dados nos endpoints do FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_pool():
    global _pool
    if _pool is None and URL_NORMALIZADA and asyncpg:
        try:
            _pool = await asyncpg.create_pool(
                dsn=URL_NORMALIZADA,
                min_size=1,
                max_size=5,
                command_timeout=10,
            )
        except Exception as e:
            print(f"[database] Falha ao conectar no Postgres via asyncpg, seguindo sem persistência: {e}")
            _pool = None
    return _pool


async def init_db():
    """Cria a tabela de cache de geocodificação e as tabelas ORM se não existirem."""
    Base.metadata.create_all(bind=engine)
    pool = await get_pool()
    if not pool:
        print("[database] DATABASE_URL não configurada — cache de geocodificação NÃO é persistente.")
        return
    async with pool.acquire() as conn:
        # lat/lon aceitam NULL: um CEP/endereço com status ERRO_CEP_INVALIDO é
        # salvo sem coordenada, para não inventar uma posição geográfica falsa.
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geocode_cache (
                chave       TEXT PRIMARY KEY,
                lat         DOUBLE PRECISION,
                lon         DOUBLE PRECISION,
                cidade      TEXT,
                uf          TEXT,
                cep         TEXT,
                bairro      TEXT,
                status      TEXT DEFAULT 'VALIDO',
                criado_em   TIMESTAMP DEFAULT NOW()
            )
            """
        )
        # Migração segura para bancos já existentes em produção (Render): adiciona
        # a coluna 'status' se ainda não existir e remove o NOT NULL de lat/lon,
        # sem apagar nenhum dado já cacheado.
        await conn.execute(
            "ALTER TABLE geocode_cache ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'VALIDO'"
        )
        await conn.execute("ALTER TABLE geocode_cache ALTER COLUMN lat DROP NOT NULL")
        await conn.execute("ALTER TABLE geocode_cache ALTER COLUMN lon DROP NOT NULL")
    print("[database] Cache de geocodificação persistente (Postgres) pronto.")


async def cache_get(chave: str):
    """
    Devolve uma tupla de 7 posições: (lat, lon, cidade, uf, cep, bairro, status).
    'status' é um de: VALIDO, ALERTA_APROXIMADO, ERRO_CEP_INVALIDO.
    Registros salvos antes desta coluna existir voltam com status 'VALIDO'
    (era o único comportamento possível antes da Etapa 2).
    """
    pool = await get_pool()
    if not pool:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT lat, lon, cidade, uf, cep, bairro, status FROM geocode_cache WHERE chave = $1",
            chave,
        )
        if row:
            return (
                row["lat"], row["lon"], row["cidade"], row["uf"], row["cep"], row["bairro"],
                row["status"] or "VALIDO",
            )
    return None


async def cache_set(chave: str, resultado: tuple):
    """
    Aceita uma tupla de 7 posições: (lat, lon, cidade, uf, cep, bairro, status).
    Por compatibilidade, também aceita a tupla antiga de 6 posições (sem status),
    assumindo 'VALIDO' nesse caso.
    """
    pool = await get_pool()
    if not pool:
        return
    if len(resultado) == 7:
        lat, lon, cidade, uf, cep, bairro, status = resultado
    else:
        lat, lon, cidade, uf, cep, bairro = resultado
        status = "VALIDO"
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO geocode_cache (chave, lat, lon, cidade, uf, cep, bairro, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (chave) DO UPDATE SET
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                cidade = EXCLUDED.cidade,
                uf = EXCLUDED.uf,
                cep = EXCLUDED.cep,
                bairro = EXCLUDED.bairro,
                status = EXCLUDED.status
            """,
            chave, lat, lon, cidade, uf, cep, bairro, status,
        )


async def invalidar_cache(chave: str):
    """
    Remove uma entrada do cache de geocodificação para forçar uma nova consulta
    às APIs externas na próxima vez que essa chave for pedida.

    Ainda não há, nesta etapa, nenhuma rota que edite um pedido já persistido
    (os pedidos hoje vêm de upload de CSV/XLSX e são processados em memória),
    então esta função fica pronta para quando essa funcionalidade existir, sem
    estar conectada a nenhum endpoint por enquanto.
    """
    pool = await get_pool()
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM geocode_cache WHERE chave = $1", chave)


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


# --- Modelos ORM do SQLAlchemy ---
class Operador(Base):
    __tablename__ = "operadores"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    senha_hash = Column(String, nullable=False)
    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=datetime.utcnow)