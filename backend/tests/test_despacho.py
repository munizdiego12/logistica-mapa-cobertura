"""Etapa 10: matriz de despacho. Troca do motorista final de cada rota no "Confirmar rotas", validação, rotação como aviso e endpoint de rotação."""
import asyncio
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import main
import rotas_realizadas as rr
from backend.tests.fakes_asyncpg import FakePool, criar_banco_sqlite


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


@pytest.fixture
def api(monkeypatch):
    banco = criar_banco_sqlite()
    banco.ana = banco.inserir_motorista("Ana")
    banco.beto = banco.inserir_motorista("Beto", "Fiorino/Utilitário")
    banco.caio = banco.inserir_motorista("Caio")

    async def get_pool():
        return FakePool(banco)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), banco
    main.app.dependency_overrides.clear()
    for chave in [k for k in main.JOBS if k.startswith("desp-")]:
        main.JOBS.pop(chave)


def _parada(pid, ordem):
    return {"id": pid, "Endereco": f"Rua {pid}", "Numero": "10", "Bairro": "Centro", "Cidade": "Santos", "UF": "SP", "Volume": 1, "ordem": ordem}


def _job(chave, banco, turno="tarde"):
    """Resultado com 3 rotas sugeridas: 1 e 2 para a Ana, 3 para o Beto."""
    rotas = [
        {"id": 1, "motorista_id": banco.ana, "motorista_base": "Ana", "qtd_pedidos": 2, "km_total": 5, "setores": ["N"], "paradas": [_parada("P1", 1), _parada("P2", 2)]},
        {"id": 2, "motorista_id": banco.ana, "motorista_base": "Ana", "qtd_pedidos": 1, "km_total": 3, "setores": ["L", "SE"], "paradas": [_parada("P3", 1)]},
        {"id": 3, "motorista_id": banco.beto, "motorista_base": "Beto", "qtd_pedidos": 1, "km_total": 4, "setores": ["O"], "paradas": [_parada("P4", 1)]},
    ]
    main.JOBS[chave] = {"status": "concluido", "erro": None, "resultado": {"loja_hub": "Loja", "turno": turno, "rotas": rotas}}
    return chave


def _motoristas_gravados(banco, execucao):
    return {l[0]: l[1] for l in banco.db.execute("SELECT numero_rota, motorista_id FROM rotas_realizadas WHERE execucao_id = ? ORDER BY numero_rota", (execucao,))}


def _contagem(banco):
    return banco.db.execute("SELECT count(*) FROM rotas_realizadas").fetchone()[0]


def test_sem_atribuicoes_o_confirmar_continua_igual_ao_formato_antigo(api):
    cliente, banco = api
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-1", banco)})
    assert r.status_code == 200
    assert _motoristas_gravados(banco, "desp-1") == {1: banco.ana, 2: banco.ana, 3: banco.beto}
    corpo = r.json()
    assert corpo["confirmada"] is True and corpo["novas"] == 3 and corpo["ajustadas"] == 0 and corpo["avisos"] == []
    assert {m["nome"]: m["nesta_execucao"] for m in corpo["motoristas"]} == {"Ana": 2, "Beto": 1}


def test_confirmar_grava_o_motorista_ajustado_e_os_totais_refletem_isso(api):
    cliente, banco = api
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-2", banco), "atribuicoes": {"1": banco.caio, "3": banco.ana}})
    assert r.status_code == 200
    assert _motoristas_gravados(banco, "desp-2") == {1: banco.caio, 2: banco.ana, 3: banco.ana}
    corpo = r.json()
    assert corpo["ajustadas"] == 2
    totais = {m["nome"]: (m["nesta_execucao"], m["total_hoje"], m["pedidos_nesta_execucao"], m["pedidos_hoje"]) for m in corpo["motoristas"]}
    assert totais == {"Ana": (2, 2, 2, 2), "Caio": (1, 1, 2, 2)}  # Beto ficou sem rota: não entra
    assert "Beto" not in totais


def test_atribuir_o_mesmo_motorista_da_sugestao_nao_conta_como_ajuste(api):
    cliente, banco = api
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-3", banco), "atribuicoes": {"1": banco.ana}})
    assert r.status_code == 200 and r.json()["ajustadas"] == 0


def test_trocar_por_quem_ja_tem_outra_rota_nesta_roteirizacao_e_permitido(api):
    cliente, banco = api
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-4", banco), "atribuicoes": {"3": banco.ana}})
    assert r.status_code == 200
    assert list(_motoristas_gravados(banco, "desp-4").values()).count(banco.ana) == 3


@pytest.mark.parametrize("valor", ["inativo", 99999, "abc", None, 1.5, True])
def test_motorista_inativo_inexistente_ou_invalido_e_422_e_nada_e_gravado(api, valor):
    cliente, banco = api
    inativo = banco.inserir_motorista("Dani", ativo=False)
    final = inativo if valor == "inativo" else valor
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-5", banco), "atribuicoes": {"1": final}})
    assert r.status_code == 422
    assert r.json()["detail"] == "O motorista escolhido para uma das rotas não está mais ativo ou cadastrado. Atualize a lista e escolha de novo."
    assert _contagem(banco) == 0


@pytest.mark.parametrize("chave", ["99", "x", "", "1.5"])
def test_rota_inexistente_no_resultado_e_422(api, chave):
    cliente, banco = api
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-6", banco), "atribuicoes": {chave: banco.caio}})
    assert r.status_code == 422 and r.json()["detail"] == "Uma das rotas ajustadas não existe neste resultado. Gere as rotas de novo."
    assert _contagem(banco) == 0


def test_atribuicoes_com_formato_errado_e_422_em_linguagem_do_operador(api):
    cliente, banco = api
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-7", banco), "atribuicoes": {"1": [banco.caio]}})
    assert r.status_code == 422 and "motorista" in r.json()["detail"]
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "desp-7", "atribuicoes": ["1"]})
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    assert _contagem(banco) == 0


def test_resultado_que_sumiu_da_memoria_mantem_o_aviso_de_sempre(api):
    cliente, banco = api
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "desp-nao-existe", "atribuicoes": {"1": banco.caio}})
    assert r.status_code == 404 and r.json()["detail"] == "Este resultado não está mais disponível. Gere as rotas de novo."


def test_rotacao_violada_na_troca_e_so_aviso_e_a_confirmacao_acontece(api):
    cliente, banco = api
    dia = rr.hoje_em_brasilia()
    asyncio.run(rr.confirmar(banco, "manha-0", [{"numero_rota": 1, "motorista_id": banco.caio, "qtd_pedidos": 1, "distancia_km": 1, "setores": "N,O"}], dia, "Loja", "manha", "x"))
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-8", banco, turno="tarde"), "atribuicoes": {"1": banco.caio, "3": banco.caio}})
    assert r.status_code == 200
    assert r.json()["avisos"] == ["Rota 1: Caio já fez a região N em outro turno hoje.", "Rota 3: Caio já fez a região O em outro turno hoje."]
    assert _motoristas_gravados(banco, "desp-8") == {1: banco.caio, 2: banco.ana, 3: banco.caio}


def test_aviso_de_rotacao_com_varias_regioes_e_sem_repeticao():
    rotacao = {1: {"N": ["manha"], "NE": ["manha"], "L": ["noite"]}}
    rotas = [{"numero_rota": 2, "motorista_id": 1, "setores": "N,NE,L"}, {"numero_rota": 3, "motorista_id": 1, "setores": "S"}, {"numero_rota": 4, "motorista_id": 2, "setores": "N"}]
    assert rr.avisos_de_rotacao(rotas, rotacao, {1: "Ana", 2: "Beto"}) == ["Rota 2: Ana já fez as regiões N, NE e L em outro turno hoje."]


def test_desfazer_e_confirmar_de_novo_com_outro_motorista_grava_o_novo(api):
    cliente, banco = api
    execucao = _job("desp-9", banco)
    cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": execucao})
    d = cliente.post(f"/api/rotas-realizadas/{execucao}/desfazer")
    assert d.status_code == 200 and all(m["total_hoje"] == 0 for m in d.json()["motoristas"])
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": execucao, "atribuicoes": {"1": banco.caio}})
    assert r.status_code == 200 and r.json()["ajustadas"] == 1
    assert _motoristas_gravados(banco, execucao) == {1: banco.caio, 2: banco.ana, 3: banco.beto}
    assert _contagem(banco) == 3  # não duplicou
    assert {m["nome"]: m["total_hoje"] for m in r.json()["motoristas"]} == {"Ana": 1, "Beto": 1, "Caio": 1}
    # desfazer outra vez zera pelo motorista que foi gravado
    d2 = cliente.post(f"/api/rotas-realizadas/{execucao}/desfazer").json()
    assert {m["nome"]: m["total_hoje"] for m in d2["motoristas"]} == {"Ana": 0, "Beto": 0, "Caio": 0}


def test_confirmar_de_novo_uma_execucao_ja_confirmada_mantem_o_que_foi_gravado(api):
    cliente, banco = api
    execucao = _job("desp-10", banco)
    cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": execucao})
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": execucao, "atribuicoes": {"1": banco.caio}})
    assert r.status_code == 200 and r.json()["ja_confirmada"] is True and r.json()["ajustadas"] == 0
    assert _motoristas_gravados(banco, execucao)[1] == banco.ana


def test_o_historico_mostra_o_motorista_final(api):
    cliente, banco = api
    cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-11", banco), "atribuicoes": {"1": banco.caio}})
    rotas = cliente.get("/api/historico").json()["rotas"]
    assert {r["numero"]: r["motorista"]["nome"] for r in rotas} == {1: "Caio", 2: "Ana", 3: "Beto"}


# ----------------------------------------------------------------------------------------------------------
# GET /api/rotas-realizadas/rotacao
# ----------------------------------------------------------------------------------------------------------
def test_rotacao_devolve_so_confirmadas_de_outros_turnos_de_hoje(api):
    cliente, banco = api
    dia = rr.hoje_em_brasilia()
    conn = banco
    asyncio.run(rr.confirmar(conn, "r1", [{"numero_rota": 1, "motorista_id": banco.ana, "qtd_pedidos": 1, "distancia_km": 1, "setores": "N,NE"}], dia, "L", "manha", "x"))
    asyncio.run(rr.confirmar(conn, "r2", [{"numero_rota": 1, "motorista_id": banco.beto, "qtd_pedidos": 1, "distancia_km": 1, "setores": "S"}], dia, "L", "tarde", "x"))
    asyncio.run(rr.confirmar(conn, "r3", [{"numero_rota": 1, "motorista_id": banco.caio, "qtd_pedidos": 1, "distancia_km": 1, "setores": "O"}], dia - timedelta(days=1), "L", "manha", "x"))
    asyncio.run(rr.confirmar(conn, "r4", [{"numero_rota": 1, "motorista_id": banco.caio, "qtd_pedidos": 1, "distancia_km": 1, "setores": "L"}], dia, "L", "manha", "x"))
    asyncio.run(rr.desfazer(conn, "r4", dia))
    r = cliente.get("/api/rotas-realizadas/rotacao", params={"turno": "Tarde"})
    assert r.status_code == 200
    assert r.json() == {"data": dia.isoformat(), "turno": "tarde", "por_motorista": {str(banco.ana): {"N": ["manha"], "NE": ["manha"]}}}


@pytest.mark.parametrize("turno", [None, "", "madrugada"])
def test_rotacao_com_turno_invalido_e_422(api, turno):
    cliente, _ = api
    r = cliente.get("/api/rotas-realizadas/rotacao", params={} if turno is None else {"turno": turno})
    assert r.status_code == 422 and r.json()["detail"] == "Escolha o turno (manhã, tarde ou noite)."


def test_as_rotas_novas_exigem_login():
    main.app.dependency_overrides.clear()
    cliente = TestClient(main.app)
    assert cliente.get("/api/rotas-realizadas/rotacao", params={"turno": "manha"}).status_code == 401
    assert cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "x", "atribuicoes": {"1": 1}}).status_code == 401


# ----------------------------------------------------------------------------------------------------------
# Privacidade e compatibilidade
# ----------------------------------------------------------------------------------------------------------
def test_nada_de_pedido_telefone_ou_cliente_em_log_aviso_ou_resposta(api, caplog, capsys):
    cliente, banco = api
    banco.db.execute("UPDATE motoristas SET telefone = '11987654321' WHERE id = ?", (banco.caio,))
    caplog.set_level(logging.DEBUG)
    execucao = _job("desp-12", banco)
    main.JOBS[execucao]["resultado"]["rotas"][0]["paradas"][0].update({"Cliente": "Fulano Segredoso", "id": "ID-SECRETO-77", "Endereco": "Rua Sigilosa"})
    respostas = [
        cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": execucao, "atribuicoes": {"1": banco.caio}}),
        cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": execucao, "atribuicoes": {"1": 99999}}),
        cliente.get("/api/rotas-realizadas/rotacao", params={"turno": "tarde"}),
    ]
    texto = " ".join(r.text for r in respostas) + capsys.readouterr().out + caplog.text
    for segredo in ("ID-SECRETO-77", "Rua Sigilosa", "Fulano", "11987654321"):
        assert segredo not in texto


def test_falha_na_conferencia_de_rotacao_nao_derruba_a_confirmacao(api, monkeypatch, capsys):
    cliente, banco = api

    async def quebrada(*a, **k):
        raise RuntimeError("falha em Rua Secreta 10")

    monkeypatch.setattr(rr, "setores_do_dia", quebrada)
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": _job("desp-13", banco)})
    assert r.status_code == 200 and r.json()["avisos"] == []
    saida = capsys.readouterr().out
    assert "RuntimeError" in saida and "Rua Secreta" not in saida


def test_o_resultado_de_otimizar_nao_ganha_campos_novos_de_ajuste():
    import inspect
    fonte = inspect.getsource(main._processar_otimizacao)
    assert "atribuic" not in fonte and "ajustada" not in fonte
