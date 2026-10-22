"""Etapa 8: roteirização automática (OR-Tools): setores, matriz OSRM/linha reta, solver, regra de rotação, justiça, tempos, avisos,
turno obrigatório, setores gravados ao confirmar, migration 0010, desempenho e privacidade."""
import asyncio
import importlib.util
import json
import logging
import random
import re
import time
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


def _ponto(setor, km=3.0, jitter=0.0):
    """Coordenada a `km` do hub na direção do setor (azimute no centro do setor)."""
    import math
    graus = setores.SETORES.index(setor) * 45.0
    dlat = km / 111.195 * math.cos(math.radians(graus))
    dlon = km / (111.195 * math.cos(math.radians(HUB[0]))) * math.sin(math.radians(graus))
    return (HUB[0] + dlat + jitter, HUB[1] + dlon + jitter)


def _matrizes(pontos):
    return matriz.matriz_linha_reta([HUB] + pontos)


def _motoristas(*itens):
    return [solver.MotoristaSolver(id=i, nome=nome, modal=modal, capacidade=cap) for i, nome, modal, cap in itens]


def _resolver(pontos, motoristas, **kw):
    dist, dur = _matrizes(pontos)
    sec = [setores.setor_do_pedido(*HUB, *p) for p in pontos]
    kw.setdefault("limite_s", 1.0)
    return solver.resolver(dist, dur, sec, motoristas, **kw)


# ----------------------------------------------------------------------------------------------------------
# Setores: 8 quadrantes pelo azimute loja -> pedido
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("setor", setores.SETORES)
def test_oito_quadrantes_no_centro_de_cada_setor(setor):
    for km in (0.5, 3, 25):
        assert setores.setor_do_pedido(*HUB, *_ponto(setor, km)) == setor


@pytest.mark.parametrize("graus, esperado", [
    (0, "N"), (22.49, "N"), (22.5, "NE"), (44.9, "NE"), (67.4, "NE"), (67.5, "L"), (90, "L"), (112.4, "L"), (112.5, "SE"), (157.4, "SE"),
    (157.5, "S"), (180, "S"), (202.4, "S"), (202.5, "SO"), (247.4, "SO"), (247.5, "O"), (270, "O"), (292.4, "O"), (292.5, "NO"),
    (337.4, "NO"), (337.5, "N"), (359.9, "N"), (360, "N"), (-10, "N"), (720 + 90, "L"),
])
def test_fronteiras_dos_setores_pelo_azimute(graus, esperado):
    assert setores.setor_do_azimute(graus) == esperado


def test_azimute_e_pedido_em_cima_da_loja():
    assert round(setores.azimute(0, 0, 1, 0)) == 0 and round(setores.azimute(0, 0, 0, 1)) == 90
    assert round(setores.azimute(0, 0, -1, 0)) == 180 and round(setores.azimute(0, 0, 0, -1)) == 270
    assert setores.setor_do_pedido(*HUB, HUB[0] + 0.00005, HUB[1]) == "N"  # ~5 m: sem direção, convenção N
    assert setores.setor_do_pedido(*HUB, HUB[0] - 0.0005, HUB[1]) == "S"  # ~55 m já tem direção


def test_helpers_de_setor():
    assert setores.distancia_circular("N", "S") == 4 and setores.distancia_circular("N", "NO") == 1 and setores.distancia_circular("NE", "NE") == 0
    assert setores.oposto("N") == "S" and setores.oposto("SO") == "NE"
    assert setores.texto_dos_setores(["NO", "N", "N", "SE"]) == "N,SE,NO" and setores.setores_do_texto("N, NE,xx") == ["N", "NE"]


# ----------------------------------------------------------------------------------------------------------
# Matriz: OSRM (table) e reserva em linha reta
# ----------------------------------------------------------------------------------------------------------
class RespostaFalsa:
    def __init__(self, dados):
        self.dados = dados

    def json(self):
        return self.dados


class ClienteFalso:
    def __init__(self, dados=None, erro=None):
        self.dados, self.erro, self.urls = dados, erro, []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        if self.erro:
            raise self.erro
        return RespostaFalsa(self.dados)


def test_matriz_osrm_table():
    pontos = [HUB, _ponto("N"), _ponto("S")]
    dados = {"code": "Ok", "distances": [[0, 1000.4, 2000], [1000, 0, 3000], [2000, 3000, 0]], "durations": [[0, 120.6, 240], [120, 0, 300], [240, 300, 0]]}
    cliente = ClienteFalso(dados)
    r = _rodar(matriz.obter_matriz(cliente, pontos))
    assert r["origem"] == "osrm" and r["aviso"] is None and r["distancias_m"][0][1] == 1000 and r["duracoes_s"][0][1] == 121
    assert "/table/v1/driving/" in cliente.urls[0] and "annotations=duration,distance" in cliente.urls[0]
    assert f"{HUB[1]},{HUB[0]};" in cliente.urls[0]  # OSRM usa longitude,latitude


@pytest.mark.parametrize("cliente", [
    ClienteFalso(erro=RuntimeError("sem rede")),
    ClienteFalso({"code": "TooBig"}),
    ClienteFalso({"code": "Ok", "distances": [[0, None], [1, 0]], "durations": [[0, 5], [5, 0]]}),  # trecho sem rota (null)
    ClienteFalso({"code": "Ok", "distances": [[0]], "durations": [[0]]}),  # tamanho errado
])
def test_matriz_cai_para_linha_reta_com_aviso(cliente):
    pontos = [HUB, _ponto("L", 2), _ponto("O", 2)]
    r = _rodar(matriz.obter_matriz(cliente, pontos))
    assert r["origem"] == "linha_reta" and "linha reta" in r["aviso"] and "estimativas" in r["aviso"]
    assert r["distancias_m"][0][1] > 2000  # linha reta x 1,3
    assert r["distancias_m"][1][2] > r["distancias_m"][0][1]


def test_matriz_linha_reta_usa_fator_de_rua_e_22_kmh():
    d, t = matriz.matriz_linha_reta([HUB, _ponto("N", 10)])
    reta = setores.distancia_m(*HUB, *_ponto("N", 10))
    assert abs(d[0][1] - reta * 1.3) < 2 and abs(t[0][1] - reta * 1.3 / 1000 / 22 * 3600) < 2 and d[0][0] == 0


def test_muitos_pontos_vao_direto_para_linha_reta_sem_consultar_o_osrm():
    cliente = ClienteFalso({"code": "Ok"})
    pontos = [HUB] + [_ponto("N", 1 + i * 0.01) for i in range(100)]  # 101 pontos
    r = _rodar(matriz.obter_matriz(cliente, pontos))
    assert r["origem"] == "linha_reta" and "muitos pontos" in r["aviso"] and cliente.urls == []


def test_um_ponto_so_nao_precisa_de_matriz():
    assert _rodar(matriz.obter_matriz(ClienteFalso(), [HUB]))["distancias_m"] == [[0]]


# ----------------------------------------------------------------------------------------------------------
# Solver: cobertura, capacidade, equilíbrio, viagens extras
# ----------------------------------------------------------------------------------------------------------
def _aleatorios(n, semente=3, raio=0.08):
    azar = random.Random(semente)
    return [(HUB[0] + azar.uniform(-raio, raio), HUB[1] + azar.uniform(-raio, raio)) for _ in range(n)]


@pytest.mark.parametrize("n, caps", [(1, (8, 8)), (5, (8, 8, 8)), (12, (4, 6)), (17, (5, 5, 5)), (30, (8, 8, 12))])
def test_todos_os_pedidos_exatamente_uma_vez_e_capacidade_respeitada(n, caps):
    mots = _motoristas(*[(i + 1, f"M{i + 1}", f"Tipo{c}", c) for i, c in enumerate(caps)])  # a capacidade é do TIPO de veículo
    r = _resolver(_aleatorios(n), mots)
    vistos = Counter(p for rota in r.rotas for p in rota.pedidos)
    assert sorted(vistos) == list(range(n)) and set(vistos.values()) == {1}
    capacidade = {m.id: m.capacidade for m in mots}
    for rota in r.rotas:
        assert 1 <= len(rota.pedidos) <= capacidade[rota.motorista_id]
    assert r.metodo == "ortools"


def test_equilibrio_do_numero_de_pedidos_entre_as_rotas():
    mots = _motoristas((1, "A", CARRO, 8), (2, "B", CARRO, 8), (3, "C", CARRO, 8))
    for n in (10, 20):
        r = _resolver(_aleatorios(n), mots)
        tamanhos = sorted(len(x.pedidos) for x in r.rotas)
        assert len(tamanhos) == 3 and tamanhos[-1] - tamanhos[0] <= 1, tamanhos


def test_viagens_extras_para_os_mesmos_motoristas_quando_excede_a_capacidade():
    mots = _motoristas((1, "Ana", CARRO, 3), (2, "Beto", CARRO, 3))
    r = _resolver(_aleatorios(10), mots)
    assert sorted(p for x in r.rotas for p in x.pedidos) == list(range(10))
    assert {x.motorista_id for x in r.rotas} == {1, 2} and len(r.rotas) >= 4
    assert r.viagens_extras == len(r.rotas) - 2 > 0
    assert any(a["tipo"] == "viagens_extras" and "voltam à loja" in a["mensagem"] for a in r.avisos)
    for m in (1, 2):  # as viagens do mesmo motorista são numeradas 1, 2, ...
        assert sorted(x.viagem_num for x in r.rotas if x.motorista_id == m) == list(range(1, 1 + sum(1 for x in r.rotas if x.motorista_id == m)))
    assert all(len(x.pedidos) <= 3 for x in r.rotas)


def test_um_motorista_com_capacidade_pequena_nunca_recusa():
    r = _resolver(_aleatorios(9), _motoristas((1, "Ana", CARRO, 2)))
    assert [x.motorista_id for x in r.rotas] == [1] * len(r.rotas) and len(r.rotas) == 5
    assert sorted(p for x in r.rotas for p in x.pedidos) == list(range(9))


def test_capacidade_por_tipo_de_veiculo():
    mots = _motoristas((1, "Carro", CARRO, 2), (2, "Fiorino", UTIL, 10))
    r = _resolver(_aleatorios(8), mots)
    por_motorista = Counter()
    for x in r.rotas:
        por_motorista[x.motorista_id] = max(por_motorista[x.motorista_id], len(x.pedidos))
        assert x.modal == (CARRO if x.motorista_id == 1 else UTIL)
        assert len(x.pedidos) <= (2 if x.motorista_id == 1 else 10)
    assert set(por_motorista) == {1, 2}


def test_sem_pedidos_ou_sem_motoristas_devolve_vazio():
    assert solver.resolver([[0]], [[0]], [], _motoristas((1, "A", CARRO, 5))).rotas == []
    dist, dur = _matrizes(_aleatorios(2))
    assert solver.resolver(dist, dur, ["N", "S"], []).rotas == []


# ----------------------------------------------------------------------------------------------------------
# Regra de rotação (forte, mas nunca bloqueante) e justiça
# ----------------------------------------------------------------------------------------------------------
def _cluster(setor, n, km=4.0):
    return [_ponto(setor, km, jitter=i * 0.0004) for i in range(n)]


def test_rotacao_cumprida_o_outro_motorista_pega_o_setor_proibido():
    pontos = _cluster("N", 3) + _cluster("S", 3)
    mots = _motoristas((1, "Ana", CARRO, 10), (2, "Beto", CARRO, 10))
    r = _resolver(pontos, mots, proibidos={1: {"N": ["manha"]}})
    por_motorista = {x.motorista_id: x for x in r.rotas}
    assert set(por_motorista[1].setores) == {"S"} and set(por_motorista[2].setores) == {"N"}
    assert all(not x.violacoes for x in r.rotas) and not [a for a in r.avisos if a["tipo"] == "rotacao"]


def test_rotacao_violada_com_aviso_quando_e_inevitavel_e_a_rota_sai_mesmo_assim():
    pontos = _cluster("N", 3) + _cluster("S", 2)
    r = _resolver(pontos, _motoristas((1, "Ana", CARRO, 10)), proibidos={1: {"N": ["manha"]}})
    assert sorted(p for x in r.rotas for p in x.pedidos) == list(range(5))  # a rota é montada mesmo assim
    assert r.rotas[0].violacoes == ["N"]
    avisos = [a for a in r.avisos if a["tipo"] == "rotacao"]
    assert len(avisos) == 1 and "Ana" in avisos[0]["mensagem"] and "setor N" in avisos[0]["mensagem"] and "manha" in avisos[0]["mensagem"]
    assert "não há outro motorista marcado" in avisos[0]["mensagem"]


def test_rotacao_violada_quando_todos_os_motoristas_ja_passaram_pelo_setor():
    pontos = _cluster("N", 4)
    proibidos = {1: {"N": ["manha"]}, 2: {"N": ["tarde"]}}
    r = _resolver(pontos, _motoristas((1, "Ana", CARRO, 10), (2, "Beto", CARRO, 10)), proibidos=proibidos)
    avisos = [a for a in r.avisos if a["tipo"] == "rotacao"]
    assert len(avisos) >= 1 and all("já passaram por esse setor em outro turno hoje" in a["mensagem"] for a in avisos)
    assert sorted(p for x in r.rotas for p in x.pedidos) == [0, 1, 2, 3]


def test_justica_prefere_quem_fez_menos_rotas_no_dia():
    mots = _motoristas((1, "Ana", CARRO, 10), (2, "Beto", CARRO, 10))
    um = _resolver(_cluster("L", 1), mots, rotas_hoje={1: 3, 2: 0})  # uma só rota: vai para quem fez menos
    assert [x.motorista_id for x in um.rotas] == [2]
    um = _resolver(_cluster("L", 1), mots, rotas_hoje={1: 0, 2: 4})
    assert [x.motorista_id for x in um.rotas] == [1]
    assert any(a["tipo"] == "sem_rota" for a in um.avisos)  # com pouco pedido, o outro fica sem rota (informativo)


def test_justica_na_cota_impar_e_todos_os_motoristas_trabalham():
    mots = _motoristas((1, "Ana", CARRO, 2), (2, "Beto", CARRO, 2))
    r = _resolver(_aleatorios(6), mots, rotas_hoje={1: 5, 2: 0})
    pedidos_por_motorista = Counter()
    for x in r.rotas:
        pedidos_por_motorista[x.motorista_id] += len(x.pedidos)
    assert pedidos_por_motorista == {1: 3, 2: 3} and len(r.rotas) == 4  # carga igual por motorista (3 e 3), cada um em 2 viagens de teto 2
    r = _resolver(_aleatorios(7), mots, rotas_hoje={1: 5, 2: 0})
    pedidos_por_motorista = Counter()
    for x in r.rotas:
        pedidos_por_motorista[x.motorista_id] += len(x.pedidos)
    assert pedidos_por_motorista == {1: 3, 2: 4}  # o pedido a mais vai para quem fez menos rotas no dia


def test_viagens_do_mesmo_motorista_ficam_em_setores_diferentes():
    pontos = _cluster("N", 3) + _cluster("S", 3)
    r = _resolver(pontos, _motoristas((1, "Ana", CARRO, 3)))
    assert len(r.rotas) == 2 and [x.motorista_id for x in r.rotas] == [1, 1]
    assert [set(x.setores) for x in sorted(r.rotas, key=lambda x: x.viagem_num)] in ([{"N"}, {"S"}], [{"S"}, {"N"}])


# ----------------------------------------------------------------------------------------------------------
# Reserva (sem ortools ou sem solução)
# ----------------------------------------------------------------------------------------------------------
def test_reserva_gulosa_cobre_todos_os_pedidos_e_avisa():
    mots = _motoristas((1, "Ana", CARRO, 4), (2, "Beto", CARRO, 4))
    r = _resolver(_aleatorios(11), mots, usar_ortools=False)
    assert r.metodo == "reserva" and sorted(p for x in r.rotas for p in x.pedidos) == list(range(11))
    assert all(len(x.pedidos) <= 4 for x in r.rotas) and {x.motorista_id for x in r.rotas} == {1, 2}
    assert any(a["tipo"] == "reserva" and "método simples" in a["mensagem"] for a in r.avisos)


def test_ortools_ausente_ou_sem_solucao_cai_na_reserva_com_aviso(monkeypatch):
    def falta(*a, **k):
        raise ImportError("ortools")

    monkeypatch.setattr(solver, "_agrupar_ortools", falta)
    r = _resolver(_aleatorios(6), _motoristas((1, "Ana", CARRO, 4), (2, "Beto", CARRO, 4)))
    assert r.metodo == "reserva" and "não está disponível" in r.avisos[0]["mensagem"]
    assert sorted(p for x in r.rotas for p in x.pedidos) == list(range(6))
    monkeypatch.setattr(solver, "_agrupar_ortools", lambda *a, **k: None)
    r = _resolver(_aleatorios(6), _motoristas((1, "Ana", CARRO, 4), (2, "Beto", CARRO, 4)))
    assert r.metodo == "reserva" and "não achou uma solução" in r.avisos[0]["mensagem"]


def test_reserva_tambem_respeita_a_rotacao_quando_da():
    pontos = _cluster("N", 3) + _cluster("S", 3)
    r = _resolver(pontos, _motoristas((1, "Ana", CARRO, 10), (2, "Beto", CARRO, 10)), proibidos={1: {"N": ["manha"]}}, usar_ortools=False)
    por_motorista = {x.motorista_id: set(x.setores) for x in r.rotas}
    assert por_motorista[1] == {"S"} and por_motorista[2] == {"N"}


# ----------------------------------------------------------------------------------------------------------
# Orquestração: tempo = deslocamento + paradas, trechos, avisos, peso nunca entra
# ----------------------------------------------------------------------------------------------------------
class Mot:
    def __init__(self, id, motorista, modal):
        self.id, self.motorista, self.modal = id, motorista, modal


def _executar(pedidos, motoristas, capacidades=None, tempo=10, matriz_falsa=None, **kw):
    async def obter(pontos):
        if matriz_falsa:
            return matriz_falsa(pontos)
        d, t = matriz.matriz_linha_reta(pontos)
        return {"distancias_m": d, "duracoes_s": t, "origem": "osrm", "aviso": None}

    kw.setdefault("limite_s", 1.0)
    return _rodar(roteirizacao.executar(
        pedidos=pedidos, hub=HUB, motoristas=motoristas, capacidades=capacidades or {CARRO: 8, UTIL: 12}, turno="manha",
        tempo_por_parada_min=tempo, rotas_hoje=kw.pop("rotas_hoje", {}), proibidos=kw.pop("proibidos", {}), obter_matriz=obter, **kw,
    ))


def _pedidos(pontos, **extra):
    return [{"id": str(i + 1), "lat": lat, "lon": lon, **extra} for i, (lat, lon) in enumerate(pontos)]


def test_tempo_da_rota_e_deslocamento_mais_tempo_por_parada():
    pedidos = _pedidos(_aleatorios(7))
    for tempo in (10, 15, 1):
        plano = _executar(pedidos, [Mot(1, "Ana", CARRO)], tempo=tempo)
        for v in plano["viagens"]:
            n = len(v["pedidos"])
            assert v["tempo_paradas_min"] == n * tempo
            assert v["tempo_min"] == v["tempo_deslocamento_min"] + v["tempo_paradas_min"]
            assert v["tempo_deslocamento_min"] > 0
    assert plano["parametros"]["tempo_por_parada_min"] == 1


def test_tempo_de_deslocamento_vem_da_matriz_e_inclui_a_volta_a_loja():
    pedidos = _pedidos([_ponto("N", 6)])
    # matriz sintética: ida 600 s, volta 900 s, 5 km de ida e 7 km de volta
    def fake(pontos):
        return {"distancias_m": [[0, 5000], [7000, 0]], "duracoes_s": [[0, 600], [900, 0]], "origem": "osrm", "aviso": None}

    v = _executar(pedidos, [Mot(1, "Ana", CARRO)], matriz_falsa=fake)["viagens"][0]
    assert v["tempo_deslocamento_min"] == 25 and v["tempo_paradas_min"] == 10 and v["tempo_min"] == 35
    assert v["km_total"] == 12.0 and v["distancias_trechos_km"] == [5.0, 7.0] and v["distancia_retorno_km"] == 7.0


def test_distancia_entre_paradas_consecutivas_e_ordem_das_paradas():
    plano = _executar(_pedidos(_cluster("N", 4)), [Mot(1, "Ana", CARRO)])
    v = plano["viagens"][0]
    assert [p["ordem"] for p in v["pedidos"]] == [1, 2, 3, 4]
    assert [p["distancia_anterior_km"] for p in v["pedidos"]] == v["distancias_trechos_km"][:-1]
    assert round(sum(v["distancias_trechos_km"]), 1) == round(v["km_total"], 1) or abs(sum(v["distancias_trechos_km"]) - v["km_total"]) < 0.05
    assert all(p["setor"] == "N" for p in v["pedidos"]) and v["setores"] == ["N"]


def test_aviso_de_linha_reta_e_origem_das_distancias():
    def reserva(pontos):
        d, t = matriz.matriz_linha_reta(pontos)
        return {"distancias_m": d, "duracoes_s": t, "origem": "linha_reta", "aviso": matriz.AVISO_LINHA_RETA}

    plano = _executar(_pedidos(_aleatorios(5)), [Mot(1, "Ana", CARRO)], matriz_falsa=reserva)
    assert plano["origem_distancias"] == "linha_reta"
    assert any(a["tipo"] == "linha_reta" and a["gravidade"] == "atencao" and "linha reta" in a["mensagem"] for a in plano["avisos"])
    assert _executar(_pedidos(_aleatorios(5)), [Mot(1, "Ana", CARRO)])["origem_distancias"] == "osrm"


def test_peso_nunca_bloqueia_nem_avisa_nem_muda_as_rotas():
    base = _aleatorios(9)
    leves = _executar(_pedidos(base), [Mot(1, "Ana", CARRO), Mot(2, "Beto", CARRO)])
    pesados = _executar(_pedidos(base, peso_kg=99999, Peso=99999, Volume=500, peso_estimado=1e9), [Mot(1, "Ana", CARRO), Mot(2, "Beto", CARRO)])
    assert sorted(len(v["pedidos"]) for v in pesados["viagens"]) == sorted(len(v["pedidos"]) for v in leves["viagens"])
    assert sum(len(v["pedidos"]) for v in pesados["viagens"]) == 9
    for plano in (leves, pesados):
        assert not any(re.search(r"peso|kg|capacidade", a["mensagem"], re.IGNORECASE) for a in plano["avisos"])
    fonte = (Path(solver.__file__).read_text(encoding="utf-8") + Path(roteirizacao.__file__).read_text(encoding="utf-8"))
    codigo = re.sub(r'""".*?"""', "", fonte, flags=re.S)
    codigo = re.sub(r"#.*", "", codigo)
    assert "peso" not in codigo.lower().replace("peso_rotacao", "").replace("peso_justica", "").replace("peso_setor", "")


def test_sem_pedidos_nao_ha_rotas():
    plano = _executar([], [Mot(1, "Ana", CARRO)])
    assert plano["viagens"] == [] and plano["origem_distancias"] is None


def test_turno_e_tempo_por_parada():
    assert [roteirizacao.normalizar_turno(t) for t in ("manhã", "Manha", " TARDE ", "noite")] == ["manha", "manha", "tarde", "noite"]
    for ruim in (None, "", "madrugada", "  "):
        with pytest.raises(ValueError, match="Escolha o turno"):
            roteirizacao.normalizar_turno(ruim)
    assert roteirizacao.interpretar_tempo_por_parada(None) == 10 and roteirizacao.interpretar_tempo_por_parada("") == 10
    assert roteirizacao.interpretar_tempo_por_parada("15") == 15 and roteirizacao.interpretar_tempo_por_parada(7.0) == 7
    for ruim in (0, 61, "abc", 2.5, True, -3):
        with pytest.raises(ValueError, match="entre 1 e 60"):
            roteirizacao.interpretar_tempo_por_parada(ruim)
    assert roteirizacao.formatar_tempo(45) == "45 min" and roteirizacao.formatar_tempo(125) == "2h 5m"


# ----------------------------------------------------------------------------------------------------------
# Fluxo completo (job em segundo plano), turno obrigatório, confirmar com turno e setores, migration, privacidade
# ----------------------------------------------------------------------------------------------------------
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


def _geocodificar_por_id(monkeypatch, coordenadas):
    async def geocode_falso(client, *a, **k):
        return HUB[0], HUB[1], "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO"

    async def lote_falso(lista):
        saida = {}
        for p in lista:
            lat, lon = coordenadas[p["id"]]
            saida[main._chave_cache(p["Endereco"], numero=p["Numero"], bairro=p.get("Bairro", ""), cep=p.get("CEP", ""), cidade=p.get("Cidade", ""), uf=p.get("UF", ""))] = (
                lat, lon, "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO")
        return saida

    async def osrm_falso(client, pontos):
        return 1.0, 1, [[a, b] for a, b in pontos]

    monkeypatch.setattr(main, "geocode_async", geocode_falso)
    monkeypatch.setattr(main, "geocodificar_lote", lote_falso)
    monkeypatch.setattr(main, "get_osrm_route_async", osrm_falso)


def _pedidos_do_job(pontos, prefixo="Rua Reservada"):
    pedidos = [{"id": str(i + 1), "Endereco": f"{prefixo} {i + 1}", "Numero": str(i + 1), "Bairro": "Bairro Secreto", "CEP": "01310100", "Volume": 1} for i in range(len(pontos))]
    return pedidos, {p["id"]: pt for p, pt in zip(pedidos, pontos)}


def _rodar_job(monkeypatch, pontos, frota_usar, contexto, modais=None, **req_extra):
    pedidos, coordenadas = _pedidos_do_job(pontos)
    _geocodificar_por_id(monkeypatch, coordenadas)
    req = main.OtimizarRequest(origem_rua="Av Paulista", origem_num="1", pedidos=pedidos, modais_config=modais, **req_extra)
    main.JOBS["t8"] = {"status": "em_andamento", "etapa": "", "atual": 0, "total": 1, "resultado": None, "erro": None}
    _rodar(main._processar_otimizacao("t8", req, frota_usar, {}, None, contexto))
    job = main.JOBS.pop("t8")
    assert job["status"] == "concluido", job["erro"]
    return job["resultado"]


def test_resultado_completo_mantem_o_formato_e_acrescenta_setores_avisos_e_origem(monkeypatch):
    frota_usar = [main.MotoristaItem(id=1, motorista="Ana", modal=CARRO, custo_rota=130.0), main.MotoristaItem(id=2, motorista="Beto", modal=CARRO, custo_rota=130.0)]
    contexto = {"turno": "tarde", "tempo_por_parada_min": 12, "rotas_hoje": {}, "proibidos": {}}
    r = _rodar_job(monkeypatch, _cluster("N", 3) + _cluster("S", 3), frota_usar, contexto, {CARRO: {"capacidade": 5}})
    assert r["turno"] == "tarde" and r["origem_distancias"] == "osrm" and isinstance(r["avisos"], list) and r["parametros"]["tempo_por_parada_min"] == 12
    assert r["kpis"]["total_pedidos"] == 6 and r["kpis"]["tempo_total_min"] == sum(x["tempo_min"] for x in r["rotas"])
    for chave in ("id", "motorista", "motorista_base", "motorista_id", "viagem_num", "modal", "cor", "qtd_pedidos", "km_total", "tempo_formatado",
                  "custo_total", "geometria", "paradas", "link_maps", "setores", "tempo_min", "distancias_trechos_km"):
        assert all(chave in rota for rota in r["rotas"]), chave
    assert sorted(p["id"] for rota in r["rotas"] for p in rota["paradas"]) == ["1", "2", "3", "4", "5", "6"]  # cada pedido uma vez
    assert {tuple(rota["setores"]) for rota in r["rotas"]} == {("N",), ("S",)}
    assert all(p["ordem"] == i + 1 and p["setor"] in rota["setores"] for rota in r["rotas"] for i, p in enumerate(rota["paradas"]))


def test_job_respeita_a_regra_de_rotacao_do_contexto(monkeypatch):
    frota_usar = [main.MotoristaItem(id=1, motorista="Ana", modal=CARRO, custo_rota=130.0), main.MotoristaItem(id=2, motorista="Beto", modal=CARRO, custo_rota=130.0)]
    contexto = {"turno": "tarde", "tempo_por_parada_min": 10, "rotas_hoje": {}, "proibidos": {1: {"N": ["manha"]}}}
    r = _rodar_job(monkeypatch, _cluster("N", 3) + _cluster("S", 3), frota_usar, contexto, {CARRO: {"capacidade": 5}})
    por_motorista = {rota["motorista_id"]: rota["setores"] for rota in r["rotas"]}
    assert por_motorista == {1: ["S"], 2: ["N"]} and not [a for a in r["avisos"] if a["tipo"] == "rotacao"]


def test_job_aviso_de_rotacao_violada_e_viagens_extras(monkeypatch):
    frota_usar = [main.MotoristaItem(id=1, motorista="Ana", modal=CARRO, custo_rota=130.0)]
    contexto = {"turno": "tarde", "tempo_por_parada_min": 10, "rotas_hoje": {}, "proibidos": {1: {"N": ["manha"]}}}
    r = _rodar_job(monkeypatch, _cluster("N", 4), frota_usar, contexto, {CARRO: {"capacidade": 2}})
    tipos = {a["tipo"] for a in r["avisos"]}
    assert {"rotacao", "viagens_extras"} <= tipos and r["kpis"]["total_pedidos"] == 4 and len(r["rotas"]) == 2


def test_turno_e_obrigatorio_na_api_e_o_botao_nao_depende_do_relogio(api, monkeypatch):
    cliente, banco = api
    criados = []
    monkeypatch.setattr(main, "_processar_otimizacao", lambda *a, **k: criados.append(a))
    base = {"origem_rua": "A", "origem_num": "1", "pedidos": [{"id": 1}], "motorista_ids": [banco.ana]}
    for ruim in ({}, {"turno": ""}, {"turno": "madrugada"}, {"turno": None}):
        r = cliente.post("/api/otimizar", json={**base, **ruim})
        assert r.status_code == 422 and r.json()["detail"] == "Escolha o turno (manhã, tarde ou noite)."
    r = cliente.post("/api/otimizar", json={**base, "turno": "manha", "tempo_por_parada_min": 99})
    assert r.status_code == 422 and "entre 1 e 60" in r.json()["detail"]
    assert criados == []


def test_api_entrega_ao_job_turno_tempo_historico_e_setores_proibidos(api, monkeypatch):
    cliente, banco = api
    dia = rr.hoje_em_brasilia()
    _rodar(rr.confirmar(banco, "antiga", [{"numero_rota": 1, "motorista_id": banco.ana, "qtd_pedidos": 2, "distancia_km": 3, "setores": "N,NE"}], dia, "Loja", "manha", OPERADOR))
    _rodar(rr.confirmar(banco, "antiga2", [{"numero_rota": 1, "motorista_id": banco.beto, "qtd_pedidos": 2, "distancia_km": 3, "setores": "S"}], dia, "Loja", "tarde", OPERADOR))
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None, loja=None, contexto=None):
        capturado.update(contexto=contexto, frota=frota_usar)

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    r = cliente.post("/api/otimizar", json={"origem_rua": "A", "origem_num": "1", "turno": "Tarde", "tempo_por_parada_min": 12, "pedidos": [{"id": 1}],
                                           "motorista_ids": [banco.ana, banco.beto]})
    assert r.status_code == 200
    contexto = capturado["contexto"]
    assert contexto["turno"] == "tarde" and contexto["tempo_por_parada_min"] == 12
    assert contexto["rotas_hoje"] == {banco.ana: 1, banco.beto: 1}
    # só vale o que foi feito em OUTRO turno: a rota da manhã da Ana conta; a da tarde do Beto (mesmo turno) não
    assert contexto["proibidos"] == {banco.ana: {"N": ["manha"], "NE": ["manha"]}}


def test_setores_do_dia_so_conta_confirmadas_de_outro_turno_do_mesmo_dia(banco):
    hoje, ontem = date(2026, 10, 21), date(2026, 10, 20)
    _rodar(rr.confirmar(banco, "e1", [{"numero_rota": 1, "motorista_id": banco.ana, "setores": "N"}], hoje, None, "manha", OPERADOR))
    _rodar(rr.confirmar(banco, "e2", [{"numero_rota": 1, "motorista_id": banco.ana, "setores": "L,SE"}], hoje, None, "noite", OPERADOR))
    _rodar(rr.confirmar(banco, "e3", [{"numero_rota": 1, "motorista_id": banco.beto, "setores": "O"}], ontem, None, "manha", OPERADOR))  # outro dia
    _rodar(rr.confirmar(banco, "e4", [{"numero_rota": 1, "motorista_id": banco.beto, "setores": "S"}], hoje, None, None, OPERADOR))  # sem turno
    _rodar(rr.confirmar(banco, "e5", [{"numero_rota": 1, "motorista_id": banco.beto, "setores": None}], hoje, None, "manha", OPERADOR))  # rota antiga
    _rodar(rr.confirmar(banco, "e6", [{"numero_rota": 1, "motorista_id": banco.beto, "setores": "NO"}], hoje, None, "manha", OPERADOR))
    _rodar(rr.desfazer(banco, "e6", hoje))  # cancelada não conta
    assert _rodar(rr.setores_do_dia(banco, hoje, "tarde")) == {banco.ana: {"N": ["manha"], "L": ["noite"], "SE": ["noite"]}}
    assert _rodar(rr.setores_do_dia(banco, hoje, "manha")) == {banco.ana: {"L": ["noite"], "SE": ["noite"]}}


def test_confirmar_grava_o_turno_do_resultado_e_os_setores_de_cada_rota(api):
    cliente, banco = api
    main.JOBS["exec8"] = {"status": "concluido", "erro": None, "resultado": {"loja_hub": "Loja X", "turno": "noite", "rotas": [
        {"id": 1, "motorista_id": banco.ana, "qtd_pedidos": 3, "km_total": 10.5, "setores": ["NE", "N"]},
        {"id": 2, "motorista_id": banco.beto, "qtd_pedidos": 2, "km_total": 4.0, "setores": ["S"]},
    ]}}
    r = cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "exec8", "turno": "manha"})  # o corpo não manda: vale o do resultado
    assert r.status_code == 200 and r.json()["novas"] == 2
    linhas = banco.db.execute("SELECT numero_rota, turno, setores FROM rotas_realizadas ORDER BY numero_rota").fetchall()
    assert [tuple(l) for l in linhas] == [(1, "noite", "N,NE"), (2, "noite", "S")]
    main.JOBS.pop("exec8")


def test_confirmar_resultado_antigo_sem_turno_usa_o_do_corpo_e_setores_vazios(api):
    cliente, banco = api
    main.JOBS["exec8b"] = {"status": "concluido", "erro": None, "resultado": {"loja_hub": "Loja X", "rotas": [{"id": 1, "motorista_id": banco.ana, "qtd_pedidos": 1, "km_total": 1}]}}
    assert cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "exec8b", "turno": "tarde"}).status_code == 200
    assert tuple(banco.db.execute("SELECT turno, setores FROM rotas_realizadas").fetchone()) == ("tarde", None)
    main.JOBS.pop("exec8b")


def _migracao():
    caminho = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0010_rotas_realizadas_setores.py"
    spec = importlib.util.spec_from_file_location("migracao_0010", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_migration_0010_e_idempotente_e_nao_apaga_nada():
    modulo = _migracao()
    assert modulo.revision == "0010" and modulo.down_revision == "0009"
    texto = " ".join(modulo.COMANDOS).upper()
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE)\b", texto) and "ADD COLUMN IF NOT EXISTS SETORES TEXT" in texto
    banco = criar_banco_sqlite()  # já aplicou a 0010 uma vez (a coluna existe); rodar de novo não pode quebrar nem mexer nos dados
    banco.inserir_motorista("Ana", CARRO)
    banco.db.execute("INSERT INTO rotas_realizadas (execucao_id, numero_rota, motorista_id, data) VALUES ('e', 1, 1, '2026-10-21')")
    colunas = {l[1] for l in banco.db.execute("PRAGMA table_info(rotas_realizadas)")}
    assert "setores" in colunas and banco.db.execute("SELECT setores FROM rotas_realizadas").fetchone()[0] is None  # rotas antigas: NULL
    assert not banco.db.execute("SELECT count(*) FROM rotas_realizadas WHERE setores IS NOT NULL").fetchone()[0]


def test_migration_0010_sql_para_o_postgres():
    assert _migracao().COMANDOS == ["ALTER TABLE rotas_realizadas ADD COLUMN IF NOT EXISTS setores TEXT"]


def test_nenhum_dado_de_pedido_em_log_aviso_ou_erro(monkeypatch, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    frota_usar = [main.MotoristaItem(id=1, motorista="Ana", modal=CARRO, custo_rota=130.0), main.MotoristaItem(id=2, motorista="Beto", modal=CARRO, custo_rota=130.0)]
    contexto = {"turno": "manha", "tempo_por_parada_min": 10, "rotas_hoje": {}, "proibidos": {1: {"N": ["tarde"]}, 2: {"N": ["tarde"]}}}
    r = _rodar_job(monkeypatch, _cluster("N", 4) + _cluster("S", 2), frota_usar, contexto, {CARRO: {"capacidade": 2}})
    saida = capsys.readouterr().out + caplog.text
    avisos = json.dumps(r["avisos"], ensure_ascii=False) + json.dumps(r["parametros"], ensure_ascii=False)
    for segredo in ("Rua Reservada", "Bairro Secreto", "01310100"):
        assert segredo not in saida and segredo not in avisos
    # erro do cálculo: só a classe (já coberto antes) e nada de endereço
    async def quebra(lista):
        raise RuntimeError("falha em Rua Reservada 1")

    monkeypatch.setattr(main, "geocodificar_lote", quebra)
    pedidos, _ = _pedidos_do_job(_cluster("N", 2))
    req = main.OtimizarRequest(origem_rua="Av Paulista", origem_num="1", pedidos=pedidos)
    main.JOBS["t8e"] = {"status": "em_andamento", "etapa": "", "atual": 0, "total": 1, "resultado": None, "erro": None}
    _rodar(main._processar_otimizacao("t8e", req, frota_usar, {}, None, {"turno": "manha"}))
    job = main.JOBS.pop("t8e")
    assert job["status"] == "erro" and "Rua Reservada" not in job["erro"] and "Rua Reservada" not in capsys.readouterr().out


def test_fluxo_do_job_continua_com_post_e_status(api, monkeypatch):
    cliente, banco = api
    pedidos, coordenadas = _pedidos_do_job(_cluster("L", 3) + _cluster("O", 3))
    _geocodificar_por_id(monkeypatch, coordenadas)
    criados = []

    def agenda(corotina):  # o TestClient encerra o laço de eventos junto com a resposta: aqui só se confere que o job nasce e é consultável
        criados.append(corotina)
        corotina.close()

    monkeypatch.setattr(main.asyncio, "create_task", agenda)
    r = cliente.post("/api/otimizar", json={"origem_rua": "Av Paulista", "origem_num": "1", "turno": "manha", "pedidos": pedidos,
                                           "motorista_ids": [banco.ana, banco.beto], "modais_config": {CARRO: {"capacidade": 5}}})
    assert r.status_code == 200 and r.json()["job_id"] and len(criados) == 1
    status = cliente.get(f"/api/otimizar/status/{r.json()['job_id']}").json()
    assert status["status"] == "em_andamento" and set(status) >= {"status", "etapa", "atual", "total"}
    assert cliente.get("/api/otimizar/status/inexistente").status_code == 404


# ----------------------------------------------------------------------------------------------------------
# Desempenho (10, 20 e 40 pedidos) e o servidor continua respondendo durante o cálculo
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n, motoristas", [(10, 3), (20, 3), (40, 4)])
def test_desempenho_com_10_20_e_40_pedidos(n, motoristas, capsys):
    mots = [Mot(i + 1, f"M{i + 1}", CARRO) for i in range(motoristas)]
    inicio = time.monotonic()
    plano = _executar(_pedidos(_aleatorios(n, semente=n)), mots, limite_s=None)
    decorrido = time.monotonic() - inicio
    limite = solver.limite_de_tempo(n)
    with capsys.disabled():
        print(f"\n[desempenho] {n} pedidos, {motoristas} motoristas: {decorrido:.2f} s (limite do solver {limite:.1f} s, método {plano['metodo']})")
    assert sum(len(v["pedidos"]) for v in plano["viagens"]) == n
    assert decorrido <= limite + 3.0  # o limite do solver vale: nunca estoura o tempo
    assert plano["metodo"] == "ortools"


def test_o_servidor_continua_respondendo_enquanto_o_solver_calcula():
    async def principal():
        batidas = []

        async def relogio():
            while True:
                batidas.append(time.monotonic())
                await asyncio.sleep(0.05)

        tarefa = asyncio.create_task(relogio())
        mots = [Mot(1, "A", CARRO), Mot(2, "B", CARRO), Mot(3, "C", CARRO)]

        async def obter(pontos):
            d, t = matriz.matriz_linha_reta(pontos)
            return {"distancias_m": d, "duracoes_s": t, "origem": "osrm", "aviso": None}

        await roteirizacao.executar(pedidos=_pedidos(_aleatorios(20)), hub=HUB, motoristas=mots, capacidades={CARRO: 8}, turno="manha",
                                    tempo_por_parada_min=10, rotas_hoje={}, proibidos={}, obter_matriz=obter, limite_s=2.0)
        tarefa.cancel()
        return batidas

    batidas = _rodar(principal())
    maior_pausa = max(b - a for a, b in zip(batidas, batidas[1:]))
    assert len(batidas) > 10 and maior_pausa < 1.0  # o laço de eventos não ficou travado durante os 2 s de cálculo
