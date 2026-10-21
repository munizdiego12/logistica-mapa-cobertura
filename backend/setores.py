"""
Setores cardeais (Etapa 8): a região de um pedido é o setor, entre 8 (N, NE, L, SE, S, SO, O, NO), pelo AZIMUTE entre a loja (hub)
e o pedido. O bairro serve só para exibição.

Azimute: 0° = norte, crescendo no sentido horário (90° = leste). Cada setor cobre 45° centrados na direção cardeal, então o N vai de
337,5° a 22,5° (a fronteira de baixo é inclusiva: 22,5° já é NE). Pedido praticamente em cima da loja (menos de 20 m) não tem direção:
por convenção documentada entra no setor N.
Só stdlib: o módulo é importado pelo app (backend/ no path) e pelos testes.
"""
import math
from typing import Iterable

SETORES = ("N", "NE", "L", "SE", "S", "SO", "O", "NO")
RAIO_SEM_DIRECAO_M = 20.0
RAIO_TERRA_M = 6371008.8


def distancia_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em linha reta (haversine), em metros."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * RAIO_TERRA_M * math.asin(math.sqrt(a))


def azimute(lat0: float, lon0: float, lat: float, lon: float) -> float:
    """Azimute em graus [0, 360) da direção (lat0, lon0) -> (lat, lon): 0 = norte, 90 = leste."""
    p0, p1 = math.radians(lat0), math.radians(lat)
    dlon = math.radians(lon - lon0)
    x = math.sin(dlon) * math.cos(p1)
    y = math.cos(p0) * math.sin(p1) - math.sin(p0) * math.cos(p1) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def setor_do_azimute(graus: float) -> str:
    return SETORES[int(((graus % 360.0) + 22.5) // 45) % 8]


def setor_do_pedido(lat_hub: float, lon_hub: float, lat: float, lon: float) -> str:
    """Setor do pedido em relação à loja. Pedido a menos de 20 m da loja entra no N (convenção)."""
    if distancia_m(lat_hub, lon_hub, lat, lon) < RAIO_SEM_DIRECAO_M:
        return "N"
    return setor_do_azimute(azimute(lat_hub, lon_hub, lat, lon))


def distancia_circular(a: str, b: str) -> int:
    """Quantos setores separam a de b (0 = o mesmo, 4 = opostos)."""
    d = abs(SETORES.index(a) - SETORES.index(b))
    return min(d, 8 - d)


def oposto(setor: str) -> str:
    return SETORES[(SETORES.index(setor) + 4) % 8]


def texto_dos_setores(setores: Iterable[str]) -> str:
    """'N,NE' na ordem N, NE, L, SE, S, SO, O, NO, sem repetir."""
    conjunto = set(setores)
    return ",".join(s for s in SETORES if s in conjunto)


def setores_do_texto(texto) -> list:
    """Inverso de texto_dos_setores; ignora o que não for setor."""
    return [s for s in (texto or "").replace(" ", "").split(",") if s in SETORES]
