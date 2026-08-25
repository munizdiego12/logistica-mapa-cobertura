from typing import Optional, List, Dict, Any
from backend.config import PRECO_GASOLINA_LITRO, CUSTO_HOMEM_HORA, TEMPO_PARADA_MINUTOS, MODAIS, ModalConfig

def formatar_tempo(tempo_horas_decimal: float) -> str:
    """Converte horas decimais para formato legível ('1 hora e 48 min')."""
    total_minutos = int(round(tempo_horas_decimal * 60))
    horas = total_minutos // 60
    minutos = total_minutos % 60
    
    if horas > 0 and minutos > 0:
        return f"{horas} hora{'s' if horas > 1 else ''} e {minutos} min"
    elif horas > 0:
        return f"{horas} hora{'s' if horas > 1 else ''}"
    else:
        return f"{minutos} min"

def calculate_route_costs(
    route: List[Dict[str, Any]], 
    hub_coords: List[float],
    nome_modal: str = "Carro de Passeio",
    preco_gasolina: Optional[float] = None,
    custo_hora: Optional[float] = None
) -> Dict[str, Any]:
    """Calcula combustível, manutenção, mão de obra e custo por pedido considerando modais dinâmicos."""
    qtd_pedidos = len(route)
    if qtd_pedidos == 0:
        return {
            "km_total": 0.0,
            "tempo_formatado": "0 min",
            "custo_combustivel": 0.0,
            "custo_manutencao": 0.0,
            "custo_mao_obra": 0.0,
            "custo_total": 0.0,
            "custo_por_pedido": 0.0
        }

    modal: ModalConfig = MODAIS.get(nome_modal, MODAIS["Carro de Passeio"])
    gasolina_efetiva = preco_gasolina if preco_gasolina is not None else PRECO_GASOLINA_LITRO
    hora_efetiva = custo_hora if custo_hora is not None else CUSTO_HOMEM_HORA
    
    # Estimativa de deslocamento e tempo acumulado da rota
    km_real = qtd_pedidos * 3.5  # Média urbana em SP por parada
    tempo_transito_h = (km_real / 30.0)  # Velocidade média estimada em SP
    tempo_espera_total_h = sum([p.get("tempo_espera_min", 0) for p in route]) / 60.0
    tempo_paradas_h = (qtd_pedidos * TEMPO_PARADA_MINUTOS) / 60.0
    
    tempo_total_h = tempo_transito_h + tempo_paradas_h + tempo_espera_total_h
    
    combustivel = (km_real / modal.consumo_km_l) * gasolina_efetiva
    manutencao = km_real * modal.manutencao_km
    mao_obra = tempo_total_h * hora_efetiva
    custo_total = combustivel + manutencao + mao_obra

    return {
        "km_total": round(km_real, 1),
        "tempo_horas_decimal": round(tempo_total_h, 2),
        "tempo_formatado": formatar_tempo(tempo_total_h),
        "custo_combustivel": round(combustivel, 2),
        "custo_manutencao": round(manutencao, 2),
        "custo_mao_obra": round(mao_obra, 2),
        "custo_total": round(custo_total, 2),
        "custo_por_pedido": round(custo_total / qtd_pedidos, 2)
    }