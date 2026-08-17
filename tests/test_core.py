import pytest
from logistica.validation import sanitizar_cep
from logistica.costs import formatar_tempo, calcular_custo_operacional
from logistica.routing import calcular_distancia_euclidiana

def test_sanitizar_cep():
    assert sanitizar_cep("04534-000") == "04534000"
    assert sanitizar_cep("04534000") == "04534000"
    assert sanitizar_cep("4534-000") == "04534000"
    assert sanitizar_cep("04.534-000") == "04534000"
    assert sanitizar_cep(None) == ""

def test_formatar_tempo():
    assert formatar_tempo(1.8) == "1 hora e 48 min"
    assert formatar_tempo(2.0) == "2 horas"
    assert formatar_tempo(0.5) == "30 min"

def test_calcular_distancia_euclidiana():
    p1 = (-23.5505, -46.6333)
    p2 = (-23.5505, -46.6333)
    assert calcular_distancia_euclidiana(p1, p2) == 0.0

def test_calcular_custo_operacional():
    res = calcular_custo_operacional(km_real=20.0, tempo_transito_h=1.0, qtd_pedidos=2, nome_modal="Carro de Passeio")
    assert res["km_total"] == 20.0
    assert res["custo_total"] > 0
    assert res["custo_por_pedido"] == round(res["custo_total"] / 2, 2)