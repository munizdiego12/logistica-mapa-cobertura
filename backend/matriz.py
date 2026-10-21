"""
Matriz de distâncias e tempos (Etapa 8): OSRM (serviço `table`) quando disponível, com reserva por distância em linha reta.

A reserva usa Haversine × 1,3 (fator de rua) e 22 km/h, os mesmos números que o cálculo antigo já usava. Quando a reserva é usada, o
resultado traz `origem = "linha_reta"` e um aviso claro (os valores passam a ser estimativas). O servidor público do OSRM aceita no máximo
100 pontos por consulta: acima de 99 pedidos (mais o hub) vai direto para a reserva, com aviso.
Pedidos são dado pessoal: aqui só entram coordenadas; nada é registrado em log nem em mensagem de erro (só a classe do erro).
"""
from typing import Optional

import setores as modulo_setores

URL_OSRM = "http://router.project-osrm.org"
LIMITE_PONTOS_OSRM = 100
FATOR_RUA = 1.3
VELOCIDADE_MEDIA_KMH = 22.0
TIMEOUT_S = 8

AVISO_LINHA_RETA = (
    "Não foi possível consultar as distâncias pelas ruas (OSRM). Usei a distância em linha reta (com fator de rua de 1,3 e velocidade média de "
    "22 km/h): distâncias e tempos desta execução são estimativas."
)
AVISO_MUITOS_PONTOS = (
    "São muitos pontos para consultar as distâncias pelas ruas (OSRM público, no máximo 99 pedidos por vez). Usei a distância em linha reta "
    "(fator de rua de 1,3 e 22 km/h): distâncias e tempos desta execução são estimativas."
)


def matriz_linha_reta(pontos: list) -> tuple:
    """(distâncias em metros, tempos em segundos), inteiros; `pontos` = [(lat, lon), ...] com o hub na posição 0."""
    n = len(pontos)
    distancias = [[0] * n for _ in range(n)]
    duracoes = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            metros = modulo_setores.distancia_m(pontos[i][0], pontos[i][1], pontos[j][0], pontos[j][1]) * FATOR_RUA
            distancias[i][j] = int(round(metros))
            duracoes[i][j] = int(round(metros / 1000.0 / VELOCIDADE_MEDIA_KMH * 3600.0))
    return distancias, duracoes


def _reserva(pontos: list, aviso: str) -> dict:
    distancias, duracoes = matriz_linha_reta(pontos)
    return {"distancias_m": distancias, "duracoes_s": duracoes, "origem": "linha_reta", "aviso": aviso}


def _converter(valores, n: int, escala: float) -> Optional[list]:
    """Matriz do OSRM (lista de listas com possíveis null) em inteiros; None se vier incompleta."""
    if not isinstance(valores, list) or len(valores) != n:
        return None
    saida = []
    for linha in valores:
        if not isinstance(linha, list) or len(linha) != n or any(v is None for v in linha):
            return None
        saida.append([int(round(float(v) * escala)) for v in linha])
    return saida


async def obter_matriz(cliente, pontos: list, url_base: str = URL_OSRM) -> dict:
    """
    Devolve {"distancias_m", "duracoes_s", "origem": "osrm"|"linha_reta", "aviso": str|None}. `pontos` = [(lat, lon), ...], hub primeiro.
    `cliente` é um httpx.AsyncClient. Nunca levanta erro de rede: cai para a reserva em linha reta com aviso.
    """
    if len(pontos) <= 1:
        return {"distancias_m": [[0]], "duracoes_s": [[0]], "origem": "osrm", "aviso": None}
    if len(pontos) > LIMITE_PONTOS_OSRM:
        return _reserva(pontos, AVISO_MUITOS_PONTOS)
    coordenadas = ";".join(f"{lon},{lat}" for lat, lon in pontos)
    try:
        resposta = await cliente.get(f"{url_base}/table/v1/driving/{coordenadas}?annotations=duration,distance", timeout=TIMEOUT_S)
        dados = resposta.json()
        if dados.get("code") == "Ok":
            distancias = _converter(dados.get("distances"), len(pontos), 1.0)
            duracoes = _converter(dados.get("durations"), len(pontos), 1.0)
            if distancias is not None and duracoes is not None:
                return {"distancias_m": distancias, "duracoes_s": duracoes, "origem": "osrm", "aviso": None}
    except Exception:  # rede, timeout, JSON ruim: só a reserva importa (nada da resposta vai para log)
        pass
    return _reserva(pontos, AVISO_LINHA_RETA)
