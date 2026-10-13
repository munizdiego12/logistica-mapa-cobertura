from typing import Optional, Dict, Any


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


def calcular_custo_rota(qtd_pedidos: int, custo_rota: Optional[float]) -> Dict[str, Any]:
    """
    Custo da rota = valor FIXO do tipo de veículo (ex.: carro de passeio R$ 130, Fiorino/Utilitário R$ 260),
    independente de km, tempo, combustível ou hora do motorista. Uma rota sem pedidos não custa nada.
    """
    valor = float(custo_rota or 0.0)
    if qtd_pedidos <= 0 or valor <= 0:
        return {"custo_total": 0.0, "custo_por_pedido": 0.0}
    return {
        "custo_total": round(valor, 2),
        "custo_por_pedido": round(valor / qtd_pedidos, 2),
    }
