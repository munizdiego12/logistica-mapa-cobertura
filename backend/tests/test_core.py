from backend.logistica.validation import sanitizar_cep
from backend.logistica.costs import formatar_tempo, calcular_custo_rota
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

def test_valor_da_rota_sem_valor_informado_e_o_valor_base_do_tipo_de_veiculo():
    # Valor base: carro de passeio R$ 130 e Fiorino/Utilitário R$ 260 por rota, qualquer que seja o tamanho da rota.
    assert calcular_custo_rota(4, 130.0) == {"custo_total": 130.0, "custo_por_pedido": 32.5, "valor_rota": 130.0, "origem_valor": "padrão"}
    assert calcular_custo_rota(10, 260.0) == {"custo_total": 260.0, "custo_por_pedido": 26.0, "valor_rota": 260.0, "origem_valor": "padrão"}
    assert calcular_custo_rota(1, 130.0)["custo_total"] == calcular_custo_rota(40, 130.0)["custo_total"] == 130.0


def test_valor_informado_vale_no_lugar_do_valor_base():
    res = calcular_custo_rota(4, 260.0, 300.0)
    assert res == {"custo_total": 300.0, "custo_por_pedido": 75.0, "valor_rota": 300.0, "origem_valor": "informado"}


def test_valor_zero_informado_de_proposito_vale_e_e_diferente_de_nao_informar():
    zero = calcular_custo_rota(4, 260.0, 0.0)
    assert zero["custo_total"] == 0.0 and zero["valor_rota"] == 0.0 and zero["origem_valor"] == "informado"
    assert calcular_custo_rota(4, 260.0, None)["custo_total"] == 260.0


def test_custo_da_rota_nao_depende_de_combustivel_nem_de_hora_do_motorista():
    import inspect
    assert list(inspect.signature(calcular_custo_rota).parameters) == ["qtd_pedidos", "valor_base", "valor_informado"]


def test_custo_da_rota_sem_pedidos_ou_sem_valor_e_zero():
    assert calcular_custo_rota(0, 130.0)["custo_total"] == 0.0
    assert calcular_custo_rota(3, None)["custo_total"] == 0.0
    assert calcular_custo_rota(3, 0)["custo_por_pedido"] == 0.0


def test_custo_da_rota_arredonda_o_valor_por_pedido():
    assert calcular_custo_rota(3, 130.0)["custo_por_pedido"] == 43.33
