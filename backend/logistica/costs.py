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


ORIGEM_INFORMADO = "informado"
ORIGEM_PADRAO = "padrão"


def calcular_custo_rota(qtd_pedidos: int, valor_base: Optional[float], valor_informado: Optional[float] = None) -> Dict[str, Any]:
    """
    Valor da rota: o valor INFORMADO pelo operador na roteirização, quando existir (zero vale se foi digitado de
    propósito); senão, o VALOR BASE do tipo de veículo (ex.: carro de passeio R$ 130, Fiorino/Utilitário R$ 260).
    Não depende de km, tempo, combustível nem hora do motorista. Uma rota sem pedidos não custa nada.
    Devolve também o valor usado por rota e a origem dele ("informado" ou "padrão").
    """
    informado = valor_informado is not None
    valor = float(valor_informado) if informado else float(valor_base or 0.0)
    resultado = {"valor_rota": round(valor, 2), "origem_valor": ORIGEM_INFORMADO if informado else ORIGEM_PADRAO}
    if qtd_pedidos <= 0 or valor <= 0:
        return {"custo_total": 0.0, "custo_por_pedido": 0.0, **resultado}
    return {
        "custo_total": round(valor, 2),
        "custo_por_pedido": round(valor / qtd_pedidos, 2),
        **resultado,
    }
