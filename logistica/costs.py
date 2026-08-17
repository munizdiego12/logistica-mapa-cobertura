from config import PRECO_GASOLINA_LITRO, CUSTO_HOMEM_HORA, TEMPO_PARADA_MINUTOS, MODAIS, ModalConfig

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

def calcular_custo_operacional(km_real: float, tempo_transito_h: float, qtd_pedidos: int, nome_modal: str = "Carro de Passeio") -> dict:
    """Calcula combustível, manutenção e homem-hora."""
    modal: ModalConfig = MODAIS.get(nome_modal, MODAIS["Carro de Passeio"])
    
    combustivel = (km_real / modal.consumo_km_l) * PRECO_GASOLINA_LITRO
    manutencao = km_real * modal.manutencao_km
    
    tempo_paradas_h = (qtd_pedidos * TEMPO_PARADA_MINUTOS) / 60.0
    tempo_total_h = tempo_transito_h + tempo_paradas_h
    mao_obra = tempo_total_h * CUSTO_HOMEM_HORA
    
    custo_total = combustivel + manutencao + mao_obra
    
    return {
        "km_total": round(km_real, 1),
        "tempo_horas_decimal": round(tempo_total_h, 2),
        "tempo_formatado": formatar_tempo(tempo_total_h),
        "custo_combustivel": round(combustivel, 2),
        "custo_manutencao": round(manutencao, 2),
        "custo_mao_obra": round(mao_obra, 2),
        "custo_total": round(custo_total, 2),
        "custo_por_pedido": round(custo_total / qtd_pedidos, 2) if qtd_pedidos > 0 else 0.0
    }