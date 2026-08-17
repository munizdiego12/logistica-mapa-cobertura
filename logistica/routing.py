import math
import requests
import logging
from typing import List, Dict, Tuple, Any

logger = logging.getLogger("RoutingEngine")

def calcular_distancia_euclidiana(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def sequenciar_rotas_nearest_neighbor(
    origem_coords: Tuple[float, float], 
    pedidos: List[Dict[str, Any]], 
    capacidade: int = 5
) -> List[List[Dict[str, Any]]]:
    """Heurística Nearest Neighbor com guarda contra loops infinitos."""
    if capacidade < 1:
        raise ValueError("A capacidade do veículo/modal deve ser no mínimo 1.")
        
    rotas = []
    nao_atendidos = pedidos.copy()
    
    while nao_atendidos:
        rota_atual = []
        ponto_referencia = origem_coords
        
        while len(rota_atual) < capacidade and nao_atendidos:
            mais_proximo = min(
                nao_atendidos,
                key=lambda p: calcular_distancia_euclidiana(ponto_referencia, (p['lat'], p['lon']))
            )
            rota_atual.append(mais_proximo)
            ponto_referencia = (mais_proximo['lat'], mais_proximo['lon'])
            nao_atendidos.remove(mais_proximo)
            
        rotas.append(rota_atual)
        
    return rotas

def obter_trajeto_asfalto_osrm(pontos: List[Tuple[float, float]]) -> Tuple[List[List[float]], float, float]:
    coords_str = ";".join([f"{lon:.6f},{lat:.6f}" for lat, lon in pontos])
    url = f"https://router.project-osrm.org/route/v1/driving/{coords_str}"
    
    try:
        res = requests.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=10).json()
        if res.get("code") == "Ok":
            rota = res["routes"][0]
            km = rota["distance"] / 1000.0
            duracao_h = rota["duration"] / 3600.0
            geometria = [[lat, lon] for lon, lat in rota["geometry"]["coordinates"]]
            return geometria, km, duracao_h
    except Exception as e:
        logger.warning(f"OSRM indisponível ({e}). Usando fallback de malha estimada.")
        
    dist_total = sum(calcular_distancia_euclidiana(pontos[i], pontos[i+1]) for i in range(len(pontos)-1)) * 1.35
    return [[lat, lon] for lat, lon in pontos], dist_total, dist_total / 20.0