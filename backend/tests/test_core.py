from backend.logistica.validation import sanitizar_cep
from backend.logistica.costs import formatar_tempo, calculate_route_costs
from backend.logistica.routing import calcular_distancia_euclidiana

def test_sanitizar_cep():
    assert sanitizar_cep("04534-000") == "04534000"
    assert sanitizar_cep("04534000") == "04534000"
    assert sanitizar_cep("4534-000") == "04534000"
    assert sanitizar_cep(None) == ""

def test_formatar_tempo():
    assert formatar_tempo(1.8) == "1 hora e 48 min"
    assert formatar_tempo(2.0) == "2 horas"
    assert formatar_tempo(0.5) == "30 min"

def test_calcular_distancia_euclidiana():
    p1 = (-23.5505, -46.6333)
    p2 = (-23.5505, -46.6333)
    assert calcular_distancia_euclidiana(p1, p2) == 0.0

def test_calculate_route_costs_parametros_dinamicos():
    rota = [{"lat": -23.56, "lon": -46.64}]
    hub = [-23.5505, -46.6333]
    # Custo padrão
    res_padrao = calculate_route_costs(rota, hub, preco_gasolina=5.00, custo_hora=20.00)
    # Gasolina mais cara
    res_gasolina_cara = calculate_route_costs(rota, hub, preco_gasolina=10.00, custo_hora=20.00)
    # Hora do motorista mais cara
    res_hora_cara = calculate_route_costs(rota, hub, preco_gasolina=5.00, custo_hora=40.00)

    assert res_gasolina_cara["custo_combustivel"] > res_padrao["custo_combustivel"]
    assert res_gasolina_cara["custo_total"] > res_padrao["custo_total"]
    assert res_hora_cara["custo_mao_obra"] > res_padrao["custo_mao_obra"]
    assert res_hora_cara["custo_combustivel"] == res_padrao["custo_combustivel"]

def test_calculate_route_costs_rota_vazia():
    res = calculate_route_costs([], [-23.5505, -46.6333])
    assert res["custo_total"] == 0.0
    assert res["km_total"] == 0.0
    assert res["tempo_formatado"] == "0 min"
