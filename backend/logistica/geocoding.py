import time
import requests
import logging
import threading
from typing import Tuple
from config import BBOX_SP
from logistica.cache import GeocodingCache

logger = logging.getLogger("Geocoding")

# Lock global para coordenar requisições ao Nominatim em threads simultâneas
_nominatim_lock = threading.Lock()
_ultimo_acesso_nominatim = 0.0

class GeocoderSP:
    def __init__(self, cache_db: str = "geocache.db"):
        self.cache = GeocodingCache(cache_db)
        self.headers = {"User-Agent": "LogisticaHub_Enterprise_SP/1.0"}
        
        self.bairros_fallback = {
            "itaim": (-23.5844, -46.6800), "olimpia": (-23.5954, -46.6865),
            "paraiso": (-23.5714, -46.6450), "pinheiros": (-23.5615, -46.6920),
            "perdizes": (-23.5365, -46.6730), "consolacao": (-23.5530, -46.6590),
            "mariana": (-23.5890, -46.6340), "madalena": (-23.5540, -46.6900),
            "brooklin": (-23.6180, -46.6900), "moema": (-23.6020, -46.6620)
        }

    def _esta_em_sp(self, lat: float, lon: float) -> bool:
        return (BBOX_SP["lat_min"] < lat < BBOX_SP["lat_max"] and 
                BBOX_SP["lon_min"] < lon < BBOX_SP["lon_max"])

    def _requisitar_nominatim_seguro(self, query_str: str):
        global _ultimo_acesso_nominatim
        with _nominatim_lock:
            tempo_decorrido = time.time() - _ultimo_acesso_nominatim
            if tempo_decorrido < 1.05:
                time.sleep(1.05 - tempo_decorrido)
            
            _ultimo_acesso_nominatim = time.time()
            
            return requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query_str, "format": "json", "limit": 1, "countrycodes": "br"},
                headers=self.headers,
                timeout=5
            ).json()

    def geocodificar(self, logradouro: str, numero: str, bairro: str, cep_limpo: str) -> Tuple[float, float]:
        chave_busca = f"{logradouro}, {numero}, {bairro}, {cep_limpo}"
        
        # 1. Cache Local
        cached = self.cache.get(chave_busca)
        if cached:
            return cached

        # 2. Consulta Nominatim Estruturada
        queries = [
            f"{logradouro}, {numero}, {bairro}, {cep_limpo}, São Paulo - SP, Brasil",
            f"{logradouro}, {bairro}, São Paulo - SP, Brasil"
        ]
        
        for q in queries:
            try:
                res = self._requisitar_nominatim_seguro(q)
                if res and isinstance(res, list) and len(res) > 0:
                    lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
                    if self._esta_em_sp(lat, lon):
                        self.cache.set(chave_busca, lat, lon, "nominatim")
                        return lat, lon
            except Exception as e:
                logger.warning(f"Falha na requisição Nominatim ({q}): {e}")

        # 3. Consulta BrasilAPI v2 por CEP
        if len(cep_limpo) == 8:
            try:
                time.sleep(0.3)
                res_cep = requests.get(f"https://brasilapi.com.br/api/cep/v2/{cep_limpo}", timeout=5).json()
                coords = res_cep.get("location", {}).get("coordinates", {})
                if coords:
                    lat, lon = float(coords["latitude"]), float(coords["longitude"])
                    if self._esta_em_sp(lat, lon):
                        self.cache.set(chave_busca, lat, lon, "brasilapi")
                        return lat, lon
            except Exception as e:
                logger.warning(f"Falha na BrasilAPI para CEP {cep_limpo}: {e}")

        # 4. Fallback por Dicionário de Bairros de SP
        bairro_lower = str(bairro).lower()
        for k, v in self.bairros_fallback.items():
            if k in bairro_lower:
                logger.info(f"Geocoding aproximado via bairro: '{bairro}'")
                self.cache.set(chave_busca, v[0], v[1], "bairro_fallback")
                return v

        # Fallback Central SP
        centro = (-23.5505, -46.6333)
        self.cache.set(chave_busca, centro[0], centro[1], "default_sp")
        return centro