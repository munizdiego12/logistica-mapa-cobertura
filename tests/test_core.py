import pytest
from logistica.validation import sanitizar_cep
from logistica.costs import formatar_tempo, calcular_custo_operacional
from logistica.routing import calcular_distancia_euclidiana
from logistica.mapping import construir_mapa

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

def test_calcular_custo_operacional_parametros_dinamicos():
    # Custo padrão
    res_padrao = calcular_custo_operacional(km_real=10.0, tempo_transito_h=1.0, qtd_pedidos=1, preco_gasolina=5.00, custo_hora=20.00)
    # Gasolina mais cara
    res_gasolina_cara = calcular_custo_operacional(km_real=10.0, tempo_transito_h=1.0, qtd_pedidos=1, preco_gasolina=10.00, custo_hora=20.00)
    
    assert res_gasolina_cara["custo_combustivel"] > res_padrao["custo_combustivel"]
    assert res_gasolina_cara["custo_total"] > res_padrao["custo_total"]

def test_seguranca_xss_no_mapa():
    origem = (-23.5505, -46.6333)
    pedidos_maliciosos = [[{
        "Cliente": "<script>alert('xss')</script>",
        "Logradouro": "<img src=x onerror=alert(1)>",
        "Numero": "100",
        "Bairro": "Centro",
        "lat": -23.5600,
        "lon": -46.6400
    }]]
    
    mapa = construir_mapa(origem, pedidos_maliciosos, "Carro de Passeio")
    mapa_html = mapa.get_root().render()
    
    # Garante que a tag crua <script> NUNCA seja injetada no HTML do mapa
    assert "<script>alert('xss')</script>" not in mapa_html
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in mapa_html