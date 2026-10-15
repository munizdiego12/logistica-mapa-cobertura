"""Etapa 5b: rotas realizadas (confirmar, desfazer, contagem do dia em Brasília) e escolha dos motoristas da roteirização."""
import asyncio
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import frota
import main
import rotas_realizadas as rr
from backend.tests.fakes_asyncpg import FakeConn, FakePool, criar_banco_sqlite

UTC = timezone.utc
BRT = timezone(timedelta(hours=-3))
HOJE = date(2026, 10, 15)
OPERADOR = "Maria Souza (maria@zubale.com)"


def _rodar(corotina):
    return asyncio.run(corotina)


def _rotas(motoristas):
    """Uma rota por item: [(numero, motorista_id)]."""
    return [{"numero_rota": n, "motorista_id": m, "qtd_pedidos": 3, "distancia_km": 12.345} for n, m in motoristas]


@pytest.fixture
def banco():
    conn = criar_banco_sqlite()
    conn.joao = conn.inserir_motorista("João", "Fiorino/Utilitário")
    conn.ana = conn.inserir_motorista("Ana", "Carro de passeio")
    conn.inativo = conn.inserir_motorista("Pedro", "Carro de passeio", ativo=False)
    return conn


# ----------------------------------------------------------------------------------------------------------
# Dia no fuso de Brasília
# ----------------------------------------------------------------------------------------------------------
def test_dia_de_brasilia_as_23h_ainda_e_o_mesmo_dia_mesmo_sendo_o_dia_seguinte_em_utc():
    as_23h30 = datetime(2026, 10, 15, 23, 30, tzinfo=BRT)
    assert as_23h30.astimezone(UTC).date() == date(2026, 10, 16)  # em UTC já virou o dia
    assert rr.hoje_em_brasilia(as_23h30) == date(2026, 10, 15)
    assert rr.hoje_em_brasilia(datetime(2026, 10, 16, 2, 30, tzinfo=UTC)) == date(2026, 10, 15)  # 23h30 de Brasília
    assert rr.hoje_em_brasilia(datetime(2026, 10, 16, 2, 59, tzinfo=UTC)) == date(2026, 10, 15)  # 23h59
    assert rr.hoje_em_brasilia(datetime(2026, 10, 16, 3, 0, tzinfo=UTC)) == date(2026, 10, 16)  # meia-noite em Brasília
    assert rr.hoje_em_brasilia(datetime(2026, 10, 16, 0, 5, tzinfo=BRT)) == date(2026, 10, 16)
    assert rr.hoje_em_brasilia(datetime(2026, 10, 15, 3, 0, tzinfo=UTC)) == date(2026, 10, 15)
    assert rr.hoje_em_brasilia(datetime(2026, 10, 15, 2, 59, tzinfo=UTC)) == date(2026, 10, 14)  # ainda ontem em Brasília
    assert rr.hoje_em_brasilia(datetime(2026, 10, 16, 2, 30)) == date(2026, 10, 15)  # sem fuso: trata como UTC


def test_hoje_sem_argumento_usa_o_relogio_e_devolve_uma_data():
    assert isinstance(rr.hoje_em_brasilia(), date)


def test_contagem_do_dia_as_23h_cai_no_dia_de_brasilia(banco):
    dia = rr.hoje_em_brasilia(datetime(2026, 10, 16, 2, 30, tzinfo=UTC))  # 23h30 de 15/10 em Brasília
    _rodar(rr.confirmar(banco, "exec-23h", _rotas([(1, banco.joao)]), dia, "Av Paulista, 1", None, OPERADOR))
    assert _rodar(rr.contagem_do_dia(banco, date(2026, 10, 15))) == {banco.joao: 1}
    assert _rodar(rr.contagem_do_dia(banco, date(2026, 10, 16))) == {}  # o dia UTC seguinte não conta


def test_contagem_e_por_dia(banco):
    _rodar(rr.confirmar(banco, "ontem", _rotas([(1, banco.joao), (2, banco.joao)]), date(2026, 10, 14), None, None, OPERADOR))
    _rodar(rr.confirmar(banco, "hoje", _rotas([(1, banco.joao)]), HOJE, None, None, OPERADOR))
    assert _rodar(rr.contagem_do_dia(banco, date(2026, 10, 14))) == {banco.joao: 2}
    assert _rodar(rr.contagem_do_dia(banco, HOJE)) == {banco.joao: 1}


# ----------------------------------------------------------------------------------------------------------
# Só confirmadas contam, repetir não duplica, desfazer não apaga
# ----------------------------------------------------------------------------------------------------------
def test_confirmar_grava_uma_rota_por_viagem_com_o_motorista_de_cada_uma(banco):
    r = _rodar(rr.confirmar(banco, "e1", _rotas([(1, banco.joao), (2, banco.ana), (3, banco.joao)]), HOJE, "Av Paulista, 1 - Bela Vista", "manha", OPERADOR))
    assert r["novas"] == 3 and r["ja_confirmada"] is False
    linhas = banco.db.execute("SELECT numero_rota, motorista_id, data, loja_hub, turno, qtd_pedidos, distancia_km, status, criado_por FROM rotas_realizadas ORDER BY numero_rota").fetchall()
    assert [tuple(l) for l in linhas] == [
        (1, banco.joao, "2026-10-15", "Av Paulista, 1 - Bela Vista", "manha", 3, 12.35, "confirmada", OPERADOR),
        (2, banco.ana, "2026-10-15", "Av Paulista, 1 - Bela Vista", "manha", 3, 12.35, "confirmada", OPERADOR),
        (3, banco.joao, "2026-10-15", "Av Paulista, 1 - Bela Vista", "manha", 3, 12.35, "confirmada", OPERADOR),
    ]
    assert _rodar(rr.contagem_do_dia(banco, HOJE)) == {banco.joao: 2, banco.ana: 1}


def test_resumo_diz_quantas_rotas_o_motorista_ganhou_e_o_total_do_dia(banco):
    _rodar(rr.confirmar(banco, "antes", _rotas([(1, banco.joao)]), HOJE, None, None, OPERADOR))
    r = _rodar(rr.confirmar(banco, "agora", _rotas([(1, banco.joao), (2, banco.joao), (3, banco.ana)]), HOJE, None, None, OPERADOR))
    por_nome = {m["nome"]: m for m in r["motoristas"]}
    assert (por_nome["João"]["nesta_execucao"], por_nome["João"]["total_hoje"]) == (2, 3)  # "João: +2 rotas (total hoje: 3)"
    assert (por_nome["Ana"]["nesta_execucao"], por_nome["Ana"]["total_hoje"]) == (1, 1)
    assert [m["nome"] for m in r["motoristas"]] == ["Ana", "João"]


def test_confirmar_o_mesmo_resultado_duas_vezes_nao_duplica(banco):
    rotas = _rotas([(1, banco.joao), (2, banco.ana)])
    primeira = _rodar(rr.confirmar(banco, "e1", rotas, HOJE, None, None, OPERADOR))
    segunda = _rodar(rr.confirmar(banco, "e1", rotas, HOJE, None, None, OPERADOR))
    assert primeira["novas"] == 2 and segunda["novas"] == 0 and segunda["ja_confirmada"] is True
    assert banco.db.execute("SELECT count(*) FROM rotas_realizadas").fetchone()[0] == 2
    assert _rodar(rr.contagem_do_dia(banco, HOJE)) == {banco.joao: 1, banco.ana: 1}
    assert {m["nome"]: m["total_hoje"] for m in segunda["motoristas"]} == {"João": 1, "Ana": 1}


def test_confirmacao_repetida_com_rota_a_mais_so_grava_a_nova(banco):
    _rodar(rr.confirmar(banco, "e1", _rotas([(1, banco.joao)]), HOJE, None, None, OPERADOR))
    r = _rodar(rr.confirmar(banco, "e1", _rotas([(1, banco.joao), (2, banco.joao)]), HOJE, None, None, OPERADOR))
    assert r["novas"] == 1 and banco.db.execute("SELECT count(*) FROM rotas_realizadas").fetchone()[0] == 2


def test_desfazer_marca_como_cancelada_sem_apagar_e_sai_da_contagem(banco):
    _rodar(rr.confirmar(banco, "e1", _rotas([(1, banco.joao), (2, banco.joao)]), HOJE, None, None, OPERADOR))
    _rodar(rr.confirmar(banco, "e2", _rotas([(1, banco.joao)]), HOJE, None, None, OPERADOR))
    assert _rodar(rr.contagem_do_dia(banco, HOJE)) == {banco.joao: 3}
    r = _rodar(rr.desfazer(banco, "e1", HOJE))
    assert r["canceladas"] == 2 and r["confirmada"] is False
    assert banco.db.execute("SELECT count(*) FROM rotas_realizadas").fetchone()[0] == 3  # nada foi apagado
    assert [l[0] for l in banco.db.execute("SELECT status FROM rotas_realizadas WHERE execucao_id = 'e1'")] == ["cancelada", "cancelada"]
    assert _rodar(rr.contagem_do_dia(banco, HOJE)) == {banco.joao: 1}  # só a execução e2
    assert {m["nome"]: (m["nesta_execucao"], m["total_hoje"]) for m in r["motoristas"]} == {"João": (0, 1)}


def test_rotas_nao_confirmadas_ou_canceladas_nao_entram_na_contagem(banco):
    banco.db.execute("INSERT INTO rotas_realizadas (execucao_id, numero_rota, motorista_id, data, status) VALUES ('x', 1, ?, '2026-10-15', 'cancelada')", (banco.ana,))
    assert _rodar(rr.contagem_do_dia(banco, HOJE)) == {}
    _rodar(rr.confirmar(banco, "y", _rotas([(1, banco.ana)]), HOJE, None, None, OPERADOR))
    assert _rodar(rr.contagem_do_dia(banco, HOJE)) == {banco.ana: 1}


def test_desfazer_sem_nada_confirmado_avisa_e_confirmar_de_novo_volta_a_contar(banco):
    with pytest.raises(ValueError) as erro:
        _rodar(rr.desfazer(banco, "nunca-confirmada", HOJE))
    assert str(erro.value) == rr.MSG_NAO_CONFIRMADA
    _rodar(rr.confirmar(banco, "e1", _rotas([(1, banco.joao)]), HOJE, None, None, OPERADOR))
    _rodar(rr.desfazer(banco, "e1", HOJE))
    with pytest.raises(ValueError):
        _rodar(rr.desfazer(banco, "e1", HOJE))  # já estava cancelada
    r = _rodar(rr.confirmar(banco, "e1", _rotas([(1, banco.joao)]), HOJE, None, None, OPERADOR))
    assert r["novas"] == 1 and r["ja_confirmada"] is False  # confirmar de novo depois de desfazer volta a valer
    assert _rodar(rr.contagem_do_dia(banco, HOJE)) == {banco.joao: 1}
    assert banco.db.execute("SELECT count(*) FROM rotas_realizadas").fetchone()[0] == 1


def test_confirmar_sem_rotas_e_recusado_e_motorista_inexistente_nao_grava_nada(banco):
    with pytest.raises(ValueError) as erro:
        _rodar(rr.confirmar(banco, "e1", [], HOJE, None, None, OPERADOR))
    assert str(erro.value) == rr.MSG_SEM_ROTAS
    with pytest.raises(sqlite3.IntegrityError):  # a chave estrangeira com motoristas vale
        _rodar(rr.confirmar(banco, "e2", _rotas([(1, banco.joao), (2, 9999)]), HOJE, None, None, OPERADOR))
    assert banco.db.execute("SELECT count(*) FROM rotas_realizadas").fetchone()[0] == 0  # a transação foi desfeita inteira


def test_status_so_aceita_confirmada_ou_cancelada(banco):
    with pytest.raises(sqlite3.IntegrityError):
        banco.db.execute("INSERT INTO rotas_realizadas (execucao_id, numero_rota, motorista_id, data, status) VALUES ('z', 1, ?, '2026-10-15', 'talvez')", (banco.joao,))


# ----------------------------------------------------------------------------------------------------------
# Escolha dos motoristas
# ----------------------------------------------------------------------------------------------------------
def test_selecao_devolve_os_marcados_na_ordem_sem_repetir(banco):
    escolhidos = _rodar(frota.selecionar_motoristas(banco, [banco.ana, str(banco.joao), banco.ana]))
    assert [(m["id"], m["nome"], m["tipo_veiculo"], m["custo_rota"]) for m in escolhidos] == [
        (banco.ana, "Ana", "Carro de passeio", 130.0), (banco.joao, "João", "Fiorino/Utilitário", 260.0)]


def test_selecao_recusa_motorista_inativo_com_o_nome_e_orientacao(banco):
    with pytest.raises(ValueError) as erro:
        _rodar(frota.selecionar_motoristas(banco, [banco.joao, banco.inativo]))
    assert "Pedro está desativado" in str(erro.value) and "tela" in str(erro.value)


@pytest.mark.parametrize("ids", [[9999], ["abc"], [1.5], [True], [None]])
def test_selecao_recusa_motorista_inexistente_ou_id_invalido(banco, ids):
    with pytest.raises(ValueError) as erro:
        _rodar(frota.selecionar_motoristas(banco, ids))
    assert str(erro.value) == frota.MSG_MOTORISTA_INEXISTENTE


@pytest.mark.parametrize("ids", [None, [], ()])
def test_selecao_sem_nenhum_motorista_marcado(banco, ids):
    with pytest.raises(ValueError) as erro:
        _rodar(frota.selecionar_motoristas(banco, ids))
    assert str(erro.value) == frota.MSG_ESCOLHA_UM_MOTORISTA


def test_mensagens_da_selecao_sem_termo_tecnico(banco):
    textos = [frota.MSG_ESCOLHA_UM_MOTORISTA, frota.MSG_MOTORISTA_INEXISTENTE, rr.MSG_SEM_ROTAS, rr.MSG_NAO_CONFIRMADA]
    try:
        _rodar(frota.selecionar_motoristas(banco, [banco.inativo]))
    except ValueError as erro:
        textos.append(str(erro))
    assert not any(re.search(r"sql|tabela|banco|api|json|token|null|id \d|asyncpg", t, re.IGNORECASE) for t in textos), textos


# ----------------------------------------------------------------------------------------------------------
# Rotas HTTP (SQL de verdade em SQLite)
# ----------------------------------------------------------------------------------------------------------
class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


@pytest.fixture
def api(monkeypatch, banco):
    async def get_pool():
        return FakePool(banco)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), banco
    main.app.dependency_overrides.clear()
    main.JOBS.pop("exec-api", None)


def _job_concluido(banco, execucao_id="exec-api", motoristas=None):
    motoristas = motoristas or [banco.joao, banco.ana, banco.joao]
    main.JOBS[execucao_id] = {"status": "concluido", "etapa": "", "atual": 1, "total": 1, "erro": None, "resultado": {
        "execucao_id": execucao_id, "loja_hub": "Av Paulista, 1",
        "rotas": [{"id": i + 1, "motorista_id": m, "qtd_pedidos": 4, "km_total": 10.5} for i, m in enumerate(motoristas)]}}


def test_api_confirmar_mostra_o_ganho_e_o_total_do_dia(api):
    cliente, banco = api
    _job_concluido(banco)
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "exec-api"})
    assert r.status_code == 200 and r.json()["novas"] == 3
    por_nome = {m["nome"]: m for m in r.json()["motoristas"]}
    assert (por_nome["João"]["nesta_execucao"], por_nome["João"]["total_hoje"]) == (2, 2)
    hoje = cliente.get("/api/rotas-realizadas/hoje").json()
    assert hoje["data"] == rr.hoje_em_brasilia().isoformat()
    assert hoje["por_motorista"] == {str(banco.joao): 2, str(banco.ana): 1}


def test_api_confirmar_duas_vezes_nao_duplica_e_desfazer_tira_da_contagem(api):
    cliente, banco = api
    _job_concluido(banco)
    cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "exec-api"})
    segunda = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "exec-api"}).json()
    assert segunda["ja_confirmada"] is True and segunda["novas"] == 0
    assert banco.db.execute("SELECT count(*) FROM rotas_realizadas").fetchone()[0] == 3
    d = cliente.post("/api/rotas-realizadas/exec-api/desfazer")
    assert d.status_code == 200 and d.json()["canceladas"] == 3
    assert cliente.get("/api/rotas-realizadas/hoje").json()["por_motorista"] == {}
    assert banco.db.execute("SELECT count(*) FROM rotas_realizadas").fetchone()[0] == 3
    assert cliente.post("/api/rotas-realizadas/exec-api/desfazer").status_code == 422  # já desfeita
    assert cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "exec-api"}).json()["novas"] == 3


def test_api_confirmar_resultado_que_nao_existe_mais_ou_nao_terminou(api):
    cliente, banco = api
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "nao-existe"})
    assert r.status_code == 404 and "Gere as rotas de novo" in r.json()["detail"]
    main.JOBS["exec-api"] = {"status": "em_andamento", "resultado": None}
    assert cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "exec-api"}).status_code == 404


def test_api_confirmar_ignora_rota_sem_motorista_e_recusa_se_nao_sobrar_nenhuma(api):
    cliente, banco = api
    main.JOBS["exec-api"] = {"status": "concluido", "erro": None, "resultado": {"loja_hub": "x", "rotas": [{"id": 1, "qtd_pedidos": 2, "km_total": 1}]}}
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "exec-api"})
    assert r.status_code == 422 and r.json()["detail"] == rr.MSG_SEM_ROTAS


@pytest.mark.parametrize("metodo, caminho, args", [
    ("get", "/api/rotas-realizadas/hoje", {}),
    ("post", "/api/rotas-realizadas/confirmar", {"json": {"execucao_id": "x"}}),
    ("post", "/api/rotas-realizadas/x/desfazer", {}),
])
def test_rotas_realizadas_exigem_login(metodo, caminho, args):
    main.app.dependency_overrides.clear()
    assert getattr(TestClient(main.app), metodo)(caminho, **args).status_code == 401


def test_api_otimizar_recusa_motorista_inativo_ou_inexistente_com_422(api, monkeypatch):
    cliente, banco = api
    criados = []
    monkeypatch.setattr(main, "_processar_otimizacao", lambda *a, **k: criados.append(a))
    base = {"origem_rua": "Av Paulista", "origem_num": "1", "pedidos": [{"id": 1}]}
    r = cliente.post("/api/otimizar", json={**base, "motorista_ids": [banco.joao, banco.inativo]})
    assert r.status_code == 422 and "Pedro está desativado" in r.json()["detail"]
    r = cliente.post("/api/otimizar", json={**base, "motorista_ids": [banco.joao, 9999]})
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_MOTORISTA_INEXISTENTE
    r = cliente.post("/api/otimizar", json={**base, "motorista_ids": ["abc"]})
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_MOTORISTA_INEXISTENTE
    assert criados == []


def test_api_otimizar_so_leva_os_motoristas_marcados(api, monkeypatch):
    cliente, banco = api
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None):
        capturado["frota"] = frota_usar

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    r = cliente.post("/api/otimizar", json={"origem_rua": "A", "origem_num": "1", "pedidos": [{"id": 1}], "motorista_ids": [banco.ana]})
    assert r.status_code == 200
    assert [(m.id, m.motorista, m.modal) for m in capturado["frota"]] == [(banco.ana, "Ana", "Carro de passeio")]  # João não foi marcado


# ----------------------------------------------------------------------------------------------------------
# Resultado da roteirização: motorista de cada rota, execução e motoristas realmente usados
# ----------------------------------------------------------------------------------------------------------
def _roteirizar(monkeypatch, frota_usar, capacidades):
    pedidos = [{"id": i, "Endereco": f"Rua {i}", "Numero": str(i), "Bairro": "Centro", "CEP": "01310100", "Volume": 1} for i in range(1, 9)]

    async def geocode_falso(client, *a, **k):
        return -23.5505, -46.6333, "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO"

    async def lote_falso(lista):
        return {main._chave_cache(p["Endereco"], numero=p["Numero"], bairro=p["Bairro"], cep=p["CEP"], cidade="", uf=""):
                (-23.55 - i * 0.001, -46.63, "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO") for i, p in enumerate(lista)}

    async def osrm_falso(client, pontos):
        return 12.0, 30, []

    monkeypatch.setattr(main, "geocode_async", geocode_falso)
    monkeypatch.setattr(main, "geocodificar_lote", lote_falso)
    monkeypatch.setattr(main, "get_osrm_route_async", osrm_falso)
    req = main.OtimizarRequest(origem_rua="Av Paulista", origem_num="1", origem_bairro="Bela Vista", pedidos=pedidos, modais_config=capacidades)
    main.JOBS["t5b"] = {"status": "em_andamento", "etapa": "", "atual": 0, "total": 1, "resultado": None, "erro": None}
    _rodar(main._processar_otimizacao("t5b", req, frota_usar, {}))
    job = main.JOBS.pop("t5b")
    assert job["status"] == "concluido", job["erro"]
    return job["resultado"]


def test_resultado_traz_o_motorista_de_cada_rota_a_execucao_e_os_motoristas_realmente_usados(monkeypatch):
    frota_usar = [main.MotoristaItem(id=7, motorista="João", modal="Carro de passeio", custo_rota=130.0),
                  main.MotoristaItem(id=8, motorista="Ana", modal="Fiorino/Utilitário", custo_rota=260.0),
                  main.MotoristaItem(id=9, motorista="Beto", modal="Carro de passeio", custo_rota=130.0)]
    # Só 8 pedidos com 4 por viagem: duas viagens bastam e o terceiro motorista não é usado.
    resultado = _roteirizar(monkeypatch, frota_usar, {"Carro de passeio": {"capacidade": 4}, "Fiorino/Utilitário": {"capacidade": 4}})
    assert resultado["execucao_id"] == "t5b"
    assert resultado["loja_hub"] == "Av Paulista, 1 - Bela Vista"
    assert all(r["motorista_id"] in (7, 8, 9) for r in resultado["rotas"])
    usados = {r["motorista_id"] for r in resultado["rotas"]}
    assert 9 not in usados and usados == {7, 8}
    assert resultado["kpis"]["total_motoristas"] == resultado["kpis"]["total_veiculos"] == 2
    assert resultado["kpis"]["total_rotas_viagens"] == len(resultado["rotas"]) == 2


def test_um_motorista_com_duas_viagens_conta_duas_rotas_e_um_motorista(monkeypatch):
    frota_usar = [main.MotoristaItem(id=7, motorista="João", modal="Carro de passeio", custo_rota=130.0)]
    resultado = _roteirizar(monkeypatch, frota_usar, {"Carro de passeio": {"capacidade": 4}})
    assert len(resultado["rotas"]) == 2 and {r["motorista_id"] for r in resultado["rotas"]} == {7}
    assert resultado["kpis"]["total_motoristas"] == 1 and resultado["kpis"]["total_rotas_viagens"] == 2
