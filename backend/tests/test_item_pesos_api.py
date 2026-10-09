"""Rotas de pesos dos itens: exigem login, registram quem alterou e falham com mensagens claras."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import main
from backend.tests.fakes_asyncpg import FakeConn, FakePool


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


def _item(**kw):
    base = {"id_sku": "27439", "reference_code": "23290909", "nome": "Creme de Leite 200g", "peso_kg": Decimal("0.2000"),
            "fonte": "nome", "confianca": "alta", "unidades_vendidas": 2954, "atualizado_em": None, "atualizado_por": None}
    base.update(kw)
    return base


@pytest.fixture
def api(monkeypatch):
    conn = FakeConn()

    async def get_pool():
        return FakePool(conn)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), conn
    main.app.dependency_overrides.clear()


ROTAS = [
    ("get", "/api/item-pesos/resumo", None),
    ("get", "/api/item-pesos/fila-sem-peso", None),
    ("get", "/api/item-pesos", None),
    ("put", "/api/item-pesos/27439", {"peso_kg": 1}),
    ("post", "/api/item-pesos/skus-vistos", {"itens": [{"id_sku": "1"}]}),
]


@pytest.mark.parametrize("metodo, caminho, corpo", ROTAS)
def test_todas_as_rotas_de_pesos_exigem_operador_logado(metodo, caminho, corpo):
    main.app.dependency_overrides.clear()
    r = getattr(TestClient(main.app), metodo)(caminho, **({"json": corpo} if corpo else {}))
    assert r.status_code == 401


def test_resumo(api):
    cliente, conn = api
    conn.respostas = [{"total": 10, "com_peso": 6}]
    assert cliente.get("/api/item-pesos/resumo").json() == {"total": 10, "com_peso": 6, "sem_peso": 4}


def test_fila_sem_peso_vem_ordenada_pelos_mais_vendidos_e_pagina(api):
    cliente, conn = api
    conn.respostas = [[_item(id_sku="1", peso_kg=None, unidades_vendidas=300), _item(id_sku="2", peso_kg=None, unidades_vendidas=200),
                       _item(id_sku="3", peso_kg=None, unidades_vendidas=100)]]
    r = cliente.get("/api/item-pesos/fila-sem-peso?limite=2&deslocamento=4").json()
    _, sql, args = conn.chamadas[0]
    assert args == (None, None, True, 3, 4) and "ORDER BY unidades_vendidas DESC" in sql
    assert [i["id_sku"] for i in r["itens"]] == ["1", "2"] and r["tem_mais"] is True and r["itens"][0]["peso_kg"] is None


def test_listar_com_busca_escapa_curingas_e_limita(api):
    cliente, conn = api
    conn.respostas = [[_item()]]
    r = cliente.get("/api/item-pesos", params={"busca": "100%", "limite": 5000}).json()
    assert conn.chamadas[0][2] == ("100\\%", "100%", False, 201, 0) and r["limite"] == 200
    assert r["itens"][0]["peso_kg"] == 0.2 and r["tem_mais"] is False


def test_editar_peso_aceita_virgula_e_registra_quem_alterou(api):
    cliente, conn = api
    conn.respostas = [_item(peso_kg=Decimal("1.5000"), fonte="manual", confianca="media", atualizado_por="Maria Souza (maria@zubale.com)")]
    r = cliente.put("/api/item-pesos/27439", json={"peso_kg": "1,5", "confianca": "media"})
    assert r.status_code == 200
    assert conn.chamadas[0][2] == ("27439", Decimal("1.5000"), "manual", "media", "Maria Souza (maria@zubale.com)")
    assert r.json()["peso_kg"] == 1.5 and r.json()["atualizado_por"] == "Maria Souza (maria@zubale.com)"


def test_editar_peso_com_numero_e_confianca_padrao_alta(api):
    cliente, conn = api
    conn.respostas = [_item()]
    assert cliente.put("/api/item-pesos/1", json={"peso_kg": 0.045}).status_code == 200
    assert conn.chamadas[0][2][1:4] == (Decimal("0.0450"), "manual", "alta")


def test_tirar_o_peso_devolve_o_item_para_a_fila(api):
    cliente, conn = api
    conn.respostas = [_item(peso_kg=None, fonte=None, confianca=None)]
    assert cliente.put("/api/item-pesos/1", json={"peso_kg": None}).status_code == 200
    assert conn.chamadas[0][2][1:4] == (None, None, None)


@pytest.mark.parametrize("corpo", [
    {"peso_kg": 0}, {"peso_kg": -1}, {"peso_kg": "abc"}, {"peso_kg": 1001}, {"peso_kg": "0,00001"}, {"peso_kg": 1, "confianca": "talvez"},
])
def test_peso_invalido_vira_422_com_mensagem_e_nao_chega_ao_banco(api, corpo):
    cliente, conn = api
    r = cliente.put("/api/item-pesos/1", json=corpo)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str) and r.json()["detail"]
    assert conn.chamadas == []


def test_editar_item_que_nao_existe_da_404(api):
    cliente, conn = api
    conn.respostas = [None]
    r = cliente.put("/api/item-pesos/999", json={"peso_kg": 1})
    assert r.status_code == 404 and "não encontrado" in r.json()["detail"]


def test_skus_vistos_fazem_os_novos_entrarem_na_fila(api):
    cliente, conn = api
    conn.respostas = [[{"id_sku": "1"}]]
    r = cliente.post("/api/item-pesos/skus-vistos", json={"itens": [{"id_sku": "1", "quantidade": 2}, {"id_sku": "2", "quantidade": 7, "nome": "Novo"}]})
    assert r.status_code == 200 and r.json() == {"novos": 1, "ja_existiam": 1}
    linhas = [c for c in conn.chamadas if c[0] == "executemany"][0][2]
    assert sorted(linhas) == [("1", None, None, 2), ("2", None, "Novo", 7)]


def test_skus_vistos_recusa_quantidade_invalida(api):
    cliente, conn = api
    assert cliente.post("/api/item-pesos/skus-vistos", json={"itens": [{"id_sku": "1", "quantidade": 0}]}).status_code == 422
    assert cliente.post("/api/item-pesos/skus-vistos", json={"itens": [{"id_sku": "", "quantidade": 1}]}).status_code == 422


TERMOS_TECNICOS = ("item_pesos", "tabela", "SQL", "asyncpg", "banco de dados", "alembic", "Traceback", "Error", "conexão com")


def test_falhas_do_banco_viram_503_sem_termos_tecnicos(api, monkeypatch):
    cliente, conn = api
    conn.erro_no_fetch = RuntimeError('relation "item_pesos" does not exist')
    r1 = cliente.get("/api/item-pesos")

    async def sem_pool():
        return None

    monkeypatch.setattr(main.database, "get_pool", sem_pool)
    r2 = cliente.get("/api/item-pesos/resumo")
    for r in (r1, r2):
        assert r.status_code == 503
        texto = r.json()["detail"]
        assert "cadastro de pesos" in texto and "administrador do sistema" in texto
        assert not any(t.lower() in texto.lower() for t in TERMOS_TECNICOS), texto
        assert "does not exist" not in texto  # a mensagem do erro não vaza para a tela
