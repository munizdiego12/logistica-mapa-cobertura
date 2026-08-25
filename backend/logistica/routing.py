import math
import requests
import logging
from typing import List, Dict, Tuple, Any

logger = logging.getLogger("RoutingEngine")

OSRM_BASE_URL = "http://router.project-osrm.org/table/v1/driving"

def calcular_distancia_euclidiana(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """Calcula a distância aproximada via fórmula de Haversine."""
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
    """Heurística Nearest Neighbor com suporte a ordenação por capacidade do veículo."""
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

def solve_vrptw(
    depot: Tuple[float, float],
    orders: List[Dict[str, Any]],
    vehicle_capacity: float,
    service_time_min: float = 10.0
) -> List[Dict[str, Any]]:
    """Otimização VRPTW mantendo a janela de entrega e OSRM."""
    if not orders:
        return []

    locations = [depot] + [(o["lat"], o["lon"]) for o in orders]
    coords_str = ";".join([f"{lon},{lat}" for lat, lon in locations])
    url = f"{OSRM_BASE_URL}/{coords_str}?annotations=duration,distance"
    
    try:
        res = requests.get(url, timeout=5)
        durations = res.json().get("durations") if res.status_code == 200 else None
    except Exception:
        durations = None

    n = len(locations)
    if not durations:
        durations = [[(calcular_distancia_euclidiana(locations[i], locations[j]) / 30.0) * 3600 for j in range(n)] for i in range(n)]

    unvisited = list(range(1, n))
    current_node = 0
    current_time_sec = 0.0
    current_load = 0.0
    route = []

    while unvisited:
        best_candidate = None
        best_score = float('inf')

        for candidate in unvisited:
            order = orders[candidate - 1]
            demand = order.get("peso", 1.0)
            if current_load + demand > vehicle_capacity:
                continue

            travel_sec = durations[current_node][candidate]
            arrival_min = (current_time_sec + travel_sec) / 60.0
            window_end = order.get("janela_fim", 1440)

            if arrival_min > window_end:
                continue

            window_start = order.get("janela_inicio", 0)
            wait_min = max(0.0, window_start - arrival_min)
            score = travel_sec + (wait_min * 60 * 0.5)

            if score < best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate is None:
            break

        order = orders[best_candidate - 1]
        travel_sec = durations[current_node][best_candidate]
        arrival_min = (current_time_sec + travel_sec) / 60.0
        start_service_min = max(arrival_min, order.get("janela_inicio", 0))

        current_time_sec = (start_service_min + service_time_min) * 60.0
        current_load += order.get("peso", 1.0)
        current_node = best_candidate

        order["horario_estimado_chegada"] = round(arrival_min, 1)
        order["tempo_espera_min"] = round(start_service_min - arrival_min, 1)
        route.append(order)
        unvisited.remove(best_candidate)

    return route