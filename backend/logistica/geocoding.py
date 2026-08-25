import asyncio
import logging
import re
import sqlite3
import aiohttp
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("geocoding")

DB_PATH = "geocoding_cache.db"
SP_CENTER_COORDS = (-23.550520, -46.633308)

# Configurações de taxa de requisição
SEMAPHORE_LIMIT = 5  # Limite de chamadas concorrentes externas
NOMINATIM_USER_AGENT = "zubale_routing_core_v2"


def init_db():
    """Inicializa a tabela de cache persistente no SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS geocode_cache (
                key TEXT PRIMARY KEY,
                lat REAL,
                lon REAL,
                source TEXT
            )
        """)
        conn.commit()


def get_from_cache(key: str) -> Optional[Tuple[float, float, str]]:
    """Recupera coordenadas do cache SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT lat, lon, source FROM geocode_cache WHERE key = ?", (key.strip().lower(),))
        row = cursor.fetchone()
        if row:
            return row[0], row[1], row[2]
    return None


def save_to_cache(key: str, lat: float, lon: float, source: str):
    """Salva o resultado obtido no cache SQLite."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO geocode_cache (key, lat, lon, source) VALUES (?, ?, ?, ?)",
            (key.strip().lower(), lat, lon, source)
        )
        conn.commit()


def clean_cep(cep_str: str) -> str:
    """Higieniza o formato do CEP."""
    return re.sub(r"\D", "", str(cep_str)).zfill(8)


async def fetch_with_retry(session: aiohttp.ClientSession, url: str, headers: dict = None, retries: int = 3, backoff_factor: float = 0.5) -> Optional[dict]:
    """Realiza requisições HTTP assíncronas com tratamento de erros e backoff exponencial."""
    for attempt in range(retries):
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status in (429, 500, 502, 503, 504):
                    await asyncio.sleep(backoff_factor * (2 ** attempt))
                else:
                    break
        except (aiohttp.ClientError, asyncio.TimeoutError):
            await asyncio.sleep(backoff_factor * (2 ** attempt))
    return None


async def geocode_cep_brasilapi(session: aiohttp.ClientSession, cep: str) -> Optional[Tuple[float, float]]:
    """Obtém coordenadas via BrasilAPI a partir do CEP."""
    clean = clean_cep(cep)
    if len(clean) != 8:
        return None
    
    cached = get_from_cache(f"cep:{clean}")
    if cached:
        return cached[0], cached[1]

    url = f"https://brasilapi.com.br/api/cep/v2/{clean}"
    data = await fetch_with_retry(session, url)
    
    if data and "location" in data and "coordinates" in data["location"]:
        coords = data["location"]["coordinates"]
        if coords.get("latitude") and coords.get("longitude"):
            lat = float(coords["latitude"])
            lon = float(coords["longitude"])
            save_to_cache(f"cep:{clean}", lat, lon, "brasilapi")
            return lat, lon
    return None


async def geocode_address_nominatim(session: aiohttp.ClientSession, address: str, semaphore: asyncio.Semaphore) -> Optional[Tuple[float, float]]:
    """Obtém coordenadas via Nominatim (OpenStreetMap) com controle de concorrência."""
    cached = get_from_cache(f"addr:{address}")
    if cached:
        return cached[0], cached[1]

    async with semaphore:
        # Respeita os limites da API de OpenStreetMap
        await asyncio.sleep(1.0) 
        url = "https://nominatim.openstreetmap.org/search"
        params = f"?q={aiohttp.helpers.quote_plus(address)}&format=json&limit=1"
        headers = {"User-Agent": NOMINATIM_USER_AGENT}
        
        data = await fetch_with_retry(session, url + params, headers=headers)
        if data and len(data) > 0:
            lat = float(data[0]["lat"])
            lon = float(data[0]["lon"])
            save_to_cache(f"addr:{address}", lat, lon, "nominatim")
            return lat, lon
    return None


async def resolve_single_location(session: aiohttp.ClientSession, item: Dict, semaphore: asyncio.Semaphore) -> Dict:
    """
    Resolve as coordenadas de um único pedido utilizando fallbacks estruturados:
    1. Cache SQLite
    2. BrasilAPI (via CEP)
    3. Nominatim (via Endereço)
    4. Fallback Centro de SP
    """
    init_db()
    cep = item.get("cep", "")
    address = item.get("endereco", "")
    
    # 1. Tentativa via CEP
    if cep:
        coords = await geocode_cep_brasilapi(session, cep)
        if coords:
            item["lat"], item["lon"], item["geocode_source"] = coords[0], coords[1], "brasilapi"
            return item

    # 2. Tentativa via Endereço Completo
    full_address = f"{address}, São Paulo, SP, Brasil" if address else ""
    if full_address:
        coords = await geocode_address_nominatim(session, full_address, semaphore)
        if coords:
            item["lat"], item["lon"], item["geocode_source"] = coords[0], coords[1], "nominatim"
            return item

    # 3. Fallback Padrão (Centro de SP)
    item["lat"], item["lon"], item["geocode_source"] = SP_CENTER_COORDS[0], SP_CENTER_COORDS[1], "fallback_sp_center"
    return item


async def process_batch_geocoding(items: List[Dict]) -> List[Dict]:
    """Processa uma lista de pedidos em lote concorrente de forma assíncrona."""
    init_db()
    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    
    async with aiohttp.ClientSession() as session:
        tasks = [resolve_single_location(session, item, semaphore) for item in items]
        return await asyncio.gather(*tasks)