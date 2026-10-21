"""Etapa 5: tipos de veículo (custo por rota, peso de referência opcional) e motoristas (CRUD, desativar, frota ativa)."""
import asyncio
import importlib.util
import re
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import frota
import main
from backend.tests.fakes_asyncpg import FakeConn, FakePool, criar_banco_sqlite

BACKEND = Path(__file__).resolve().parents[1]
ARQUIVO_MIGRACAO = BACKEND / "migrations" / "versions" / "0004_tipos_veiculo_motoristas.py"
AGORA = datetime(2026, 10, 13, 10, 0, 0)


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


def _tipo(id=1, nome="Carro de passeio", custo="130.00", peso=None):
    return {"id": id, "nome": nome, "custo_rota": Decimal(custo), "peso_referencia_kg": None if peso is None else Decimal(peso),
            "ativo": True, "atualizado_em": AGORA, "atualizado_por": "cadastro inicial (migration)"}


def _motorista(id=1, nome="João Silva", tipo="Carro de passeio", ativo=True, valor=None):
    return {"id": id, "nome": nome, "tipo_veiculo": tipo, "valor_rota": None if valor is None else Decimal(valor), "ativo": ativo, "atualizado_em": AGORA, "atualizado_por": "Maria Souza (maria@zubale.com)"}


@pytest.fixture
def api(monkeypatch):
    conn = FakeConn()

    async def get_pool():
        return FakePool(conn)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), conn
    main.app.dependency_overrides.clear()


def _rodar(corotina):
    return asyncio.run(corotina)


# ----------------------------------------------------------------------------------------------------------
# Valores
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("entrada, esperado", [(130, "130.00"), ("130", "130.00"), ("130,5", "130.50"), ("R$ 260", "260.00"),
                                               ("1.234,56", "1234.56"), (0, "0.00"), (130.456, "130.46")])
def test_custo_valido(entrada, esperado):
    assert frota.interpretar_custo_rota(entrada) == Decimal(esperado)


@pytest.mark.parametrize("entrada", [None, "", "  ", "abc", -1, "-5", True, 1e12, float("nan")])
def test_custo_invalido(entrada):
    with pytest.raises(ValueError):
        frota.interpretar_custo_rota(entrada)


def test_peso_de_referencia_e_opcional():
    assert frota.interpretar_peso_referencia(None) is None
    assert frota.interpretar_peso_referencia("") is None
    assert frota.interpretar_peso_referencia("  ") is None  # em branco = "sem referência"
    assert frota.interpretar_peso_referencia("300") == Decimal("300.000")
    assert frota.interpretar_peso_referencia("1,5 kg") == Decimal("1.500")


@pytest.mark.parametrize("entrada", [-1, "-10", 0, "0", "abc", 1e9])
def test_peso_de_referencia_negativo_zero_ou_texto_e_recusado(entrada):
    with pytest.raises(ValueError):
        frota.interpretar_peso_referencia(entrada)


def test_mensagens_em_linguagem_do_operador():
    termos = re.compile(r"sql|tabela|banco|api|json|token|null|constraint|asyncpg|migration|endpoint", re.IGNORECASE)
    textos = [frota.MSG_NOME_VAZIO, frota.MSG_NOME_GRANDE, frota.MSG_TIPO_INEXISTENTE, frota.MSG_SEM_MOTORISTAS]
    for entrada in (-1, "abc", None, ""):
        for funcao in (frota.interpretar_custo_rota, frota.interpretar_peso_referencia):
            try:
                funcao(entrada)
            except ValueError as erro:
                textos.append(str(erro))
    assert all(not termos.search(t) for t in textos), [t for t in textos if termos.search(t)]


def test_nome_do_motorista():
    assert frota.normalizar_nome_motorista("  João   da  Silva ") == "João da Silva"
    for ruim in (None, "", "   ", "x" * 121):
        with pytest.raises(ValueError):
            frota.normalizar_nome_motorista(ruim)


# ----------------------------------------------------------------------------------------------------------
# Rotas: tipos de veículo
# ----------------------------------------------------------------------------------------------------------
def test_listar_tipos_de_veiculo(api):
    cliente, conn = api
    conn.respostas = [[_tipo(1, "Carro de passeio", "130.00"), _tipo(2, "Fiorino/Utilitário", "260.00", "400")]]
    r = cliente.get("/api/tipos-veiculo")
    assert r.status_code == 200
    corpo = r.json()
    assert [(t["nome"], t["custo_rota"], t["peso_referencia_kg"]) for t in corpo] == [
        ("Carro de passeio", 130.0, None), ("Fiorino/Utilitário", 260.0, 400.0)]


def test_editar_custo_e_peso_de_referencia_registra_quem_alterou(api):
    cliente, conn = api
    conn.respostas = [_tipo(2, "Fiorino/Utilitário", "275.00", "400")]
    r = cliente.put("/api/tipos-veiculo/2", json={"custo_rota": "275", "peso_referencia_kg": "400"})
    assert r.status_code == 200 and r.json()["custo_rota"] == 275.0 and r.json()["peso_referencia_kg"] == 400.0
    sql, args = conn.chamadas[0][1], conn.chamadas[0][2]
    assert "UPDATE tipos_veiculo" in sql and "atualizado_em = NOW()" in sql and "atualizado_por" in sql
    assert args == (2, Decimal("275.00"), Decimal("400.000"), "Maria Souza (maria@zubale.com)")


def test_editar_tipo_com_peso_em_branco_vira_sem_referencia(api):
    cliente, conn = api
    conn.respostas = [_tipo(1)]
    assert cliente.put("/api/tipos-veiculo/1", json={"custo_rota": 130, "peso_referencia_kg": ""}).status_code == 200
    assert conn.chamadas[0][2][2] is None
    conn.respostas = [_tipo(1)]
    assert cliente.put("/api/tipos-veiculo/1", json={"custo_rota": 130}).status_code == 200
    assert conn.chamadas[1][2][2] is None


@pytest.mark.parametrize("corpo", [
    {"custo_rota": -10}, {"custo_rota": ""}, {"custo_rota": "abc"}, {}, {"custo_rota": 130, "peso_referencia_kg": -5},
    {"custo_rota": 130, "peso_referencia_kg": 0}, {"custo_rota": 130, "peso_referencia_kg": "pesado"},
])
def test_editar_tipo_com_valor_invalido_da_422_e_nao_grava(api, corpo):
    cliente, conn = api
    r = cliente.put("/api/tipos-veiculo/1", json=corpo)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str) and r.json()["detail"]
    assert conn.chamadas == []


def test_editar_tipo_inexistente_da_404(api):
    cliente, conn = api
    conn.respostas = [None]
    assert cliente.put("/api/tipos-veiculo/99", json={"custo_rota": 130}).status_code == 404


@pytest.mark.parametrize("corpo, trecho", [
    ({"nome": "", "tipo_veiculo": "Carro de passeio"}, "nome do motorista"),
    ({"nome": "   ", "tipo_veiculo": "Carro de passeio"}, "nome do motorista"),
    ({"tipo_veiculo": "Carro de passeio"}, "nome do motorista"),
    ({"nome": "x" * 200, "tipo_veiculo": "Carro de passeio"}, "até 120"),
])
def test_criar_motorista_com_nome_invalido(api, corpo, trecho):
    cliente, conn = api
    r = cliente.post("/api/motoristas", json=corpo)
    assert r.status_code == 422 and trecho in r.json()["detail"]
    assert conn.chamadas == []


def test_editar_motorista_inexistente_da_404_e_nao_existe_exclusao(api):
    cliente, conn = api
    conn.respostas = ["Carro de passeio", None]
    assert cliente.put("/api/motoristas/99", json={"nome": "X", "tipo_veiculo": "Carro de passeio"}).status_code == 404
    assert cliente.delete("/api/motoristas/1").status_code == 405  # sem DELETE: motorista só é desativado


def test_editar_motorista_com_nome_vazio_ou_tipo_inexistente(api):
    cliente, conn = api
    assert cliente.put("/api/motoristas/1", json={"nome": " ", "tipo_veiculo": "Carro de passeio"}).status_code == 422
    conn.respostas = [None]
    assert cliente.put("/api/motoristas/1", json={"nome": "João", "tipo_veiculo": "Nave"}).status_code == 422


def test_cadastro_indisponivel_vira_mensagem_clara(monkeypatch):
    async def sem_pool():
        return None

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", sem_pool)
    try:
        for chamada in (lambda c: c.get("/api/motoristas"), lambda c: c.get("/api/tipos-veiculo")):
            r = chamada(TestClient(main.app))
            assert r.status_code == 503 and "cadastro de motoristas não está disponível" in r.json()["detail"]
            assert not re.search(r"postgres|asyncpg|sql|traceback|exception", r.json()["detail"], re.IGNORECASE)
    finally:
        main.app.dependency_overrides.clear()


def test_erro_inesperado_do_banco_nao_vaza_detalhe_tecnico(api):
    cliente, conn = api

    async def explode(*a, **k):
        raise RuntimeError("password authentication failed for user neondb_owner")

    conn.fetch = explode
    r = cliente.get("/api/motoristas")
    assert r.status_code == 503 and "neondb" not in r.text and "password" not in r.text


# ----------------------------------------------------------------------------------------------------------
# Frota ativa e roteirização
# ----------------------------------------------------------------------------------------------------------
def test_frota_ativa_traz_custo_e_peso_de_referencia_do_tipo():
    conn = FakeConn([[{"id": 1, "nome": "João", "tipo_veiculo": "Carro de passeio", "valor_rota": None, "custo_rota": Decimal("130.00"), "peso_referencia_kg": None},
                      {"id": 2, "nome": "Ana", "tipo_veiculo": "Fiorino/Utilitário", "valor_rota": Decimal("280.50"), "custo_rota": Decimal("260.00"), "peso_referencia_kg": Decimal("400.000")}]])
    resultado = _rodar(frota.frota_ativa(conn))
    assert resultado == [
        {"id": 1, "nome": "João", "tipo_veiculo": "Carro de passeio", "custo_rota": 130.0, "valor_rota": None, "peso_referencia_kg": None},
        {"id": 2, "nome": "Ana", "tipo_veiculo": "Fiorino/Utilitário", "custo_rota": 260.0, "valor_rota": 280.5, "peso_referencia_kg": 400.0},
    ]
    assert "WHERE m.ativo" in conn.chamadas[0][1]


def test_otimizar_sem_motorista_marcado_pede_a_escolha_sem_erro_tecnico(api, monkeypatch):
    cliente, conn = api
    chamado = []
    monkeypatch.setattr(main, "_processar_otimizacao", lambda *a, **k: chamado.append(a))
    for extra in ({}, {"motorista_ids": []}, {"motorista_ids": None}):
        corpo = {"origem_rua": "Av Paulista", "origem_num": "1", "turno": "manha", "pedidos": [{"id": 1}], **extra}
        r = cliente.post("/api/otimizar", json=corpo)
        assert r.status_code == 422
        assert r.json()["detail"] == frota.MSG_ESCOLHA_UM_MOTORISTA and "Marque pelo menos um motorista" in r.json()["detail"]
    assert chamado == []
    assert not re.search(r"traceback|exception|null|none", r.json()["detail"], re.IGNORECASE)


def test_otimizar_usa_os_motoristas_ativos_e_ignora_frota_e_custos_do_cliente(api, monkeypatch):
    cliente, conn = api
    conn.respostas = [[{"id": 5, "nome": "Ana", "ativo": True, "tipo_veiculo": "Fiorino/Utilitário", "valor_rota": None, "custo_rota": Decimal("260.00"), "peso_referencia_kg": None}]]
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None, loja=None, contexto=None):
        capturado["frota"] = frota_usar
        capturado["req"] = req
        capturado["valores"] = valores_informados

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    corpo = {"origem_rua": "Av Paulista", "origem_num": "1", "turno": "manha", "pedidos": [{"id": 1}], "motorista_ids": [5],
             "frota": [{"id": 1, "motorista": "Motorista 01", "modal": "Carro de Passeio"}],  # cliente antigo: ignorado
             "preco_gasolina": 9.9, "custo_hora": 99}
    r = cliente.post("/api/otimizar", json=corpo)
    assert r.status_code == 200 and r.json()["job_id"]
    assert [(m.id, m.motorista, m.modal, m.custo_rota) for m in capturado["frota"]] == [(5, "Ana", "Fiorino/Utilitário", 260.0)]
    assert not hasattr(capturado["req"], "preco_gasolina") and not hasattr(capturado["req"], "custo_hora")


def test_custo_de_cada_rota_e_o_valor_fixo_do_tipo_de_veiculo(monkeypatch):
    """Roteirização completa com geocodificação e OSRM simulados: o custo vem do tipo, não de km, tempo ou hora."""
    pedidos = [{"id": i, "Endereco": f"Rua {i}", "Numero": str(i), "Bairro": "Centro", "CEP": "01310100", "Volume": 1} for i in range(1, 5)]

    async def geocode_falso(client, *a, **k):
        return -23.5505, -46.6333, "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO"

    async def lote_falso(lista):
        return {main._chave_cache(p["Endereco"], numero=p["Numero"], bairro=p["Bairro"], cep=p["CEP"], cidade="", uf=""):
                (-23.55 - i * 0.001, -46.63, "São Paulo", "SP", "01310100", "Bela Vista", "VALIDO") for i, p in enumerate(lista)}

    async def osrm_falso(client, pontos):
        return 987.0, 600, []  # km e minutos absurdos de propósito: não podem mudar o custo

    monkeypatch.setattr(main, "geocode_async", geocode_falso)
    monkeypatch.setattr(main, "geocodificar_lote", lote_falso)
    monkeypatch.setattr(main, "get_osrm_route_async", osrm_falso)
    req = main.OtimizarRequest(origem_rua="Av Paulista", origem_num="1", pedidos=pedidos,
                               modais_config={"Carro de passeio": {"capacidade": 2}, "Fiorino/Utilitário": {"capacidade": 10}})
    frota_usar = [main.MotoristaItem(id=1, motorista="João", modal="Carro de passeio", custo_rota=130.0),
                  main.MotoristaItem(id=2, motorista="Ana", modal="Fiorino/Utilitário", custo_rota=260.0)]
    main.JOBS["teste"] = {"status": "em_andamento", "etapa": "", "atual": 0, "total": 1, "resultado": None, "erro": None}
    _rodar(main._processar_otimizacao("teste", req, frota_usar))
    job = main.JOBS.pop("teste")
    assert job["status"] == "concluido", job["erro"]
    rotas = job["resultado"]["rotas"]
    assert rotas
    for rota in rotas:
        esperado = 130.0 if rota["modal"] == "Carro de passeio" else 260.0
        assert rota["custo_total"] == esperado
        assert rota["custo_por_pedido"] == round(esperado / rota["qtd_pedidos"], 2)
    assert job["resultado"]["kpis"]["custo_total"] == round(sum(r["custo_total"] for r in rotas), 2)


# ----------------------------------------------------------------------------------------------------------
# Migration 0004
# ----------------------------------------------------------------------------------------------------------
def _migracao():
    spec = importlib.util.spec_from_file_location("migracao_0004", ARQUIVO_MIGRACAO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _sqlite_com_a_migracao(conn):
    for comando in _migracao().COMANDOS:
        comando = (comando.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY").replace("TIMESTAMPTZ", "TIMESTAMP")
                   .replace("NOW()", "CURRENT_TIMESTAMP").replace("length(btrim(nome))", "length(trim(nome))"))
        conn.execute(comando)


def test_migration_0004_e_idempotente_e_nao_apaga_nada():
    modulo = _migracao()
    assert modulo.down_revision == "0003"
    for comando in modulo.COMANDOS:
        assert not re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE)\b", comando, re.IGNORECASE), comando
        assert re.search(r"IF NOT EXISTS|ON CONFLICT \(nome\) DO NOTHING", comando), comando


def test_migration_0004_ja_cria_os_dois_tipos_e_nao_mexe_no_que_foi_editado():
    conn = sqlite3.connect(":memory:")
    _sqlite_com_a_migracao(conn)
    tipos = conn.execute("SELECT nome, custo_rota, peso_referencia_kg, ativo FROM tipos_veiculo ORDER BY id").fetchall()
    assert tipos == [("Carro de passeio", 130, None, 1), ("Fiorino/Utilitário", 260, None, 1)]
    conn.execute("UPDATE tipos_veiculo SET custo_rota = 275, peso_referencia_kg = 400 WHERE nome = 'Fiorino/Utilitário'")
    conn.execute("INSERT INTO motoristas (nome, tipo_veiculo) VALUES ('João', 'Carro de passeio')")
    _sqlite_com_a_migracao(conn)  # segunda vez, como num banco já migrado
    assert conn.execute("SELECT custo_rota, peso_referencia_kg FROM tipos_veiculo WHERE nome = 'Fiorino/Utilitário'").fetchone() == (275, 400)
    assert conn.execute("SELECT count(*) FROM tipos_veiculo").fetchone() == (2,)
    assert conn.execute("SELECT count(*), min(ativo) FROM motoristas").fetchone() == (1, 1)


def test_migration_0004_peso_de_referencia_pode_ficar_em_branco_mas_nao_ser_negativo():
    conn = sqlite3.connect(":memory:")
    _sqlite_com_a_migracao(conn)
    conn.execute("UPDATE tipos_veiculo SET peso_referencia_kg = NULL")  # "sem referência"
    for ruim in ("-5", "0"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE tipos_veiculo SET peso_referencia_kg = {ruim} WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE tipos_veiculo SET custo_rota = -1 WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO motoristas (nome, tipo_veiculo) VALUES ('   ', 'Carro de passeio')")


# ----------------------------------------------------------------------------------------------------------
# Valor por rota informado na roteirização (o valor cadastrado vira o "valor base")
# ----------------------------------------------------------------------------------------------------------
def test_valor_informado_aceita_virgula_decimal_e_vazio_usa_o_base():
    assert frota.interpretar_valor_informado("130,50") == Decimal("130.50")
    assert frota.interpretar_valor_informado("R$ 1.234,56") == Decimal("1234.56")
    assert frota.interpretar_valor_informado(300) == Decimal("300.00")
    for vazio in (None, "", "   "):
        assert frota.interpretar_valor_informado(vazio) is None
    assert frota.interpretar_valor_informado("0") == Decimal("0.00")  # zero digitado de propósito é aceito
    assert frota.interpretar_valor_informado(0) == Decimal("0.00")


@pytest.mark.parametrize("entrada", [-1, "-5", "abc", "R$", True, 1e12])
def test_valor_informado_negativo_ou_texto_e_recusado_com_mensagem_do_operador(entrada):
    with pytest.raises(ValueError) as erro:
        frota.interpretar_valor_informado(entrada, "Fiorino/Utilitário")
    texto = str(erro.value)
    assert "valor por rota" in texto and "Fiorino/Utilitário" in texto
    assert not re.search(r"sql|tabela|banco|api|json|token|null|decimal|invalid|exception", texto, re.IGNORECASE)


def test_valores_informados_por_tipo_sao_independentes():
    assert frota.interpretar_valores_informados(None) == {}
    assert frota.interpretar_valores_informados({}) == {}
    assert frota.interpretar_valores_informados({"Carro de passeio": "", "Fiorino/Utilitário": "300,5"}) == {"fiorino/utilitário": Decimal("300.50")}
    assert frota.interpretar_valores_informados({"Carro de passeio": None, "Fiorino/Utilitário": 0}) == {"fiorino/utilitário": Decimal("0.00")}


def test_otimizar_repassa_os_valores_informados_e_ignora_os_vazios(api, monkeypatch):
    cliente, conn = api
    conn.respostas = [[{"id": 5, "nome": "Ana", "ativo": True, "tipo_veiculo": "Fiorino/Utilitário", "valor_rota": None, "custo_rota": Decimal("260.00"), "peso_referencia_kg": None}]]
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None, loja=None, contexto=None):
        capturado["valores"] = valores_informados

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    corpo = {"origem_rua": "Av Paulista", "origem_num": "1", "turno": "manha", "pedidos": [{"id": 1}], "motorista_ids": [5],
             "valores_por_rota": {"Carro de passeio": "", "Fiorino/Utilitário": "300,50"}}
    assert cliente.post("/api/otimizar", json=corpo).status_code == 200
    assert capturado["valores"] == {"fiorino/utilitário": Decimal("300.50")}


def test_otimizar_sem_o_campo_nao_informa_nada(api, monkeypatch):
    cliente, conn = api
    conn.respostas = [[{"id": 5, "nome": "Ana", "ativo": True, "tipo_veiculo": "Carro de passeio", "valor_rota": None, "custo_rota": Decimal("130.00"), "peso_referencia_kg": None}]]
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None, loja=None, contexto=None):
        capturado["valores"] = valores_informados

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    assert cliente.post("/api/otimizar", json={"origem_rua": "A", "origem_num": "1", "turno": "manha", "pedidos": [{"id": 1}], "motorista_ids": [5]}).status_code == 200
    assert capturado["valores"] == {}


@pytest.mark.parametrize("valores, trecho", [
    ({"Carro de passeio": "-10"}, "não pode ser negativo"),
    ({"Fiorino/Utilitário": -0.01}, "não pode ser negativo"),
    ({"Fiorino/Utilitário": "abc"}, "precisa ser um valor em reais"),
    ({"Carro de passeio": "130", "Fiorino/Utilitário": "muito"}, "Fiorino/Utilitário"),
])
def test_otimizar_com_valor_negativo_ou_texto_devolve_422_e_nao_cria_o_calculo(api, monkeypatch, valores, trecho):
    cliente, conn = api
    criados = []
    monkeypatch.setattr(main, "_processar_otimizacao", lambda *a, **k: criados.append(a))
    r = cliente.post("/api/otimizar", json={"origem_rua": "A", "origem_num": "1", "turno": "manha", "pedidos": [{"id": 1}], "valores_por_rota": valores})
    assert r.status_code == 422 and trecho in r.json()["detail"]
    assert criados == [] and conn.chamadas == []


def _roteirizar(monkeypatch, valores_informados, capacidades=(2, 10), valores_motorista=(None, None)):
    """Roteirização completa (geocodificação e OSRM simulados) com 1 carro e 1 utilitário; devolve o resultado."""
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
    req = main.OtimizarRequest(origem_rua="Av Paulista", origem_num="1", pedidos=pedidos,
                               modais_config={"Carro de passeio": {"capacidade": capacidades[0]}, "Fiorino/Utilitário": {"capacidade": capacidades[1]}})
    frota_usar = [main.MotoristaItem(id=1, motorista="João", modal="Carro de passeio", custo_rota=130.0, valor_motorista=valores_motorista[0]),
                  main.MotoristaItem(id=2, motorista="Ana", modal="Fiorino/Utilitário", custo_rota=260.0, valor_motorista=valores_motorista[1])]
    main.JOBS["t"] = {"status": "em_andamento", "etapa": "", "atual": 0, "total": 1, "resultado": None, "erro": None}
    _rodar(main._processar_otimizacao("t", req, frota_usar, frota.interpretar_valores_informados(valores_informados)))
    job = main.JOBS.pop("t")
    assert job["status"] == "concluido", job["erro"]
    return job["resultado"]


def test_campo_vazio_usa_o_valor_base_e_a_origem_e_padrao(monkeypatch):
    resultado = _roteirizar(monkeypatch, {"Carro de passeio": "", "Fiorino/Utilitário": ""})
    for rota in resultado["rotas"]:
        assert rota["valor_rota"] == (130.0 if rota["modal"] == "Carro de passeio" else 260.0)
        assert rota["custo_total"] == rota["valor_rota"] and rota["origem_valor"] == "padrão"
    assert {v["origem"] for v in resultado["kpis"]["valores_por_tipo"]} == {"padrão"}


def test_valor_informado_vale_para_todas_as_rotas_do_tipo_e_so_dele(monkeypatch):
    resultado = _roteirizar(monkeypatch, {"Carro de passeio": "", "Fiorino/Utilitário": "300,50"})
    rotas = resultado["rotas"]
    utilitario = [r for r in rotas if r["modal"] == "Fiorino/Utilitário"]
    passeio = [r for r in rotas if r["modal"] == "Carro de passeio"]
    assert utilitario and passeio
    for rota in utilitario:  # informar só o utilitário...
        assert rota["valor_rota"] == rota["custo_total"] == 300.5 and rota["origem_valor"] == "informado"
        assert rota["custo_por_pedido"] == round(300.5 / rota["qtd_pedidos"], 2)
    for rota in passeio:  # ...mantém o passeio no valor base
        assert rota["valor_rota"] == rota["custo_total"] == 130.0 and rota["origem_valor"] == "padrão"
    assert resultado["kpis"]["custo_total"] == round(sum(r["custo_total"] for r in rotas), 2)


def test_valor_informado_para_varias_rotas_do_mesmo_tipo(monkeypatch):
    resultado = _roteirizar(monkeypatch, {"Carro de passeio": "99"}, capacidades=(3, 3))
    passeio = [r for r in resultado["rotas"] if r["modal"] == "Carro de passeio"]
    assert len(passeio) >= 2  # 8 pedidos com 3 por viagem: o carro faz mais de uma viagem
    assert all(r["valor_rota"] == r["custo_total"] == 99.0 and r["origem_valor"] == "informado" for r in passeio)


def test_valor_zero_digitado_de_proposito_vale_e_a_origem_e_informado(monkeypatch):
    resultado = _roteirizar(monkeypatch, {"Fiorino/Utilitário": "0"})
    for rota in resultado["rotas"]:
        if rota["modal"] == "Fiorino/Utilitário":
            assert rota["valor_rota"] == 0.0 and rota["custo_total"] == 0.0 and rota["origem_valor"] == "informado"
        else:
            assert rota["custo_total"] == 130.0 and rota["origem_valor"] == "padrão"


def test_resumo_mostra_valor_usado_e_origem_por_tipo(monkeypatch):
    resultado = _roteirizar(monkeypatch, {"Fiorino/Utilitário": "300,5"})
    resumo = {v["tipo"]: v for v in resultado["kpis"]["valores_por_tipo"]}
    assert resumo["Fiorino/Utilitário"]["valor"] == 300.5 and resumo["Fiorino/Utilitário"]["origem"] == "informado"
    assert resumo["Carro de passeio"]["valor"] == 130.0 and resumo["Carro de passeio"]["origem"] == "padrão"
    contagem = {t: sum(1 for r in resultado["rotas"] if r["modal"] == t) for t in resumo}
    assert {t: v["rotas"] for t, v in resumo.items()} == contagem


# ----------------------------------------------------------------------------------------------------------
# Valor próprio por rota do motorista (migration 0005)
# ----------------------------------------------------------------------------------------------------------
def test_valor_proprio_aceita_virgula_e_vazio_e_recusa_negativo_ou_texto():
    assert frota.interpretar_valor_proprio("150,5") == Decimal("150.50")
    assert frota.interpretar_valor_proprio("R$ 1.234,56") == Decimal("1234.56")
    assert frota.interpretar_valor_proprio(0) == Decimal("0.00")  # zero cadastrado de propósito
    for vazio in (None, "", "  "):
        assert frota.interpretar_valor_proprio(vazio) is None
    for ruim in (-1, "-5", "abc", "R$", True, 1e12):
        with pytest.raises(ValueError) as erro:
            frota.interpretar_valor_proprio(ruim)
        assert "valor próprio por rota" in str(erro.value)
        assert not re.search(r"sql|tabela|banco|api|json|token|null|decimal|invalid", str(erro.value), re.IGNORECASE)


def test_listar_motoristas_devolve_o_valor_proprio(api):
    cliente, conn = api
    conn.respostas = [[_motorista(1, valor="150.50"), _motorista(2, "Ana")]]
    r = cliente.get("/api/motoristas")
    assert [m["valor_rota"] for m in r.json()] == [150.5, None]


def test_otimizar_leva_o_valor_proprio_do_motorista_para_o_calculo(api, monkeypatch):
    cliente, conn = api
    conn.respostas = [[{"id": 1, "nome": "João", "ativo": True, "tipo_veiculo": "Carro de passeio", "valor_rota": Decimal("150.00"), "custo_rota": Decimal("130.00"), "peso_referencia_kg": None},
                       {"id": 2, "nome": "Ana", "ativo": True, "tipo_veiculo": "Fiorino/Utilitário", "valor_rota": None, "custo_rota": Decimal("260.00"), "peso_referencia_kg": None}]]
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None, loja=None, contexto=None):
        capturado["frota"] = frota_usar

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    assert cliente.post("/api/otimizar", json={"origem_rua": "A", "origem_num": "1", "turno": "manha", "pedidos": [{"id": 1}], "motorista_ids": [1, 2]}).status_code == 200
    assert [(m.motorista, m.custo_rota, m.valor_motorista) for m in capturado["frota"]] == [("João", 130.0, 150.0), ("Ana", 260.0, None)]


def test_motorista_sem_valor_proprio_usa_o_valor_base(monkeypatch):
    resultado = _roteirizar(monkeypatch, {}, valores_motorista=(None, None))
    for rota in resultado["rotas"]:
        assert rota["valor_rota"] == (130.0 if rota["modal"] == "Carro de passeio" else 260.0) and rota["origem_valor"] == "padrão"


def test_motorista_com_valor_proprio_usa_o_dele(monkeypatch):
    resultado = _roteirizar(monkeypatch, {}, valores_motorista=(150.0, None))
    for rota in resultado["rotas"]:
        if rota["modal"] == "Carro de passeio":
            assert rota["valor_rota"] == rota["custo_total"] == 150.0 and rota["origem_valor"] == "motorista"
        else:
            assert rota["valor_rota"] == rota["custo_total"] == 260.0 and rota["origem_valor"] == "padrão"


def test_valor_digitado_na_roteirizacao_ganha_do_valor_do_motorista(monkeypatch):
    resultado = _roteirizar(monkeypatch, {"Carro de passeio": "99,90"}, valores_motorista=(150.0, 280.0))
    for rota in resultado["rotas"]:
        if rota["modal"] == "Carro de passeio":  # informado ganha do valor próprio do motorista
            assert rota["valor_rota"] == rota["custo_total"] == 99.9 and rota["origem_valor"] == "informado"
        else:  # o utilitário não foi informado: vale o valor próprio do motorista dele
            assert rota["valor_rota"] == rota["custo_total"] == 280.0 and rota["origem_valor"] == "motorista"


def test_tipos_independentes_com_as_tres_origens(monkeypatch):
    resultado = _roteirizar(monkeypatch, {"Fiorino/Utilitário": "300"}, valores_motorista=(150.0, None))
    por_tipo = {r["modal"]: r for r in resultado["rotas"]}
    assert (por_tipo["Carro de passeio"]["valor_rota"], por_tipo["Carro de passeio"]["origem_valor"]) == (150.0, "motorista")
    assert (por_tipo["Fiorino/Utilitário"]["valor_rota"], por_tipo["Fiorino/Utilitário"]["origem_valor"]) == (300.0, "informado")
    resumo = {(v["tipo"], v["valor"], v["origem"]) for v in resultado["kpis"]["valores_por_tipo"]}
    assert resumo == {("Carro de passeio", 150.0, "motorista"), ("Fiorino/Utilitário", 300.0, "informado")}


def test_valor_proprio_zero_vale_e_nao_cai_no_valor_base(monkeypatch):
    resultado = _roteirizar(monkeypatch, {}, valores_motorista=(0.0, None))
    carro = [r for r in resultado["rotas"] if r["modal"] == "Carro de passeio"]
    assert carro and all(r["custo_total"] == 0.0 and r["origem_valor"] == "motorista" for r in carro)


# ----------------------------------------------------------------------------------------------------------
# Migration 0005
# ----------------------------------------------------------------------------------------------------------
ARQUIVO_0005 = BACKEND / "migrations" / "versions" / "0005_motoristas_valor_rota.py"


def _carregar_0005():
    spec = importlib.util.spec_from_file_location("migracao_0005", ARQUIVO_0005)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _aplicar_0005_no_sqlite(conn):
    """O SQLite não tem ADD COLUMN IF NOT EXISTS: confere a coluna antes (o resto do SQL é o mesmo, com o CHECK)."""
    for comando in _carregar_0005().COMANDOS:
        colunas = {l[1] for l in conn.execute("PRAGMA table_info(motoristas)")}
        if "valor_rota" in colunas and "ADD COLUMN IF NOT EXISTS" in comando:
            continue
        conn.execute(comando.replace("ADD COLUMN IF NOT EXISTS", "ADD COLUMN"))


def test_migration_0005_so_acrescenta_a_coluna_sem_apagar_nada():
    modulo = _carregar_0005()
    assert modulo.down_revision == "0004" and modulo.revision == "0005"
    for comando in modulo.COMANDOS:
        assert not re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\b", comando, re.IGNORECASE), comando
        assert "ADD COLUMN IF NOT EXISTS valor_rota NUMERIC(10, 2)" in comando
        assert "CHECK (valor_rota IS NULL OR valor_rota >= 0)" in comando
    # a 0004 não foi editada: continua sem a coluna
    assert "valor_rota" not in ARQUIVO_MIGRACAO.read_text(encoding="utf-8")


def test_migration_0005_roda_duas_vezes_e_preserva_os_motoristas():
    conn = sqlite3.connect(":memory:")
    _sqlite_com_a_migracao(conn)  # a 0004
    conn.execute("INSERT INTO motoristas (nome, tipo_veiculo) VALUES ('João', 'Carro de passeio')")
    _aplicar_0005_no_sqlite(conn)
    assert conn.execute("SELECT nome, valor_rota FROM motoristas").fetchall() == [("João", None)]  # sem valor próprio
    conn.execute("UPDATE motoristas SET valor_rota = 150.5")
    _aplicar_0005_no_sqlite(conn)  # segunda vez, como num banco já migrado
    assert conn.execute("SELECT nome, valor_rota FROM motoristas").fetchall() == [("João", 150.5)]
    assert sum(1 for l in conn.execute("PRAGMA table_info(motoristas)") if l[1] == "valor_rota") == 1


def test_migration_0005_valor_vazio_ou_zero_pode_mas_negativo_nao():
    conn = sqlite3.connect(":memory:")
    _sqlite_com_a_migracao(conn)
    _aplicar_0005_no_sqlite(conn)
    conn.execute("INSERT INTO motoristas (nome, tipo_veiculo, valor_rota) VALUES ('A', 'Carro de passeio', NULL)")
    conn.execute("INSERT INTO motoristas (nome, tipo_veiculo, valor_rota) VALUES ('B', 'Carro de passeio', 0)")
    conn.execute("INSERT INTO motoristas (nome, tipo_veiculo, valor_rota) VALUES ('C', 'Carro de passeio', 150.50)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO motoristas (nome, tipo_veiculo, valor_rota) VALUES ('D', 'Carro de passeio', -1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE motoristas SET valor_rota = -0.01 WHERE nome = 'A'")


# ----------------------------------------------------------------------------------------------------------
# Rotas de motoristas com um banco SQLite de verdade (as tabelas das migrations 0004 a 0009)
# ----------------------------------------------------------------------------------------------------------
OPERADOR = "Maria Souza (maria@zubale.com)"


@pytest.fixture
def api_db(monkeypatch):
    banco = criar_banco_sqlite()

    async def get_pool():
        return FakePool(banco)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), banco
    main.app.dependency_overrides.clear()


def _novo(**extra):
    corpo = {"codigo": "MOT-0001", "nome": "Carlos Lima", "tipo_veiculo": "Carro de passeio"}
    corpo.update(extra)
    return corpo


def test_listar_motoristas_com_e_sem_inativos(api_db):
    cliente, banco = api_db
    banco.inserir_motorista("João", ativo=True)
    banco.inserir_motorista("Ana", ativo=False)
    r = cliente.get("/api/motoristas")
    assert r.status_code == 200 and [m["ativo"] for m in r.json()] == [True, False]
    r = cliente.get("/api/motoristas", params={"incluir_inativos": "false"})
    assert [m["nome"] for m in r.json()] == ["João"]


def test_criar_motorista(api_db):
    cliente, banco = api_db
    r = cliente.post("/api/motoristas", json=_novo(nome="  Carlos   Lima ", tipo_veiculo="carro de passeio"))
    assert r.status_code == 201
    m = r.json()
    assert m["nome"] == "Carlos Lima" and m["tipo_veiculo"] == "Carro de passeio" and m["ativo"] is True
    assert m["codigo"] == "MOT-0001" and m["valor_rota"] is None and m["lojas"] == []
    assert m["atualizado_por"] == OPERADOR


def test_criar_motorista_com_tipo_inexistente(api_db):
    cliente, banco = api_db
    r = cliente.post("/api/motoristas", json=_novo(tipo_veiculo="Caminhão"))
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_TIPO_INEXISTENTE
    r = cliente.post("/api/motoristas", json={"codigo": "MOT-0001", "nome": "Carlos"})
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_TIPO_INEXISTENTE
    assert cliente.get("/api/motoristas").json() == []


def test_desativar_motorista_em_vez_de_apagar(api_db):
    cliente, banco = api_db
    id_ = cliente.post("/api/motoristas", json=_novo(nome="João Silva")).json()["id"]
    r = cliente.put(f"/api/motoristas/{id_}", json={"nome": "João Silva", "tipo_veiculo": "Carro de passeio", "ativo": False})
    assert r.status_code == 200 and r.json()["ativo"] is False and r.json()["atualizado_por"] == OPERADOR
    assert not any(re.search(r"\bDELETE\b", sql, re.IGNORECASE) for sql in banco.sqls if "motoristas" in sql and "motorista_lojas" not in sql)
    assert len(cliente.get("/api/motoristas").json()) == 1  # continua cadastrado


def test_reativar_e_trocar_tipo(api_db):
    cliente, banco = api_db
    id_ = cliente.post("/api/motoristas", json=_novo(nome="João Silva")).json()["id"]
    cliente.put(f"/api/motoristas/{id_}", json={"nome": "João Silva", "tipo_veiculo": "Carro de passeio", "ativo": False})
    r = cliente.put(f"/api/motoristas/{id_}", json={"nome": "João Silva", "tipo_veiculo": "Fiorino/Utilitário", "ativo": True})
    assert r.status_code == 200 and r.json()["tipo_veiculo"] == "Fiorino/Utilitário" and r.json()["ativo"] is True


def test_criar_motorista_com_valor_proprio_em_virgula_decimal(api_db):
    cliente, banco = api_db
    r = cliente.post("/api/motoristas", json=_novo(valor_rota="150,5"))
    assert r.status_code == 201 and r.json()["valor_rota"] == 150.5


@pytest.mark.parametrize("valor, trecho", [(-10, "não pode ser negativo"), ("-0,01", "não pode ser negativo"), ("abc", "precisa ser um valor em reais")])
def test_criar_ou_editar_motorista_com_valor_proprio_negativo_ou_texto_da_422(api_db, valor, trecho):
    cliente, banco = api_db
    r = cliente.post("/api/motoristas", json=_novo(valor_rota=valor))
    assert r.status_code == 422 and trecho in r.json()["detail"]
    id_ = cliente.post("/api/motoristas", json=_novo()).json()["id"]
    r = cliente.put(f"/api/motoristas/{id_}", json={"nome": "Carlos", "tipo_veiculo": "Carro de passeio", "ativo": True, "valor_rota": valor})
    assert r.status_code == 422 and trecho in r.json()["detail"]
    assert cliente.get(f"/api/motoristas/{id_}").json()["valor_rota"] is None  # nada foi gravado


def test_editar_valor_proprio_registra_quem_alterou_e_quando(api_db):
    cliente, banco = api_db
    id_ = cliente.post("/api/motoristas", json=_novo(nome="João Silva")).json()["id"]
    r = cliente.put(f"/api/motoristas/{id_}", json={"nome": "João Silva", "tipo_veiculo": "Carro de passeio", "ativo": True, "valor_rota": "175"})
    assert r.status_code == 200 and r.json()["valor_rota"] == 175.0
    assert r.json()["atualizado_por"] == OPERADOR and r.json()["atualizado_em"]


def test_valor_proprio_em_branco_apaga_e_volta_a_usar_o_valor_base(api_db):
    cliente, banco = api_db
    id_ = cliente.post("/api/motoristas", json=_novo(valor_rota="200")).json()["id"]
    for vazio in ("", None, "  "):
        cliente.put(f"/api/motoristas/{id_}", json={"nome": "João", "tipo_veiculo": "Carro de passeio", "ativo": True, "valor_rota": "200"})
        r = cliente.put(f"/api/motoristas/{id_}", json={"nome": "João", "tipo_veiculo": "Carro de passeio", "ativo": True, "valor_rota": vazio})
        assert r.json()["valor_rota"] is None


def test_editar_sem_mandar_o_campo_mantem_o_valor_proprio(api_db):
    cliente, banco = api_db
    id_ = cliente.post("/api/motoristas", json=_novo(nome="João Silva", valor_rota="150")).json()["id"]
    r = cliente.put(f"/api/motoristas/{id_}", json={"nome": "João Silva", "tipo_veiculo": "Carro de passeio", "ativo": False})
    assert r.status_code == 200 and r.json()["valor_rota"] == 150.0
