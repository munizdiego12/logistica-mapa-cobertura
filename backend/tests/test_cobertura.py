import re
from pathlib import Path

from backend import cobertura
from backend.cobertura import (
    PARCIAL,
    TOTAL,
    caixa_do_raio,
    classificar_cobertura,
    combinar_cobertura,
    formatar_titulo,
    montar_ponto_prefixo,
    resumir_cobertura,
)

RAIZ = Path(__file__).resolve().parents[2]


def _prefixo(**kw):
    base = {
        "prefixo": "70254", "uf": "DF", "cod_municipio": 5300108, "cidade": "Brasília",
        "localidade": "ASA SUL", "localidade_pct": 100.0, "lat": -15.8198, "lon": -47.9012,
        "n_enderecos": 398, "dispersao_km": 0.14, "distancia_km": 3.0,
    }
    base.update(kw)
    return base


def _faixa(**kw):
    base = {
        "ibge": 5212501, "uf": "GO", "cidade": "Luziânia", "bairro": "Entorno DF",
        "cep_inicial": "72800000", "cep_final": "72899999", "faixa_completa": "72800-000 a 72899-999",
        "distancia_km": 25.0, "dias_sla": 2, "lat": -16.25, "lon": -47.95,
    }
    base.update(kw)
    return base


def test_classificacao_total_e_parcial_nas_fronteiras():
    assert classificar_cobertura(10.0, 5.0, 30.0) == TOTAL
    assert classificar_cobertura(25.0, 5.0, 30.0) == TOTAL  # distância + dispersão == raio ainda é Total
    assert classificar_cobertura(25.01, 5.0, 30.0) == PARCIAL
    assert classificar_cobertura(29.9, 0.0, 30.0) == TOTAL
    assert classificar_cobertura(20.0, 98.3, 30.0) == PARCIAL  # prefixo rural gigante


def test_titulo_com_preposicoes_em_minusculas_e_romanos_mantidos():
    assert formatar_titulo("ZONA CIVICO ADMINISTRATIVA") == "Zona Civico Administrativa"
    assert formatar_titulo("SETOR HABITACIONAL MESTRE D ARMAS") == "Setor Habitacional Mestre D Armas"
    assert formatar_titulo("JARDIM DAS FLORES") == "Jardim das Flores"
    assert formatar_titulo("VILA DO SOL E MAR") == "Vila do Sol e Mar"
    assert formatar_titulo("DE LOURDES") == "De Lourdes"  # a primeira palavra sempre começa em maiúscula
    assert formatar_titulo("CONJUNTO HABITACIONAL II") == "Conjunto Habitacional II"
    assert formatar_titulo("QUADRA 12 BLOCO A") == "Quadra 12 Bloco A"
    assert formatar_titulo("SAO-JOAO") == "Sao-Joao"
    assert formatar_titulo(None) == "" and formatar_titulo("  ") == ""


def test_caixa_do_raio_contem_o_circulo():
    lat_min, lat_max, lon_min, lon_max = caixa_do_raio(-15.79, -47.88, 30.0)
    assert lat_min < -15.79 - 0.26 and lat_max > -15.79 + 0.26  # 30 km ~ 0,27 grau de latitude
    assert lon_min < -47.88 < lon_max
    assert round(lat_max - lat_min, 2) == round(2 * 30.0 / 111.32, 2)


def test_ponto_do_prefixo_tem_faixa_000_a_999_cobertura_e_prazo_de_12_km():
    ponto = montar_ponto_prefixo(_prefixo(distancia_km=3.0, dispersao_km=0.14), 30.0)
    assert (ponto["cep_inicial"], ponto["cep_final"]) == ("70254000", "70254999")
    assert ponto["faixa_completa"] == "70254-000 a 70254-999"
    assert ponto["bairro"] == "Asa Sul" and ponto["bairro_aproximado"] is False
    assert ponto["cidade"] == "Brasília" and ponto["ibge"] == 5300108
    assert ponto["cobertura"] == TOTAL and ponto["precisao"] == "prefixo" and ponto["dias_sla"] == 1
    assert montar_ponto_prefixo(_prefixo(distancia_km=12.0), 30.0)["dias_sla"] == 1
    assert montar_ponto_prefixo(_prefixo(distancia_km=12.01), 30.0)["dias_sla"] == 2


def test_bairro_aproximado_quando_a_localidade_nao_representa_o_prefixo():
    ponto = montar_ponto_prefixo(_prefixo(localidade="BOSQUE", localidade_pct=25.4), 30.0)
    assert ponto["bairro"] == "Bosque e outros" and ponto["bairro_aproximado"] is True
    sem_pct = montar_ponto_prefixo(_prefixo(localidade="BOSQUE", localidade_pct=None), 30.0)
    assert sem_pct["bairro_aproximado"] is True
    sem_nome = montar_ponto_prefixo(_prefixo(localidade=None, localidade_pct=None), 30.0)
    assert sem_nome["bairro"] == "" and sem_nome["bairro_aproximado"] is False


def test_faixas_de_uf_com_prefixos_sao_descartadas_e_de_uf_sem_prefixos_entram_como_parcial():
    prefixos = [_prefixo(distancia_km=3.0), _prefixo(prefixo="72019", distancia_km=20.0, dispersao_km=15.0)]
    faixas = [
        _faixa(uf="DF", cidade="Brasília", distancia_km=1.0),  # DF já tem prefixos: descartada
        _faixa(uf="GO", distancia_km=25.0),                    # GO não tem: entra
    ]
    pontos = combinar_cobertura(prefixos, faixas, {"DF", "AC"}, 30.0)
    assert [p["distancia_km"] for p in pontos] == [3.0, 20.0, 25.0]  # ordenado por distância
    assert [p["cobertura"] for p in pontos] == [TOTAL, PARCIAL, PARCIAL]
    assert [p["precisao"] for p in pontos] == ["prefixo", "prefixo", "faixa"]
    assert not any(p["uf"] == "DF" and p["precisao"] == "faixa" for p in pontos)


def test_uf_sem_nenhum_prefixo_usa_so_as_faixas_e_todas_sao_parciais():
    faixas = [_faixa(uf="SP", cidade="São Paulo", distancia_km=d) for d in (1.0, 5.0)]
    pontos = combinar_cobertura([], faixas, {"AC", "DF"}, 30.0)
    assert len(pontos) == 2 and {p["cobertura"] for p in pontos} == {PARCIAL}
    assert resumir_cobertura(pontos) == {"total": 0, "parcial": 2, "usa_cnefe": False}


def test_regiao_sem_dados_devolve_lista_vazia():
    assert combinar_cobertura([], [], {"AC", "DF"}, 30.0) == []
    assert resumir_cobertura([]) == {"total": 0, "parcial": 0, "usa_cnefe": False}


def test_resumo_conta_total_parcial_e_detecta_uso_do_cnefe():
    pontos = combinar_cobertura(
        [_prefixo(distancia_km=3.0), _prefixo(prefixo="72019", distancia_km=29.0, dispersao_km=5.0)], [], {"DF"}, 30.0)
    assert resumir_cobertura(pontos) == {"total": 1, "parcial": 1, "usa_cnefe": True}


def test_legenda_e_atribuicao():
    assert cobertura.ATRIBUICAO_CNEFE == "Fonte: IBGE, CNEFE 2022"
    assert "\n" not in cobertura.LEGENDA_COBERTURA  # uma linha só
    assert "Total" in cobertura.LEGENDA_COBERTURA and "Parcial" in cobertura.LEGENDA_COBERTURA


def test_consulta_de_prefixos_filtra_por_caixa_e_nao_tem_comando_destrutivo():
    texto = (RAIZ / "backend" / "database.py").read_text(encoding="utf-8")
    inicio = texto.index("async def consultar_prefixos_por_raio")
    trecho = texto[inicio:texto.index("async def consultar_ceps_por_raio")]
    assert "BETWEEN $4 AND $5" in trecho and "BETWEEN $6 AND $7" in trecho
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\b", trecho, re.IGNORECASE)
