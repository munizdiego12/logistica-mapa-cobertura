"""Etapa 8b: quantas rotas cada motorista faz (equilíbrio por MOTORISTA, viagens personalizadas) e quantos pedidos cada motorista fez
(totais do dia, confirmação e desfazer). Sem migration."""
import asyncio
import re
from collections import Counter
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import matriz
import roteirizacao
import rotas_realizadas as rr
import setores
import solver
from backend.tests.fakes_asyncpg import FakePool, criar_banco_sqlite

pytest.importorskip("ortools")

HUB = (-23.5505, -46.6333)
CARRO = "Carro de passeio"
UTIL = "Fiorino/Utilitário"
OPERADOR = "Maria Souza (maria@zubale.com)"


def _rodar(corotina):
    return asyncio.run(corotina)


def _ponto(setor, km=4.0, jitter=0.0):
    import math
    graus = setores.SETORES.index(setor) * 45.0
    dlat = km / 111.195 * math.cos(math.radians(graus))
    dlon = km / (111.195 * math.cos(math.radians(HUB[0]))) * math.sin(math.radians(graus))
    return (HUB[0] + dlat + jitter, HUB[1] + dlon + jitter)


def _cluster(setor, n, km=4.0):
    return [_ponto(setor, km, jitter=i * 0.0004) for i in range(n)]


def _aleatorios(n, semente=4, raio=0.08):
    import random
    azar = random.Random(semente)
    return [(HUB[0] + azar.uniform(-raio, raio), HUB[1] + azar.uniform(-raio, raio)) for _ in range(n)]


def _resolver(pontos, motoristas, **kw):
    dist, dur = matriz.matriz_linha_reta([HUB] + pontos)
    sec = [setores.setor_do_pedido(*HUB, *p) for p in pontos]
    az = [setores.azimute(*HUB, *p) for p in pontos]
    kw.setdefault("limite_s", 1.5)
    return solver.resolver(dist, dur, sec, motoristas, azimutes=az, **kw)


def _por_motorista(r):
    saida = {}
    for rota in sorted(r.rotas, key=lambda x: (x.motorista_id, x.viagem_num)):
        saida.setdefault(rota.motorista_id, []).append(len(rota.pedidos))
    return saida


def _dois(viagens_a=None, viagens_b=None, tipos=(CARRO, CARRO), caps=(5, 5)):
    return [solver.MotoristaSolver(1, "Ana", tipos[0], caps[0], viagens_a), solver.MotoristaSolver(2, "Beto", tipos[1], caps[1], viagens_b)]


def _cobre_todos(r, n):
    assert sorted(p for x in r.rotas for p in x.pedidos) == list(range(n))


# ----------------------------------------------------------------------------------------------------------
# Os exemplos do operador: o equilíbrio é por MOTORISTA, o nº de viagens só divide a carga dele
# ----------------------------------------------------------------------------------------------------------
def test_exemplo_automatico_20_pedidos_2_motoristas_de_passeio_teto_5():
    r = _resolver(_aleatorios(20), _dois())
    assert _por_motorista(r) == {1: [5, 5], 2: [5, 5]}  # 10 pedidos por motorista, 2 viagens de 5 cada
    assert not any(x.personalizada for x in r.rotas)
    assert not [a for a in r.avisos if a["tipo"] in ("rota_personalizada", "viagens_solicitadas_a_menos")]
    _cobre_todos(r, 20)


def test_exemplo_a_escolhe_1_rota_fica_com_10_pedidos_e_b_continua_com_10_em_2_viagens():
    r = _resolver(_aleatorios(20), _dois(viagens_a=1))
    assert _por_motorista(r) == {1: [10], 2: [5, 5]}
    a = [x for x in r.rotas if x.motorista_id == 1][0]
    assert a.personalizada and a.viagens_solicitadas == 1 and a.teto_recomendado == 5
    assert not any(x.personalizada for x in r.rotas if x.motorista_id == 2)
    aviso = [a for a in r.avisos if a["tipo"] == "rota_personalizada"]
    assert len(aviso) == 1 and "Ana" in aviso[0]["mensagem"] and "10 pedidos em 1 viagem" in aviso[0]["mensagem"] and "teto recomendado" in aviso[0]["mensagem"]
    assert "é 5 por viagem" in aviso[0]["mensagem"]
    _cobre_todos(r, 20)


def test_exemplo_a_escolhe_4_rotas_fica_com_10_pedidos_em_4_viagens_e_b_segue_com_10_em_2():
    r = _resolver(_aleatorios(20), _dois(viagens_a=4))
    por = _por_motorista(r)
    assert sum(por[1]) == 10 and len(por[1]) == 4 and set(por[1]) <= {2, 3}, por  # 2 a 3 pedidos cada
    assert por[2] == [5, 5]
    assert not [a for a in r.avisos if a["tipo"] == "rota_personalizada"]  # nenhuma viagem passa do teto de 5
    _cobre_todos(r, 20)


def test_tipos_de_veiculo_diferentes_cada_motorista_leva_a_mesma_carga():
    # carro (teto 5) e utilitário (teto 12), 24 pedidos: 12 para cada; o carro em 3 viagens de 4, o utilitário em 1 viagem de 12
    r = _resolver(_aleatorios(24), _dois(tipos=(CARRO, UTIL), caps=(5, 12)))
    assert _por_motorista(r) == {1: [4, 4, 4], 2: [12]}
    assert {x.modal for x in r.rotas if x.motorista_id == 1} == {CARRO} and {x.modal for x in r.rotas if x.motorista_id == 2} == {UTIL}
    _cobre_todos(r, 24)


def test_tipos_diferentes_com_rota_personalizada_a_carga_nao_muda():
    r = _resolver(_aleatorios(24), _dois(viagens_a=1, tipos=(CARRO, UTIL), caps=(5, 12)))
    assert _por_motorista(r) == {1: [12], 2: [12]}  # o carro leva 12 em 1 viagem (passa do teto 5, com aviso); o utilitário, 12 em 1
    assert [a["tipo"] for a in r.avisos if a["tipo"] == "rota_personalizada"] == ["rota_personalizada"]


def test_a_carga_do_motorista_e_a_mesma_com_ou_sem_o_numero_de_viagens():
    base = _resolver(_aleatorios(21), _dois())
    for viagens in (1, 2, 4):
        r = _resolver(_aleatorios(21), _dois(viagens_a=viagens))
        assert {m: sum(v) for m, v in _por_motorista(r).items()} == {m: sum(v) for m, v in _por_motorista(base).items()}


def test_cota_impar_o_pedido_extra_vai_para_quem_fez_menos_rotas_no_dia():
    r = _resolver(_aleatorios(21), _dois(), rotas_hoje={1: 3, 2: 0})
    assert {m: sum(v) for m, v in _por_motorista(r).items()} == {1: 10, 2: 11}
    r = _resolver(_aleatorios(21), _dois(), rotas_hoje={1: 0, 2: 3})
    assert {m: sum(v) for m, v in _por_motorista(r).items()} == {1: 11, 2: 10}
    r = _resolver(_aleatorios(21), _dois())  # empate: pela ordem da lista
    assert {m: sum(v) for m, v in _por_motorista(r).items()} == {1: 11, 2: 10}


def test_menos_pedidos_que_motoristas_so_os_de_menor_contagem_trabalham():
    mots = [solver.MotoristaSolver(i, f"M{i}", CARRO, 5) for i in (1, 2, 3)]
    r = _resolver(_aleatorios(2), mots, rotas_hoje={1: 4, 2: 0, 3: 1})
    assert sorted(x.motorista_id for x in r.rotas) == [2, 3] and any(a["tipo"] == "sem_rota" for a in r.avisos)
    _cobre_todos(r, 2)


def test_cotas_por_motorista_e_numero_de_viagens():
    mots = [solver.MotoristaSolver(1, "A", CARRO, 5), solver.MotoristaSolver(2, "B", CARRO, 5, 4), solver.MotoristaSolver(3, "C", UTIL, 12)]
    assert solver.cotas_por_motorista(10, mots) == {1: 4, 2: 3, 3: 3}
    assert solver.cotas_por_motorista(10, mots, {1: 2, 2: 2, 3: 0}) == {1: 3, 2: 3, 3: 4}
    assert solver.cotas_por_motorista(2, mots, {1: 5, 2: 0, 3: 1}) == {1: 0, 2: 1, 3: 1}
    assert [solver.numero_de_viagens(m, 10) for m in mots] == [2, 4, 1]  # automático: ceil(10/5), personalizado: o escolhido, ceil(10/12)
    assert solver.numero_de_viagens(mots[1], 3) == 3  # nunca mais viagens que pedidos
    assert solver.numero_de_viagens(mots[0], 0) == 0


# ----------------------------------------------------------------------------------------------------------
# Personalizada: aviso, nunca bloqueio; viagens pedidas a mais não criam rota vazia
# ----------------------------------------------------------------------------------------------------------
def test_motorista_com_uma_viagem_recebe_mais_pedidos_que_o_teto_com_aviso_e_sem_bloqueio():
    r = _resolver(_aleatorios(14), [solver.MotoristaSolver(1, "Ana", CARRO, 5, 1)])
    assert _por_motorista(r) == {1: [14]}
    aviso = [a for a in r.avisos if a["tipo"] == "rota_personalizada"]
    assert len(aviso) == 1 and "14 pedidos em 1 viagem" in aviso[0]["mensagem"] and "5 por viagem" in aviso[0]["mensagem"]
    _cobre_todos(r, 14)


def test_viagens_pedidas_maior_que_o_numero_de_pedidos_nao_cria_rota_vazia_e_avisa():
    r = _resolver(_aleatorios(3), [solver.MotoristaSolver(1, "Ana", CARRO, 5, 4)])
    assert _por_motorista(r) == {1: [1, 1, 1]}  # 3 pedidos, 4 viagens pedidas: 3 viagens, nenhuma vazia
    assert all(x.pedidos for x in r.rotas)
    aviso = [a for a in r.avisos if a["tipo"] == "viagens_solicitadas_a_menos"]
    assert len(aviso) == 1 and "4 viagens" in aviso[0]["mensagem"] and "Ana" in aviso[0]["mensagem"] and "não cria viagem vazia" in aviso[0]["mensagem"]
    _cobre_todos(r, 3)


def test_viagens_pedidas_maior_que_a_cota_de_um_de_dois_motoristas():
    r = _resolver(_aleatorios(5), _dois(viagens_a=4))  # cotas 3 e 2: A pediu 4 viagens, mas leva só 3 pedidos
    assert _por_motorista(r)[1] == [1, 1, 1] and any(a["tipo"] == "viagens_solicitadas_a_menos" for a in r.avisos)
    assert all(x.pedidos for x in r.rotas)


def test_dois_personalizados_e_um_automatico():
    mots = [solver.MotoristaSolver(1, "A", CARRO, 5, 1), solver.MotoristaSolver(2, "B", CARRO, 5, 3), solver.MotoristaSolver(3, "C", CARRO, 5)]
    r = _resolver(_aleatorios(30), mots)
    por = _por_motorista(r)
    assert por[1] == [10] and len(por[2]) == 3 and sum(por[2]) == 10 and por[3] == [5, 5]
    assert {x.motorista_id for x in r.rotas if x.personalizada} == {1, 2}
    assert [a["mensagem"][:30] for a in r.avisos if a["tipo"] == "rota_personalizada"] == ["Rota personalizada de A: 10 pe"]
    _cobre_todos(r, 30)


def test_viagens_extras_so_contam_os_motoristas_automaticos():
    r = _resolver(_aleatorios(20), _dois(viagens_a=4))  # A pediu 4 viagens (não é "excedeu a capacidade"); B fez 2 por causa do teto
    assert r.viagens_extras == 1
    r = _resolver(_aleatorios(10), _dois(viagens_a=3, viagens_b=2))  # os dois personalizados: nada a avisar como extra
    assert r.viagens_extras == 0 and not [a for a in r.avisos if a["tipo"] == "viagens_extras"]


# ----------------------------------------------------------------------------------------------------------
# Rotação, setores, tempo e peso continuam valendo com viagens personalizadas
# ----------------------------------------------------------------------------------------------------------
def test_rotacao_com_motorista_personalizado_o_setor_proibido_vai_para_o_outro():
    pontos = _cluster("N", 4) + _cluster("S", 4)
    r = _resolver(pontos, _dois(viagens_a=2), proibidos={1: {"N": ["manha"]}})
    por = {}
    for x in r.rotas:
        por.setdefault(x.motorista_id, set()).update(x.setores)
    assert por[1] == {"S"} and por[2] == {"N"} and not [a for a in r.avisos if a["tipo"] == "rotacao"]
    assert len([x for x in r.rotas if x.motorista_id == 1]) == 2  # as 2 viagens pedidas, dividindo os 4 pedidos de S


def test_viagens_do_mesmo_motorista_ficam_em_setores_diferentes():
    pontos = _cluster("N", 4) + _cluster("S", 4)
    r = _resolver(pontos, [solver.MotoristaSolver(1, "Ana", CARRO, 10, 2)])
    assert sorted(tuple(sorted(x.setores)) for x in r.rotas) == [("N",), ("S",)]


def test_rotacao_violada_com_personalizado_avisa_e_monta_a_rota():
    r = _resolver(_cluster("N", 5), [solver.MotoristaSolver(1, "Ana", CARRO, 5, 1)], proibidos={1: {"N": ["tarde"]}})
    assert r.rotas[0].violacoes == ["N"] and any(a["tipo"] == "rotacao" for a in r.avisos)
    _cobre_todos(r, 5)


def test_peso_nunca_entra_nas_viagens_personalizadas():
    codigo = re.sub(r'""".*?"""', "", Path(solver.__file__).read_text(encoding="utf-8"), flags=re.S)
    codigo = re.sub(r"#.*", "", codigo)
    assert "peso" not in codigo.lower().replace("peso_rotacao", "")


# ----------------------------------------------------------------------------------------------------------
# API: viagens_por_motorista e compatibilidade com motorista_ids
# ----------------------------------------------------------------------------------------------------------
def test_interpretar_viagens():
    ids = {1, 2, 3}
    assert roteirizacao.interpretar_viagens(None, ids) == {} and roteirizacao.interpretar_viagens({}, ids) == {}
    assert roteirizacao.interpretar_viagens({"1": 2, "2": None, "3": ""}, ids) == {1: 2}
    assert roteirizacao.interpretar_viagens({"1": "3", "2": 4.0}, ids) == {1: 3, 2: 4}
    for ruim in (0, 11, "abc", 2.5, True, -1):
        with pytest.raises(ValueError, match="1, 2, 3 ou 4"):
            roteirizacao.interpretar_viagens({"1": ruim}, ids)
    with pytest.raises(ValueError, match="não está marcado"):
        roteirizacao.interpretar_viagens({"9": 2}, ids)
    with pytest.raises(ValueError, match="1, 2, 3 ou 4"):
        roteirizacao.interpretar_viagens({"abc": 2}, ids)


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


@pytest.fixture
def banco():
    conn = criar_banco_sqlite()
    conn.ana = conn.inserir_motorista("Ana", CARRO)
    conn.beto = conn.inserir_motorista("Beto", CARRO)
    return conn


@pytest.fixture
def api(monkeypatch, banco):
    async def get_pool():
        return FakePool(banco)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), banco
    main.app.dependency_overrides.clear()


def _capturar(monkeypatch):
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None, loja=None, contexto=None):
        capturado.update(contexto=contexto, frota=frota_usar)

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    return capturado


def test_api_aceita_viagens_por_motorista_e_so_com_motorista_ids_continua_funcionando(api, monkeypatch):
    cliente, banco = api
    capturado = _capturar(monkeypatch)
    base = {"origem_rua": "A", "origem_num": "1", "turno": "manha", "pedidos": [{"id": 1}], "motorista_ids": [banco.ana, banco.beto]}
    r = cliente.post("/api/otimizar", json=base)  # compatível: sem viagens_por_motorista = tudo automático
    assert r.status_code == 200 and capturado["contexto"]["viagens"] == {}
    r = cliente.post("/api/otimizar", json={**base, "viagens_por_motorista": {str(banco.ana): 2, str(banco.beto): None}})
    assert r.status_code == 200 and capturado["contexto"]["viagens"] == {banco.ana: 2}


@pytest.mark.parametrize("viagens, trecho", [
    ({"1": 0}, "1, 2, 3 ou 4"), ({"1": 11}, "1, 2, 3 ou 4"), ({"1": "abc"}, "1, 2, 3 ou 4"), ({"9999": 2}, "não está marcado"),
])
def test_api_recusa_viagens_invalidas_ou_de_motorista_nao_marcado(api, monkeypatch, viagens, trecho):
    cliente, banco = api
    criados = _capturar(monkeypatch)
    if "1" in viagens:
        viagens = {str(banco.ana): viagens["1"]}
    r = cliente.post("/api/otimizar", json={"origem_rua": "A", "origem_num": "1", "turno": "manha", "pedidos": [{"id": 1}],
                                           "motorista_ids": [banco.ana], "viagens_por_motorista": viagens})
    assert r.status_code == 422 and trecho in r.json()["detail"] and criados == {}


def test_viagens_de_motorista_que_nao_esta_marcado_e_recusada(api, monkeypatch):
    cliente, banco = api
    criados = _capturar(monkeypatch)
    r = cliente.post("/api/otimizar", json={"origem_rua": "A", "origem_num": "1", "turno": "manha", "pedidos": [{"id": 1}],
                                           "motorista_ids": [banco.ana], "viagens_por_motorista": {str(banco.beto): 2}})
    assert r.status_code == 422 and "não está marcado" in r.json()["detail"] and criados == {}


# ----------------------------------------------------------------------------------------------------------
# Resultado do job: rota personalizada marcada em cada rota
# ----------------------------------------------------------------------------------------------------------
def _rodar_job(monkeypatch, pontos, frota_usar, contexto, modais):
    pedidos = [{"id": str(i + 1), "Endereco": f"Rua {i + 1}", "Numero": str(i + 1), "Bairro": "Centro", "CEP": "01310100", "Volume": 1} for i in range(len(pontos))]
    coordenadas = {p["id"]: pt for p, pt in zip(pedidos, pontos)}

    async def geocode_falso(client, *a, **k):
        return HUB[0], HUB[1], "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO"

    async def lote_falso(lista):
        return {main._chave_cache(p["Endereco"], numero=p["Numero"], bairro=p["Bairro"], cep=p["CEP"], cidade="", uf=""):
                (*coordenadas[p["id"]], "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO") for p in lista}

    async def osrm_falso(client, pontos_):
        return 1.0, 1, [[a, b] for a, b in pontos_]

    monkeypatch.setattr(main, "geocode_async", geocode_falso)
    monkeypatch.setattr(main, "geocodificar_lote", lote_falso)
    monkeypatch.setattr(main, "get_osrm_route_async", osrm_falso)
    req = main.OtimizarRequest(origem_rua="Av Paulista", origem_num="1", pedidos=pedidos, modais_config=modais)
    main.JOBS["t8b"] = {"status": "em_andamento", "etapa": "", "atual": 0, "total": 1, "resultado": None, "erro": None}
    _rodar(main._processar_otimizacao("t8b", req, frota_usar, {}, None, contexto))
    job = main.JOBS.pop("t8b")
    assert job["status"] == "concluido", job["erro"]
    return job["resultado"]


def test_resultado_marca_a_rota_personalizada_com_o_comparativo(monkeypatch):
    frota_usar = [main.MotoristaItem(id=1, motorista="Ana", modal=CARRO, custo_rota=130.0), main.MotoristaItem(id=2, motorista="Beto", modal=CARRO, custo_rota=130.0)]
    contexto = {"turno": "manha", "tempo_por_parada_min": 10, "rotas_hoje": {}, "proibidos": {}, "viagens": {1: 1}}
    r = _rodar_job(monkeypatch, _aleatorios(12), frota_usar, contexto, {CARRO: {"capacidade": 3}})
    por = {}
    for rota in r["rotas"]:
        por.setdefault(rota["motorista_id"], []).append(rota)
    assert [x["qtd_pedidos"] for x in por[1]] == [6] and por[1][0]["rota_personalizada"] is True
    assert por[1][0]["teto_recomendado"] == 3 and por[1][0]["viagens_solicitadas"] == 1
    assert [x["qtd_pedidos"] for x in por[2]] == [3, 3] and not any(x["rota_personalizada"] for x in por[2])
    assert all(x["viagens_solicitadas"] is None and x["teto_recomendado"] == 3 for x in por[2])
    assert any(a["tipo"] == "rota_personalizada" and "6 pedidos em 1 viagem" in a["mensagem"] and "3 por viagem" in a["mensagem"] for a in r["avisos"])
    assert sorted(p["id"] for rota in r["rotas"] for p in rota["paradas"]) == sorted(str(i + 1) for i in range(12))


# ----------------------------------------------------------------------------------------------------------
# Totais de pedidos por motorista: dia, confirmar e desfazer
# ----------------------------------------------------------------------------------------------------------
HOJE = date(2026, 10, 22)


def _rotas(*itens):
    return [{"numero_rota": n, "motorista_id": m, "qtd_pedidos": q, "distancia_km": 3, "setores": "N"} for n, m, q in itens]


def test_totais_do_dia_somam_rotas_e_pedidos_so_das_confirmadas_do_dia(banco):
    _rodar(rr.confirmar(banco, "e1", _rotas((1, banco.ana, 5), (2, banco.ana, 5), (3, banco.beto, 10)), HOJE, "Loja", "manha", OPERADOR))
    _rodar(rr.confirmar(banco, "e2", _rotas((1, banco.ana, 4)), HOJE, "Loja", "tarde", OPERADOR))
    _rodar(rr.confirmar(banco, "e3", _rotas((1, banco.beto, 7)), date(2026, 10, 21), "Loja", "manha", OPERADOR))  # outro dia
    _rodar(rr.confirmar(banco, "e4", _rotas((1, banco.beto, 9)), HOJE, "Loja", "noite", OPERADOR))
    _rodar(rr.desfazer(banco, "e4", HOJE))  # cancelada não conta
    assert _rodar(rr.totais_do_dia(banco, HOJE)) == {banco.ana: {"rotas": 3, "pedidos": 14}, banco.beto: {"rotas": 1, "pedidos": 10}}
    assert _rodar(rr.contagem_do_dia(banco, HOJE)) == {banco.ana: 3, banco.beto: 1}  # o que já existia não mudou
    assert _rodar(rr.totais_do_dia(banco, date(2026, 10, 21))) == {banco.beto: {"rotas": 1, "pedidos": 7}}
    assert _rodar(rr.totais_do_dia(banco, date(2026, 10, 20))) == {}


def test_confirmar_devolve_pedidos_da_execucao_e_do_dia_e_desfazer_reflete(banco):
    _rodar(rr.confirmar(banco, "antes", _rotas((1, banco.ana, 4)), HOJE, "Loja", "manha", OPERADOR))
    r = _rodar(rr.confirmar(banco, "agora", _rotas((1, banco.ana, 5), (2, banco.ana, 5), (3, banco.beto, 10)), HOJE, "Loja", "tarde", OPERADOR))
    por_nome = {m["nome"]: m for m in r["motoristas"]}
    assert (por_nome["Ana"]["nesta_execucao"], por_nome["Ana"]["total_hoje"], por_nome["Ana"]["pedidos_nesta_execucao"], por_nome["Ana"]["pedidos_hoje"]) == (2, 3, 10, 14)
    assert (por_nome["Beto"]["nesta_execucao"], por_nome["Beto"]["total_hoje"], por_nome["Beto"]["pedidos_nesta_execucao"], por_nome["Beto"]["pedidos_hoje"]) == (1, 1, 10, 10)
    d = _rodar(rr.desfazer(banco, "agora", HOJE))
    por_nome = {m["nome"]: m for m in d["motoristas"]}
    assert (por_nome["Ana"]["total_hoje"], por_nome["Ana"]["pedidos_hoje"], por_nome["Ana"]["pedidos_nesta_execucao"]) == (1, 4, 0)
    assert (por_nome["Beto"]["total_hoje"], por_nome["Beto"]["pedidos_hoje"]) == (0, 0)


def test_confirmar_de_novo_nao_duplica_os_pedidos(banco):
    _rodar(rr.confirmar(banco, "x", _rotas((1, banco.ana, 6)), HOJE, "Loja", "manha", OPERADOR))
    r = _rodar(rr.confirmar(banco, "x", _rotas((1, banco.ana, 6)), HOJE, "Loja", "manha", OPERADOR))
    assert r["ja_confirmada"] and r["motoristas"][0]["pedidos_hoje"] == 6


def test_api_hoje_traz_pedidos_por_motorista_sem_mudar_o_que_ja_existia(api):
    cliente, banco = api
    dia = rr.hoje_em_brasilia()
    _rodar(rr.confirmar(banco, "api8b", _rotas((1, banco.ana, 5), (2, banco.ana, 3)), dia, "Loja", "manha", OPERADOR))
    r = cliente.get("/api/rotas-realizadas/hoje").json()
    assert r["data"] == dia.isoformat() and r["por_motorista"] == {str(banco.ana): 2}
    assert r["pedidos_por_motorista"] == {str(banco.ana): 8}


def test_api_confirmar_e_desfazer_devolvem_os_pedidos(api):
    cliente, banco = api
    main.JOBS["e8b"] = {"status": "concluido", "erro": None, "resultado": {"loja_hub": "Loja", "turno": "manha", "rotas": [
        {"id": 1, "motorista_id": banco.ana, "qtd_pedidos": 10, "km_total": 5, "setores": ["N"]},
    ]}}
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "e8b"}).json()
    assert r["motoristas"][0]["pedidos_nesta_execucao"] == 10 and r["motoristas"][0]["pedidos_hoje"] == 10
    d = cliente.post("/api/rotas-realizadas/e8b/desfazer").json()
    assert d["motoristas"][0]["pedidos_hoje"] == 0 and d["motoristas"][0]["total_hoje"] == 0
    main.JOBS.pop("e8b")


def test_sem_migration_nova_na_8b():
    versoes = Path(main.__file__).parent / "migrations" / "versions"
    assert not list(versoes.glob("0011*")) and sorted(p.name[:4] for p in versoes.glob("00*.py"))[-1] == "0010"
