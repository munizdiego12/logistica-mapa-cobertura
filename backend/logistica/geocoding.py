"""
Módulo de Geocodificação do Zubale Routing Core.

Realiza a resolução de coordenadas via CEP e endereço utilizando arquitetura em cascata:
1. Cache Persistente no Postgres (via database.py)
2. BrasilAPI v2 (dados diretos de logradouro/coordenadas)
3. ViaCEP + Nominatim/OpenStreetMap (fallback com busca de endereço)
4. Sinalização de erro (ERRO_CEP_INVALIDO) sem criação de coordenadas fictícias
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional
import httpx

# Importa as funções de persistência assíncronas do database.py
from database import cache_get, cache_set, invalidar_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("geocoding")

# Limites de concorrência e requisições
SEMAPHORE_LIMIT = 5
SEMAPHORE = asyncio.Semaphore(SEMAPHORE_LIMIT)
NOMINATIM_USER_AGENT = "zubale_routing_core_v2"


def clean_cep(cep_str: str) -> str:
    """Higieniza e formata o CEP para conter exatamente 8 dígitos numéricos."""
    return re.sub(r"\D", "", str(cep_str or "")).zfill(8)


async def buscar_cep_brasilapi(client: httpx.AsyncClient, cep: str) -> Optional[Dict]:
    """Consulta o CEP na BrasilAPI v2 e extrai coordenadas e endereço."""
    clean = clean_cep(cep)
    if len(clean) != 8:
        return None

    url = f"https://brasilapi.com.br/api/cep/v2/{clean}"
    try:
        response = await client.get(url, timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            location = data.get("location", {}) or {}
            coords = location.get("coordinates", {}) or {}
            lat = coords.get("latitude")
            lon = coords.get("longitude")

            has_coords = lat is not None and lon is not None
            return {
                "lat": float(lat) if has_coords else None,
                "lon": float(lon) if has_coords else None,
                "cidade": data.get("city"),
                "uf": data.get("state"),
                "cep": clean,
                "bairro": data.get("neighborhood"),
                "status": "VALIDO" if has_coords else "ALERTA_APROXIMADO"
            }
    except Exception as e:
        logger.warning(f"[geocoding] Falha ao consultar BrasilAPI para o CEP {clean}: {e}")
    return None


async def buscar_cep_viacep_nominatim(client: httpx.AsyncClient, cep: str) -> Optional[Dict]:
    """Fallback via ViaCEP para obter o logradouro e Nominatim para geocodificar o texto."""
    clean = clean_cep(cep)
    if len(clean) != 8:
        return None

    url_viacep = f"https://viacep.com.br/ws/{clean}/json/"
    try:
        res_v = await client.get(url_viacep, timeout=5.0)
        if res_v.status_code == 200 and not res_v.json().get("erro"):
            data = res_v.json()
            logradouro = data.get("logradouro", "")
            bairro = data.get("bairro", "")
            cidade = data.get("localidade", "")
            uf = data.get("uf", "")

            address_parts = [p for p in [logradouro, bairro, cidade, uf, "Brasil"] if p]
            address_str = ", ".join(address_parts)

            url_nom = "https://nominatim.openstreetmap.org/search"
            headers = {"User-Agent": NOMINATIM_USER_AGENT}
            params = {"q": address_str, "format": "json", "limit": 1}

            await asyncio.sleep(0.5)  # Respeita o rate limit do OSM/Nominatim
            res_nom = await client.get(url_nom, params=params, headers=headers, timeout=5.0)

            if res_nom.status_code == 200 and res_nom.json():
                nom_data = res_nom.json()[0]
                return {
                    "lat": float(nom_data["lat"]),
                    "lon": float(nom_data["lon"]),
                    "cidade": cidade,
                    "uf": uf,
                    "cep": clean,
                    "bairro": bairro,
                    "status": "VALIDO"
                }

            return {
                "lat": None,
                "lon": None,
                "cidade": cidade,
                "uf": uf,
                "cep": clean,
                "bairro": bairro,
                "status": "ALERTA_APROXIMADO"
            }
    except Exception as e:
        logger.warning(f"[geocoding] Falha no fallback ViaCEP/Nominatim para o CEP {clean}: {e}")
    return None


async def geocode_cep_cascata(cep: str, client: Optional[httpx.AsyncClient] = None) -> Dict:
    """
    Executa a resolução de coordenadas em cascata salvando no Postgres via database.py.
    """
    clean = clean_cep(cep)
    chave = f"cep:{clean}"

    if not clean or len(clean) != 8:
        return {
            "lat": None,
            "lon": None,
            "cidade": None,
            "uf": None,
            "cep": clean,
            "bairro": None,
            "status": "ERRO_CEP_INVALIDO"
        }

    # 1. Tenta recuperar do Cache do Postgres
    cached = await cache_get(chave)
    if cached:
        lat, lon, cidade, uf, cep_c, bairro, status = cached
        return {
            "lat": lat,
            "lon": lon,
            "cidade": cidade,
            "uf": uf,
            "cep": cep_c or clean,
            "bairro": bairro,
            "status": status
        }

    # Executa consulta externa controlada pelo Semáforo
    async with SEMAPHORE:
        close_client = False
        if client is None:
            client = httpx.AsyncClient()
            close_client = True

        try:
            # 2. BrasilAPI v2
            res = await buscar_cep_brasilapi(client, clean)

            # 3. ViaCEP + Nominatim (se a BrasilAPI não trouxe coordenadas válidas)
            if not res or res.get("lat") is None:
                res_fallback = await buscar_cep_viacep_nominatim(client, clean)
                if res_fallback:
                    if res_fallback.get("lat") is not None or res is None:
                        res = res_fallback

            # 4. Caso o CEP seja totalmente inexistente nas bases oficiais
            if not res:
                res = {
                    "lat": None,
                    "lon": None,
                    "cidade": None,
                    "uf": None,
                    "cep": clean,
                    "bairro": None,
                    "status": "ERRO_CEP_INVALIDO"
                }

            # Salva no cache do Postgres (inclusive CEPs inválidos para evitar re-consultas)
            tupla_cache = (
                res.get("lat"),
                res.get("lon"),
                res.get("cidade"),
                res.get("uf"),
                res.get("cep") or clean,
                res.get("bairro"),
                res.get("status")
            )
            await cache_set(chave, tupla_cache)
            return res

        finally:
            if close_client:
                await client.aclose()


async def resolve_single_location(item: Dict, client: Optional[httpx.AsyncClient] = None) -> Dict:
    """
    Resolve as coordenadas de um pedido individual sem inventar dados sintéticos.
    """
    cep = item.get("cep", "")
    geo_res = await geocode_cep_cascata(cep, client=client)

    item["lat"] = geo_res.get("lat")
    item["lon"] = geo_res.get("lon")
    item["cidade"] = geo_res.get("cidade")
    item["uf"] = geo_res.get("uf")
    item["bairro"] = geo_res.get("bairro")
    item["geocode_status"] = geo_res.get("status")

    if geo_res.get("status") == "VALIDO":
        item["geocode_source"] = "cascata_exato"
    elif geo_res.get("status") == "ALERTA_APROXIMADO":
        item["geocode_source"] = "cascata_aproximado"
    else:
        item["geocode_source"] = "erro_invalid_cep"

    return item


async def process_batch_geocoding(items: List[Dict]) -> List[Dict]:
    """Processa lote de pedidos em paralelo garantindo reutilização da sessão HTTP."""
    async with httpx.AsyncClient() as client:
        tasks = [resolve_single_location(item, client=client) for item in items]
        return await asyncio.gather(*tasks)