"""Etapas 9 e 12: rotas_pedidos (gravada ao confirmar), retenção do endereço, controle de duplicidade, histórico e privacidade."""
import importlib.util
import logging
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config
import main
import rotas_realizadas as rr
from backend.tests.fakes_asyncpg import FakePool, criar_banco_sqlite

HOJE = date(2026, 10, 22)
OPERADOR = "Maria Souza (maria@zubale.com)"
OUTRO = "João Lima (joao@zubale.com)"


def _rodar(corotina):
    import asyncio
    return asyncio.run(corotina)


@pytest.fixture(autouse=True)
def _limpeza_zerada():
    rr._ULTIMA_LIMPEZA = None
    yield
    rr._ULTIMA_LIMPEZA = None


@pytest.fixture
def banco():
    b = criar_banco_sqlite()
    b.ana = b.inserir_motorista("Ana", "Carro de passeio")
    b.beto = b.inserir_motorista("Beto", "Carro de passeio")
    return b


def _pedidos(*ids, cidade="São Paulo", volume=1):
    return [{"ordem": i + 1, "pedido_id": p, "endereco": f"Rua {p}, {i + 10} - Centro", "cidade": cidade, "uf": "SP", "volume": volume} for i, p in enumerate(ids)]


def _rota(numero, motorista, pedidos, setores="N"):
    return {"numero_rota": numero, "motorista_id": motorista, "qtd_pedidos": len(pedidos), "distancia_km": 12.5, "setores": setores, "pedidos": pedidos}


def _confirmar(banco, execucao, rotas, dia=HOJE, loja="Atacadão Mooca", turno="manha", operador=OPERADOR):
    return _rodar(rr.confirmar(banco, execucao, rotas, dia, loja, turno, operador))


def _contar(banco, tabela="rotas_pedidos"):
    return banco.db.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]


def _linhas(banco):
    return [dict(l) for l in banco.db.execute("SELECT * FROM rotas_pedidos ORDER BY rota_id, ordem")]


# ----------------------------------------------------------------------------------------------------------
# Gravação ao confirmar (mínimo de dados) e sem duplicar
# ----------------------------------------------------------------------------------------------------------
def test_confirmar_grava_os_pedidos_de_cada_rota_so_com_o_minimo(banco):
    _confirmar(banco, "e1", [_rota(1, banco.ana, _pedidos("P1", "P2", volume=3)), _rota(2, banco.beto, _pedidos("P3"))])
    linhas = _linhas(banco)
    assert [(l["ordem"], l["pedido_id"], l["endereco"], l["cidade"], l["uf"], l["volume"], l["endereco_apagado_em"]) for l in linhas] == [
        (1, "P1", "Rua P1, 10 - Centro", "São Paulo", "SP", 3, None), (2, "P2", "Rua P2, 11 - Centro", "São Paulo", "SP", 3, None),
        (1, "P3", "Rua P3, 10 - Centro", "São Paulo", "SP", 1, None),
    ]
    assert linhas[0]["rota_id"] == linhas[1]["rota_id"] != linhas[2]["rota_id"]
    colunas = {l[1] for l in banco.db.execute("PRAGMA table_info(rotas_pedidos)")}
    assert colunas == {"id", "rota_id", "ordem", "pedido_id", "endereco", "cidade", "uf", "volume", "endereco_apagado_em"}  # nunca cliente, telefone nem CEP


def test_confirmar_duas_vezes_nao_duplica_os_pedidos(banco):
    rotas = [_rota(1, banco.ana, _pedidos("P1", "P2"))]
    _confirmar(banco, "e1", rotas)
    antes = _linhas(banco)
    r = _confirmar(banco, "e1", rotas)
    assert r["ja_confirmada"] and _linhas(banco) == antes and _contar(banco) == 2


def test_desfazer_mantem_os_pedidos_ligados_a_rota_cancelada_e_reconfirmar_nao_duplica(banco):
    _confirmar(banco, "e1", [_rota(1, banco.ana, _pedidos("P1", "P2"))])
    _rodar(rr.desfazer(banco, "e1", HOJE))
    assert _contar(banco) == 2
    assert banco.db.execute("SELECT status FROM rotas_realizadas").fetchone()[0] == "cancelada"
    _confirmar(banco, "e1", [_rota(1, banco.ana, _pedidos("P1", "P2"))])
    assert _contar(banco) == 2 and banco.db.execute("SELECT status FROM rotas_realizadas").fetchone()[0] == "confirmada"


def test_rota_confirmada_antes_desta_etapa_ganha_o_detalhe_ao_confirmar_de_novo(banco):
    _confirmar(banco, "velha", [{"numero_rota": 1, "motorista_id": banco.ana, "qtd_pedidos": 2, "distancia_km": 3, "setores": "N"}])  # sem pedidos
    assert _contar(banco) == 0
    _confirmar(banco, "velha", [_rota(1, banco.ana, _pedidos("P1", "P2"))])
    assert _contar(banco) == 2


def test_pedidos_com_dados_sujos_sao_normalizados_ou_ignorados(banco):
    sujos = [{"ordem": 1, "pedido_id": "  A1  ", "endereco": "  Rua   Um,  5 ", "cidade": " Santos ", "uf": "sp", "volume": "2"},
             {"ordem": 2, "pedido_id": "", "endereco": "sem id"}, {"ordem": 3, "pedido_id": "X" * 80, "endereco": None, "cidade": None, "uf": None, "volume": "abc"}]
    _confirmar(banco, "e1", [_rota(1, banco.ana, sujos)])
    linhas = _linhas(banco)
    assert [(l["pedido_id"], l["endereco"], l["cidade"], l["uf"], l["volume"]) for l in linhas] == [
        ("A1", "Rua Um, 5", "Santos", "SP", 2), ("X" * 60, None, None, None, 1)]


def test_a_api_confirma_com_os_pedidos_do_resultado_sem_cliente_nem_cep(monkeypatch, banco):
    paradas = [{"id": "P1", "Endereco": "Rua Secreta", "Numero": "10", "Bairro": "Bairro X", "Cidade": "Santos", "UF": "SP", "Volume": 2, "CEP": "01310100",
                "Cliente": "Fulano Segredoso", "Telefone": "11999990000", "ordem": 1},
               {"id": "P2", "Endereco": "Rua Dois", "Numero": "S/N", "Bairro": "", "Cidade": "Santos", "UF": "SP", "Volume": 1, "CEP": "01310200", "ordem": 2}]

    async def get_pool():
        return FakePool(banco)

    class Op:
        nome, email = "Maria Souza", "maria@zubale.com"

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: Op()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    try:
        main.JOBS["api9"] = {"status": "concluido", "erro": None, "resultado": {"loja_hub": "Loja", "turno": "manha", "rotas": [
            {"id": 1, "motorista_id": banco.ana, "qtd_pedidos": 2, "km_total": 5, "setores": ["N"], "paradas": paradas}]}}
        r = TestClient(main.app).post("/api/rotas-realizadas/confirmar", json={"execucao_id": "api9"})
    finally:
        main.app.dependency_overrides.clear()
        main.JOBS.pop("api9", None)
    assert r.status_code == 200
    linhas = _linhas(banco)
    assert [(l["pedido_id"], l["endereco"], l["cidade"], l["uf"], l["volume"]) for l in linhas] == [
        ("P1", "Rua Secreta, 10 - Bairro X", "Santos", "SP", 2), ("P2", "Rua Dois, S/N", "Santos", "SP", 1)]
    tudo = str([tuple(l) for l in banco.db.execute("SELECT * FROM rotas_pedidos")])
    for segredo in ("Fulano", "11999990000", "01310100", "01310200"):
        assert segredo not in tudo


# ----------------------------------------------------------------------------------------------------------
# Retenção do endereço
# ----------------------------------------------------------------------------------------------------------
def _rota_de(banco, dia, execucao, motorista=None, pedidos=("P1",), status="confirmada"):
    _confirmar(banco, execucao, [_rota(1, motorista or banco.ana, _pedidos(*pedidos))], dia=dia)
    if status == "cancelada":
        _rodar(rr.desfazer(banco, execucao, dia))


def test_endereco_nao_e_apagado_antes_do_prazo_e_e_apagado_depois(banco):
    _rota_de(banco, HOJE - timedelta(days=89), "d89", pedidos=("A",))
    _rota_de(banco, HOJE - timedelta(days=90), "d90", pedidos=("B",))  # exatamente 90 dias: ainda não passou do prazo
    _rota_de(banco, HOJE - timedelta(days=91), "d91", pedidos=("C",))
    _rota_de(banco, HOJE - timedelta(days=400), "d400", pedidos=("D",))
    assert _rodar(rr.limpar_enderecos_antigos(banco, HOJE, 90)) == 2
    por_id = {l["pedido_id"]: l for l in _linhas(banco)}
    assert por_id["A"]["endereco"] and por_id["B"]["endereco"]
    assert por_id["C"]["endereco"] is None and por_id["D"]["endereco"] is None
    assert str(por_id["C"]["endereco_apagado_em"]) == "2026-10-22" and por_id["A"]["endereco_apagado_em"] is None


def test_a_limpeza_apaga_so_o_endereco_e_mantem_o_resto(banco):
    _rota_de(banco, HOJE - timedelta(days=120), "velha", pedidos=("P1", "P2"))
    _rodar(rr.limpar_enderecos_antigos(banco, HOJE, 90))
    for l in _linhas(banco):
        assert l["endereco"] is None and l["pedido_id"] in ("P1", "P2") and l["cidade"] == "São Paulo" and l["uf"] == "SP" and l["volume"] == 1
    rota = dict(banco.db.execute("SELECT * FROM rotas_realizadas").fetchone())
    assert (rota["motorista_id"], rota["loja_hub"], rota["turno"], rota["qtd_pedidos"], rota["distancia_km"], rota["status"]) == (banco.ana, "Atacadão Mooca", "manha", 2, 12.5, "confirmada")
    assert str(rota["data"]) == str(HOJE - timedelta(days=120))


def test_a_limpeza_e_idempotente_e_alcanca_rotas_desfeitas(banco):
    _rota_de(banco, HOJE - timedelta(days=100), "desfeita", pedidos=("P1",), status="cancelada")
    assert _rodar(rr.limpar_enderecos_antigos(banco, HOJE, 90)) == 1
    assert _rodar(rr.limpar_enderecos_antigos(banco, HOJE, 90)) == 0  # a segunda vez não faz nada
    assert _linhas(banco)[0]["endereco"] is None


def test_o_prazo_e_configuravel(banco):
    _rota_de(banco, HOJE - timedelta(days=40), "d40", pedidos=("P1",))
    assert _rodar(rr.limpar_enderecos_antigos(banco, HOJE, 90)) == 0
    assert _rodar(rr.limpar_enderecos_antigos(banco, HOJE, 30)) == 1


def test_historico_dias_vem_da_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv("HISTORICO_DIAS", "30")
    assert config._dias_do_historico() == 30
    for ruim in ("abc", "0", "-5", ""):
        monkeypatch.setenv("HISTORICO_DIAS", ruim)
        assert config._dias_do_historico() == 90
    monkeypatch.delenv("HISTORICO_DIAS")
    assert config._dias_do_historico() == 90 and config.HISTORICO_DIAS >= 1


def test_a_limpeza_preguicosa_roda_no_maximo_uma_vez_por_dia(banco):
    _rota_de(banco, HOJE - timedelta(days=100), "a", pedidos=("A",))
    assert _rodar(rr.limpeza_preguicosa(banco, HOJE, 90)) == 1
    _rota_de(banco, HOJE - timedelta(days=95), "b", pedidos=("B",))
    assert _rodar(rr.limpeza_preguicosa(banco, HOJE, 90)) == 0  # já rodou hoje: não repete
    assert {l["pedido_id"]: l["endereco"] is None for l in _linhas(banco)} == {"A": True, "B": False}
    assert _rodar(rr.limpeza_preguicosa(banco, HOJE + timedelta(days=1), 90)) == 1  # no dia seguinte roda de novo


def test_falha_na_limpeza_nao_derruba_quem_chamou_nem_vaza_dados(capsys):
    class ConexaoQuebrada:
        async def fetch(self, *a, **k):
            raise RuntimeError("falha em Rua Secreta 10")

    assert _rodar(rr.limpeza_preguicosa(ConexaoQuebrada(), HOJE, 90)) == 0
    saida = capsys.readouterr().out
    assert "RuntimeError" in saida and "Rua Secreta" not in saida
    assert rr._ULTIMA_LIMPEZA is None  # não marca como feita: tenta de novo na próxima


# ----------------------------------------------------------------------------------------------------------
# Duplicidade (Etapa 9)
# ----------------------------------------------------------------------------------------------------------
def test_pedido_em_rota_confirmada_hoje_aparece_com_todos_os_dados(banco):
    _confirmar(banco, "e1", [_rota(1, banco.ana, _pedidos("P1", "P2")), _rota(2, banco.beto, _pedidos("P3"))], turno="tarde", loja="Atacadão Mooca")
    banco.db.execute("UPDATE rotas_realizadas SET criado_em = '2026-10-22 15:30:00'")  # UTC; em Brasília são 12:30
    achados = _rodar(rr.ja_roteirizados(banco, ["P1", "P3", "NAO-EXISTE"], HOJE))
    assert achados == {
        "P1": {"rota": 1, "motorista": "Ana", "turno": "tarde", "loja": "Atacadão Mooca", "operador": "Maria Souza", "hora": "12:30"},
        "P3": {"rota": 2, "motorista": "Beto", "turno": "tarde", "loja": "Atacadão Mooca", "operador": "Maria Souza", "hora": "12:30"},
    }
    assert "maria@zubale.com" not in str(achados)


def test_rota_cancelada_outro_dia_e_id_inexistente_nao_aparecem(banco):
    _confirmar(banco, "cancelada", [_rota(1, banco.ana, _pedidos("C1"))])
    _rodar(rr.desfazer(banco, "cancelada", HOJE))
    _confirmar(banco, "ontem", [_rota(1, banco.ana, _pedidos("O1"))], dia=HOJE - timedelta(days=1))
    _confirmar(banco, "amanha", [_rota(1, banco.ana, _pedidos("A1"))], dia=HOJE + timedelta(days=1))
    _confirmar(banco, "hoje", [_rota(1, banco.ana, _pedidos("H1"))])
    assert set(_rodar(rr.ja_roteirizados(banco, ["C1", "O1", "A1", "H1", "ZZ"], HOJE))) == {"H1"}
    assert _rodar(rr.ja_roteirizados(banco, [], HOJE)) == {} and _rodar(rr.ja_roteirizados(banco, ["", None, "  "], HOJE)) == {}


def test_reconfirmar_uma_rota_desfeita_volta_a_aparecer(banco):
    _confirmar(banco, "e1", [_rota(1, banco.ana, _pedidos("P1"))])
    _rodar(rr.desfazer(banco, "e1", HOJE))
    assert _rodar(rr.ja_roteirizados(banco, ["P1"], HOJE)) == {}
    _confirmar(banco, "e1", [_rota(1, banco.ana, _pedidos("P1"))])
    assert "P1" in _rodar(rr.ja_roteirizados(banco, ["P1"], HOJE))


def test_pedido_em_duas_rotas_confirmadas_hoje_vale_a_mais_recente(banco):
    _confirmar(banco, "e1", [_rota(1, banco.ana, _pedidos("P1"))], turno="manha")
    _confirmar(banco, "e2", [_rota(1, banco.beto, _pedidos("P1"))], turno="tarde", operador=OUTRO)
    banco.db.execute("UPDATE rotas_realizadas SET criado_em = '2026-10-22 11:00:00' WHERE execucao_id = 'e1'")
    banco.db.execute("UPDATE rotas_realizadas SET criado_em = '2026-10-22 17:00:00' WHERE execucao_id = 'e2'")
    achado = _rodar(rr.ja_roteirizados(banco, ["P1"], HOJE))["P1"]
    assert (achado["motorista"], achado["turno"], achado["operador"], achado["hora"]) == ("Beto", "tarde", "João Lima", "14:00")


def test_consulta_de_duplicidade_com_muitos_ids_em_blocos(banco):
    _confirmar(banco, "e1", [_rota(1, banco.ana, _pedidos("P7", "P900", "P1499"))])
    ids = [f"P{i}" for i in range(1500)]
    assert set(_rodar(rr.ja_roteirizados(banco, ids, HOJE))) == {"P7", "P900", "P1499"}


# ----------------------------------------------------------------------------------------------------------
# Histórico (Etapa 12)
# ----------------------------------------------------------------------------------------------------------
def _hist(banco, **kw):
    kw.setdefault("de", HOJE - timedelta(days=6))
    kw.setdefault("ate", HOJE)
    return _rodar(rr.historico(banco, **kw))


@pytest.fixture
def varias(banco):
    _confirmar(banco, "h1", [_rota(1, banco.ana, _pedidos("A1", "A2")), _rota(2, banco.beto, _pedidos("A3"))], loja="Atacadão Mooca", turno="manha")
    _confirmar(banco, "h2", [_rota(1, banco.ana, _pedidos("B1"))], loja="Sam's Club Campinas", turno="tarde", operador=OUTRO)
    _confirmar(banco, "ont", [_rota(1, banco.beto, _pedidos("C1", "C2"))], dia=HOJE - timedelta(days=1), loja="Atacadão Mooca", turno="noite")
    _confirmar(banco, "velha", [_rota(1, banco.ana, _pedidos("D1"))], dia=HOJE - timedelta(days=10), loja="Atacadão Mooca")
    banco.db.execute("UPDATE rotas_realizadas SET criado_em = '2026-10-22 13:00:00' WHERE execucao_id = 'h1'")
    banco.db.execute("UPDATE rotas_realizadas SET criado_em = '2026-10-22 18:00:00' WHERE execucao_id = 'h2'")
    return banco


def test_historico_vem_do_dia_mais_recente_para_o_mais_antigo_por_loja_e_hora(varias):
    h = _hist(varias)
    assert [(r["dia"], r["loja"], r["numero"], r["motorista"]["nome"]) for r in h["rotas"]] == [
        ("2026-10-22", "Atacadão Mooca", 1, "Ana"), ("2026-10-22", "Atacadão Mooca", 2, "Beto"), ("2026-10-22", "Sam's Club Campinas", 1, "Ana"),
        ("2026-10-21", "Atacadão Mooca", 1, "Beto"),
    ]  # a rota de 10 dias atrás fica fora do período padrão de 7 dias
    primeira = h["rotas"][0]
    assert primeira["turno"] == "manha" and primeira["hora"] == "10:00" and primeira["qtd_pedidos"] == 2 and primeira["km"] == 12.5 and primeira["status"] == "confirmada"
    assert [(p["ordem"], p["id"], p["endereco"], p["cidade"]) for p in primeira["pedidos"]] == [(1, "A1", "Rua A1, 10 - Centro", "São Paulo"), (2, "A2", "Rua A2, 11 - Centro", "São Paulo")]
    assert h["tem_mais"] is False and primeira["sem_detalhe"] is False


def test_periodo_padrao_e_os_filtros_de_periodo(varias):
    assert rr.periodo_padrao(HOJE) == (HOJE - timedelta(days=6), HOJE)
    assert len(_hist(varias, de=HOJE - timedelta(days=30))["rotas"]) == 5
    assert [r["dia"] for r in _hist(varias, de=HOJE - timedelta(days=1), ate=HOJE - timedelta(days=1))["rotas"]] == ["2026-10-21"]
    assert _hist(varias, de=HOJE + timedelta(days=1), ate=HOJE + timedelta(days=2))["rotas"] == []


def test_filtros_por_loja_motorista_e_operador(varias):
    assert {r["loja"] for r in _hist(varias, loja="Sam's Club Campinas")["rotas"]} == {"Sam's Club Campinas"}
    assert {r["motorista"]["nome"] for r in _hist(varias, motorista_id=varias.beto)["rotas"]} == {"Beto"}
    assert [r["operador"] for r in _hist(varias, operador="João Lima")["rotas"]] == ["João Lima"]
    assert len(_hist(varias, operador="maria souza")["rotas"]) == 3  # sem diferença de maiúsculas
    assert _hist(varias, operador="maria@zubale.com")["rotas"] == []  # o e-mail não é filtro (e nunca aparece)
    assert _hist(varias, operador="Fulano")["rotas"] == []
    assert len(_hist(varias, loja="Atacadão Mooca", motorista_id=varias.ana)["rotas"]) == 1


def test_busca_por_id_exato_e_por_trecho_do_endereco(varias):
    assert [r["numero"] for r in _hist(varias, q="a3")["rotas"]] == [2]  # id exato, sem diferença de maiúsculas
    assert _hist(varias, q="zzz")["rotas"] == []  # nem id nem trecho de endereço    assert {r["dia"] for r in _hist(varias, q="rua c1")["rotas"]} == {"2026-10-21"}  # trecho do endereço
    assert len(_hist(varias, q="centro")["rotas"]) == 4  # todas as rotas do período têm "Centro" no endereço
    assert _hist(varias, q="100%")["rotas"] == []  # curingas do LIKE não funcionam como curinga


def test_paginacao_com_carregar_mais(varias):
    p1 = _hist(varias, limite=3)
    assert len(p1["rotas"]) == 3 and p1["tem_mais"] is True
    p2 = _hist(varias, limite=3, deslocamento=3)
    assert len(p2["rotas"]) == 1 and p2["tem_mais"] is False
    assert [r["id"] for r in p1["rotas"] + p2["rotas"]] == [r["id"] for r in _hist(varias)["rotas"]]


def test_rotas_desfeitas_so_aparecem_quando_pedido(varias):
    _rodar(rr.desfazer(varias, "h2", HOJE))
    assert all(r["status"] == "confirmada" for r in _hist(varias)["rotas"]) and len(_hist(varias)["rotas"]) == 3
    com = _hist(varias, desfeitas=True)["rotas"]
    assert len(com) == 4 and [r["status"] for r in com if r["loja"] == "Sam's Club Campinas"] == ["cancelada"]
    assert [p["id"] for r in com if r["status"] == "cancelada" for p in r["pedidos"]] == ["B1"]  # os pedidos ficam ligados à rota cancelada


def test_rota_confirmada_antes_desta_etapa_vem_sem_detalhe(banco):
    _confirmar(banco, "velha", [{"numero_rota": 1, "motorista_id": banco.ana, "qtd_pedidos": 4, "distancia_km": 3, "setores": "N"}])
    r = _hist(banco)["rotas"][0]
    assert r["sem_detalhe"] is True and r["pedidos"] == [] and r["qtd_pedidos"] == 4


def test_endereco_removido_depois_do_prazo_mantem_id_e_cidade(banco):
    _confirmar(banco, "antiga", [_rota(1, banco.ana, _pedidos("P1", cidade="Santos"))], dia=HOJE - timedelta(days=95))
    _rodar(rr.limpar_enderecos_antigos(banco, HOJE, 90))
    r = _hist(banco, de=HOJE - timedelta(days=200))["rotas"][0]
    assert r["sem_detalhe"] is False
    assert r["pedidos"] == [{"ordem": 1, "id": "P1", "endereco": None, "endereco_apagado": True, "cidade": "Santos", "uf": "SP", "volume": 1}]
    assert _hist(banco, de=HOJE - timedelta(days=200), q="Rua P1")["rotas"] == []  # o endereço apagado não é mais pesquisável; o id continua
    assert len(_hist(banco, de=HOJE - timedelta(days=200), q="P1")["rotas"]) == 1


def test_historico_nunca_traz_cliente_telefone_cep_nem_email(varias):
    texto = str(_hist(varias, desfeitas=True)) + str(_rodar(rr.filtros_do_historico(varias, HOJE - timedelta(days=30), HOJE)))
    assert "@" not in texto and "zubale.com" not in texto
    for r in _hist(varias)["rotas"]:
        assert set(r) == {"id", "dia", "loja", "motorista", "numero", "turno", "hora", "qtd_pedidos", "km", "status", "operador", "sem_detalhe", "pedidos"}
        for p in r["pedidos"]:
            assert set(p) == {"ordem", "id", "endereco", "endereco_apagado", "cidade", "uf", "volume"}


def test_filtros_do_historico(varias):
    f = _rodar(rr.filtros_do_historico(varias, HOJE - timedelta(days=30), HOJE))
    assert f["lojas"] == ["Atacadão Mooca", "Sam's Club Campinas"] and f["operadores"] == ["João Lima", "Maria Souza"]
    assert [m["nome"] for m in f["motoristas"]] == ["Ana", "Beto"]
    assert _rodar(rr.filtros_do_historico(varias, HOJE - timedelta(days=1), HOJE - timedelta(days=1)))["lojas"] == ["Atacadão Mooca"]


def test_nome_do_operador_e_hora_em_brasilia():
    assert rr.nome_do_operador("Maria Souza (maria@zubale.com)") == "Maria Souza" and rr.nome_do_operador("Sem Email") == "Sem Email"
    assert rr.nome_do_operador("Maria (Zé) Souza (maria@zubale.com)") == "Maria (Zé) Souza" and rr.nome_do_operador(None) is None
    assert rr.hora_em_brasilia("2026-10-22 15:30:00") == "12:30" and rr.hora_em_brasilia("2026-10-22T02:59:00+00:00") == "23:59"
    assert rr.hora_em_brasilia(None) is None and rr.hora_em_brasilia("lixo") is None


# ----------------------------------------------------------------------------------------------------------
# API: login, validações e privacidade
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


def test_as_rotas_novas_exigem_login():
    main.app.dependency_overrides.clear()
    cliente = TestClient(main.app)
    assert cliente.post("/api/pedidos/ja-roteirizados", json={"ids": ["1"]}).status_code == 401
    assert cliente.get("/api/historico").status_code == 401
    assert cliente.get("/api/historico/filtros").status_code == 401


def test_api_ja_roteirizados(api):
    cliente, banco = api
    dia = rr.hoje_em_brasilia()
    _confirmar(banco, "api", [_rota(1, banco.ana, _pedidos("P1", "P2"))], dia=dia)
    r = cliente.post("/api/pedidos/ja-roteirizados", json={"ids": ["P1", "ZZ", 5]})
    assert r.status_code == 200 and r.json()["data"] == dia.isoformat() and set(r.json()["pedidos"]) == {"P1"}
    assert r.json()["pedidos"]["P1"]["motorista"] == "Ana" and r.json()["pedidos"]["P1"]["operador"] == "Maria Souza"
    assert cliente.post("/api/pedidos/ja-roteirizados", json={"ids": []}).json()["pedidos"] == {}
    assert cliente.post("/api/pedidos/ja-roteirizados", json={"ids": list(range(20001))}).status_code == 422


def test_api_historico_padrao_filtros_e_datas_invalidas(api):
    cliente, banco = api
    dia = rr.hoje_em_brasilia()
    _confirmar(banco, "api1", [_rota(1, banco.ana, _pedidos("P1", "P2"))], dia=dia, loja="Loja A")
    _confirmar(banco, "api2", [_rota(1, banco.beto, _pedidos("P3"))], dia=dia - timedelta(days=3), loja="Loja B", operador=OUTRO)
    _confirmar(banco, "api3", [_rota(1, banco.beto, _pedidos("P4"))], dia=dia - timedelta(days=20), loja="Loja B")
    h = cliente.get("/api/historico").json()
    assert h["hoje"] == dia.isoformat() and h["dias_retencao"] == config.HISTORICO_DIAS and h["de"] == (dia - timedelta(days=6)).isoformat() and h["ate"] == dia.isoformat()
    assert [r["loja"] for r in h["rotas"]] == ["Loja A", "Loja B"] and h["tem_mais"] is False
    assert [r["loja"] for r in cliente.get("/api/historico", params={"loja": "Loja A"}).json()["rotas"]] == ["Loja A"]
    assert [r["operador"] for r in cliente.get("/api/historico", params={"operador_nome": "João Lima"}).json()["rotas"]] == ["João Lima"]
    assert len(cliente.get("/api/historico", params={"de": (dia - timedelta(days=30)).isoformat()}).json()["rotas"]) == 3
    assert [r["numero"] for r in cliente.get("/api/historico", params={"q": "p3"}).json()["rotas"]] == [1]
    assert cliente.get("/api/historico", params={"de": "ontem"}).status_code == 422
    assert cliente.get("/api/historico", params={"de": dia.isoformat(), "ate": (dia - timedelta(days=1)).isoformat()}).status_code == 422
    f = cliente.get("/api/historico/filtros").json()
    assert f["lojas"] == ["Loja A", "Loja B"] and f["operadores"] == ["João Lima", "Maria Souza"]


def test_abrir_o_historico_dispara_a_limpeza_preguicosa(api):
    cliente, banco = api
    dia = rr.hoje_em_brasilia()
    _confirmar(banco, "velha", [_rota(1, banco.ana, _pedidos("P1"))], dia=dia - timedelta(days=100))
    h = cliente.get("/api/historico", params={"de": (dia - timedelta(days=200)).isoformat()}).json()
    assert h["rotas"][0]["pedidos"][0]["endereco"] is None and h["rotas"][0]["pedidos"][0]["endereco_apagado"] is True


def test_confirmar_pela_api_tambem_dispara_a_limpeza_preguicosa(api):
    cliente, banco = api
    dia = rr.hoje_em_brasilia()
    _confirmar(banco, "velha", [_rota(1, banco.ana, _pedidos("P1"))], dia=dia - timedelta(days=100))
    main.JOBS["api-nova"] = {"status": "concluido", "erro": None, "resultado": {"loja_hub": "L", "turno": "manha", "rotas": [
        {"id": 1, "motorista_id": banco.beto, "qtd_pedidos": 1, "km_total": 1, "setores": ["N"], "paradas": [{"id": "N1", "Endereco": "Rua Nova", "Numero": "1", "Bairro": "B", "Cidade": "Santos", "UF": "SP", "Volume": 1, "ordem": 1}]}]}}
    try:
        assert cliente.post("/api/rotas-realizadas/confirmar", json={"execucao_id": "api-nova"}).status_code == 200
    finally:
        main.JOBS.pop("api-nova", None)
    por_id = {l["pedido_id"]: l["endereco"] for l in _linhas(banco)}
    assert por_id["P1"] is None and por_id["N1"] == "Rua Nova, 1 - B"


def test_nenhum_endereco_ou_id_de_pedido_em_log_ou_mensagem_de_erro(api, caplog, capsys):
    cliente, banco = api
    caplog.set_level(logging.DEBUG)
    dia = rr.hoje_em_brasilia()
    _confirmar(banco, "priv", [_rota(1, banco.ana, [{"ordem": 1, "pedido_id": "ID-SECRETO-77", "endereco": "Rua Sigilosa 999 - Bairro Escondido", "cidade": "Cidade X", "uf": "SP", "volume": 1}])], dia=dia)
    respostas = [
        cliente.post("/api/pedidos/ja-roteirizados", json={"ids": ["ID-SECRETO-77"]}),
        cliente.get("/api/historico", params={"q": "Rua Sigilosa"}),
        cliente.get("/api/historico", params={"q": "ID-SECRETO-77"}),
        cliente.get("/api/historico", params={"de": "Rua Sigilosa 999"}),  # 422: a mensagem não pode repetir o valor recebido
    ]
    assert respostas[3].status_code == 422 and "Sigilosa" not in respostas[3].text
    saida = capsys.readouterr().out + caplog.text
    for segredo in ("ID-SECRETO-77", "Rua Sigilosa", "Bairro Escondido"):
        assert segredo not in saida


def test_migration_0011_e_idempotente_e_nao_apaga_nada():
    caminho = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0011_rotas_pedidos.py"
    spec = importlib.util.spec_from_file_location("migracao_0011", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.revision == "0011" and modulo.down_revision == "0010"
    texto = " ".join(modulo.COMANDOS).upper()
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE)\b", texto) and all("IF NOT EXISTS" in c.upper() for c in modulo.COMANDOS)
    assert "REFERENCES ROTAS_REALIZADAS (ID)" in texto and "UX_ROTAS_PEDIDOS_ROTA_ORDEM" in texto and "ENDERECO_APAGADO_EM DATE" in texto
    assert "CLIENTE" not in texto and "TELEFONE" not in texto and "CEP" not in texto
    banco = criar_banco_sqlite()  # a 0011 já foi aplicada uma vez; rodar os índices de novo não pode quebrar
    for comando in modulo.COMANDOS[1:]:
        banco.db.execute(comando)
    assert _contar(banco) == 0
