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


ORIGEM_INFORMADO = "informado"  # digitado na roteirização, para o tipo de veículo (nesta execução)
ORIGEM_MOTORISTA = "motorista"  # valor próprio do motorista
ORIGEM_PADRAO = "padrão"  # valor base do tipo de veículo


def calcular_custo_rota(
    qtd_pedidos: int,
    valor_base: Optional[float],
    valor_informado: Optional[float] = None,
    valor_motorista: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Valor da rota, do mais específico ao mais geral:
      1) o valor INFORMADO pelo operador na roteirização para o tipo de veículo (nesta execução);
      2) o valor PRÓPRIO do motorista (cadastro);
      3) o VALOR BASE do tipo de veículo (ex.: carro de passeio R$ 130, Fiorino/Utilitário R$ 260).
    Zero vale quando foi digitado/cadastrado de propósito (só None significa "não informado").
    Não depende de km, tempo, combustível nem hora do motorista. Uma rota sem pedidos não custa nada.
    Devolve também o valor usado por rota e a origem dele ("informado", "motorista" ou "padrão").
    """
    if valor_informado is not None:
        valor, origem = float(valor_informado), ORIGEM_INFORMADO
    elif valor_motorista is not None:
        valor, origem = float(valor_motorista), ORIGEM_MOTORISTA
    else:
        valor, origem = float(valor_base or 0.0), ORIGEM_PADRAO
    resultado = {"valor_rota": round(valor, 2), "origem_valor": origem}
    if qtd_pedidos <= 0 or valor <= 0:
        return {"custo_total": 0.0, "custo_por_pedido": 0.0, **resultado}
    return {
        "custo_total": round(valor, 2),
        "custo_por_pedido": round(valor / qtd_pedidos, 2),
        **resultado,
    }
