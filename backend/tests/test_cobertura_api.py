"""Testes do endpoint de cobertura e da exportação XLSX, com o banco e o geocodificador simulados."""
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

import main
from cobertura import ATRIBUICAO_CNEFE, LEGENDA_COBERTURA

REQ = {"origem_rua": "SQS 108", "origem_num": "1", "origem_cep": "70347000", "raio_km": 30.0}


def _prefixo(prefixo, distancia, dispersao, uf="DF", localidade="ASA SUL", pct=100.0):
    return {
        "prefixo": prefixo, "uf": uf, "cod_municipio": 5300108, "cidade": "Brasília", "localidade": localidade,
        "localidade_pct": pct, "lat": -15.82, "lon": -47.90, "n_enderecos": 100,
        "dispersao_km": dispersao, "distancia_km": distancia,
    }


@pytest.fixture
def cliente(monkeypatch):
    async def geocode_falso(client, *args, **kwargs):
        return -15.8198, -47.9012, "Brasília", "DF", "70347000", "Asa Sul", "VALIDO"

    async def ibge_falso(uf, cidade):
        return 5300108

    monkeypatch.setattr(main, "geocode_async", geocode_falso)
    monkeypatch.setattr(main.database, "buscar_ibge_municipio", ibge_falso)
    return TestClient(main.app)


def _simular_banco(monkeypatch, prefixos):
    async def _prefixos(lat, lon, raio):
        return prefixos

    monkeypatch.setattr(main.database, "consultar_prefixos_por_raio", _prefixos)


def test_cobertura_vem_so_dos_prefixos_do_cnefe_com_total_parcial_legenda_e_fonte(cliente, monkeypatch):
    _simular_banco(monkeypatch, [
        _prefixo("72499", 20.0, 90.0, localidade="GAMA", pct=30.0),
        _prefixo("70254", 3.0, 0.14),
    ])
    r = cliente.post("/api/cobertura-ceps", json=REQ)
    assert r.status_code == 200
    d = r.json()
    assert d["hub"]["ibge"] == 5300108  # vem de ibge_municipios, não de valor fixo
    assert d["total_pontos"] == 2 and d["aviso"] is None
    assert [(p["uf"], p["cobertura"]) for p in d["pontos_cobertos"]] == [("DF", "Total"), ("DF", "Parcial")]  # por distância
    assert d["pontos_cobertos"][1]["bairro"] == "Gama e outros"  # localidade com só 30% do prefixo
    assert d["resumo_cobertura"] == {"total": 1, "parcial": 1}
    assert d["legenda_cobertura"] == LEGENDA_COBERTURA and d["fonte"] == ATRIBUICAO_CNEFE


def test_nao_consulta_mais_as_faixas_manuais(cliente, monkeypatch):
    _simular_banco(monkeypatch, [_prefixo("70254", 3.0, 0.14)])
    assert not hasattr(main.database, "consultar_ceps_por_raio")
    assert not hasattr(main.database, "ufs_com_prefixos")
    assert cliente.post("/api/cobertura-ceps", json=REQ).json()["total_pontos"] == 1


def test_hub_sem_nenhuma_cobertura_devolve_aviso_como_florianopolis(cliente, monkeypatch):
    _simular_banco(monkeypatch, [])
    d = cliente.post("/api/cobertura-ceps", json=REQ).json()
    assert d["total_pontos"] == 0 and d["pontos_cobertos"] == []
    assert d["aviso"] == (
        "Ainda não temos CEPs cadastrados para essa região. Confira o endereço da loja "
        "ou peça ao administrador do sistema para incluir a região."
    )
    assert d["resumo_cobertura"] == {"total": 0, "parcial": 0} and d["fonte"] is None


def test_falha_do_banco_vira_503_e_nao_o_aviso_de_sem_cobertura(cliente, monkeypatch):
    async def quebrado(*args):
        raise RuntimeError("banco de dados indisponível")

    monkeypatch.setattr(main.database, "consultar_prefixos_por_raio", quebrado)
    r = cliente.post("/api/cobertura-ceps", json=REQ)
    assert r.status_code == 503
    assert "cobertura de CEPs" in r.json()["detail"]


TERMOS_TECNICOS = (
    "ceps_reais", "cep_prefixos", "ibge_municipios", "scripts", ".py", ".csv", "tabela", "banco de dados",
    "BrasilAPI", "ViaCEP", "Nominatim", "API", "SQL", "carregar_", "DATABASE",
)


def test_mensagens_de_tela_da_cobertura_nao_citam_termos_tecnicos(cliente, monkeypatch):
    mensagens = []

    # 1) aviso de região sem cobertura
    _simular_banco(monkeypatch, [])
    mensagens.append(cliente.post("/api/cobertura-ceps", json=REQ).json()["aviso"])

    # 2) falha do banco (503)
    async def quebrado(*args):
        raise RuntimeError("banco de dados indisponível")

    monkeypatch.setattr(main.database, "consultar_prefixos_por_raio", quebrado)
    mensagens.append(cliente.post("/api/cobertura-ceps", json=REQ).json()["detail"])

    # 3) endereço da loja não encontrado (422)
    async def geocode_vazio(client, *args, **kwargs):
        return None, None, "", "", "", "", "ERRO_CEP_INVALIDO"

    monkeypatch.setattr(main, "geocode_async", geocode_vazio)
    r = cliente.post("/api/cobertura-ceps", json=REQ)
    assert r.status_code == 422
    mensagens.append(r.json()["detail"])

    assert all(mensagens) and len(mensagens) == 3
    for texto in mensagens:
        for termo in TERMOS_TECNICOS:
            assert termo.lower() not in texto.lower(), f"termo técnico '{termo}' em: {texto}"


def _ponto(cobertura, ibge=5300108, bairro="Asa Sul"):
    return {
        "ibge": ibge, "uf": "DF", "cidade": "Brasília", "bairro": bairro, "cep_inicial": "70254000",
        "cep_final": "70254999", "distancia_km": 3.0, "dias_sla": 1, "cobertura": cobertura,
    }


def _xlsx(cliente, pontos):
    r = cliente.post("/api/exportar-tabela-frete-xlsx", json={"hub": {"uf": "DF", "ibge": 5300108}, "pontos_cobertos": pontos})
    assert r.status_code == 200
    return openpyxl.load_workbook(io.BytesIO(r.content))


def test_xlsx_tem_coluna_cobertura_por_ultimo_mantem_parciais_e_aba_de_fonte(cliente):
    wb = _xlsx(cliente, [_ponto("Total"), _ponto("Parcial"), _ponto("Parcial")])
    assert wb.sheetnames == ["Prazos e preços", "TZR e TDE", "Cobertura e fonte"]
    ws = wb["Prazos e preços"]
    cabecalho = [c.value for c in ws[3]]
    assert cabecalho[-1] == "Cobertura" and cabecalho[0] == "Código IBGE" and cabecalho[-2] == "ICMS sobre o pedágio"
    linhas = [[c.value for c in row] for row in ws.iter_rows(min_row=4)]
    assert [l[-1] for l in linhas] == ["Total", "Parcial", "Parcial"]  # os parciais continuam na planilha
    assert all(len(l) == len(cabecalho) for l in linhas)  # nenhuma coluna do modelo deslocada
    assert linhas[0][0] == 5300108 and linhas[0][5] == "70254000" and linhas[0][7] == 1


def test_xlsx_legenda_de_uma_linha_com_a_nota_de_distancia_e_atribuicao_na_aba_extra(cliente):
    aba = _xlsx(cliente, [_ponto("Total")])["Cobertura e fonte"]
    assert aba["A1"].value == LEGENDA_COBERTURA
    assert "Raio X km" in aba["A1"].value and "em linha reta entre o hub e o centro do prefixo" in aba["A1"].value
    assert "não por estrada" in aba["A1"].value and "\n" not in aba["A1"].value
    assert aba["A2"].value == "Fonte: IBGE, CNEFE 2022"
    assert aba["A3"].value is None


def test_xlsx_sem_codigo_ibge_deixa_a_celula_vazia_em_vez_de_inventar(cliente):
    r = cliente.post(
        "/api/exportar-tabela-frete-xlsx",
        json={"hub": {"uf": "SC"}, "pontos_cobertos": [{**_ponto("Parcial"), "ibge": None}]},
    )
    ws = openpyxl.load_workbook(io.BytesIO(r.content))["Prazos e preços"]
    assert ws.cell(row=4, column=1).value is None
