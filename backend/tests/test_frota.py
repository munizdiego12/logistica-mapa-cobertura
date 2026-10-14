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
from backend.tests.fakes_asyncpg import FakeConn, FakePool

BACKEND = Path(__file__).resolve().parents[1]
ARQUIVO_MIGRACAO = BACKEND / "migrations" / "versions" / "0004_tipos_veiculo_motoristas.py"
AGORA = datetime(2026, 10, 13, 10, 0, 0)


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


def _tipo(id=1, nome="Carro de passeio", custo="130.00", peso=None):
    return {"id": id, "nome": nome, "custo_rota": Decimal(custo), "peso_referencia_kg": None if peso is None else Decimal(peso),
            "ativo": True, "atualizado_em": AGORA, "atualizado_por": "cadastro inicial (migration)"}


def _motorista(id=1, nome="João Silva", tipo="Carro de passeio", ativo=True):
    return {"id": id, "nome": nome, "tipo_veiculo": tipo, "ativo": ativo, "atualizado_em": AGORA, "atualizado_por": "Maria Souza (maria@zubale.com)"}


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


# ----------------------------------------------------------------------------------------------------------
# Rotas: motoristas
# ----------------------------------------------------------------------------------------------------------
def test_listar_motoristas_com_e_sem_inativos(api):
    cliente, conn = api
    conn.respostas = [[_motorista(1), _motorista(2, "Ana", ativo=False)]]
    r = cliente.get("/api/motoristas")
    assert r.status_code == 200 and [m["ativo"] for m in r.json()] == [True, False]
    assert "WHERE ativo" not in conn.chamadas[0][1]
    conn.respostas = [[_motorista(1)]]
    cliente.get("/api/motoristas", params={"incluir_inativos": "false"})
    assert "WHERE ativo" in conn.chamadas[1][1]


def test_criar_motorista(api):
    cliente, conn = api
    conn.respostas = ["Carro de passeio", _motorista(7, "Carlos Lima")]
    r = cliente.post("/api/motoristas", json={"nome": "  Carlos   Lima ", "tipo_veiculo": "carro de passeio"})
    assert r.status_code == 201 and r.json()["id"] == 7 and r.json()["ativo"] is True
    insercao = conn.chamadas[1]
    assert "INSERT INTO motoristas" in insercao[1]
    assert insercao[2] == ("Carlos Lima", "Carro de passeio", "Maria Souza (maria@zubale.com)")


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


def test_criar_motorista_com_tipo_inexistente(api):
    cliente, conn = api
    conn.respostas = [None]  # o tipo não está no cadastro
    r = cliente.post("/api/motoristas", json={"nome": "Carlos", "tipo_veiculo": "Caminhão"})
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_TIPO_INEXISTENTE
    assert all("INSERT" not in c[1] for c in conn.chamadas if c[1])
    r = cliente.post("/api/motoristas", json={"nome": "Carlos"})
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_TIPO_INEXISTENTE


def test_desativar_motorista_em_vez_de_apagar(api):
    cliente, conn = api
    conn.respostas = ["Carro de passeio", _motorista(1, "João Silva", ativo=False)]
    r = cliente.put("/api/motoristas/1", json={"nome": "João Silva", "tipo_veiculo": "Carro de passeio", "ativo": False})
    assert r.status_code == 200 and r.json()["ativo"] is False
    sql, args = conn.chamadas[1][1], conn.chamadas[1][2]
    assert "UPDATE motoristas" in sql and "atualizado_em = NOW()" in sql and "atualizado_por" in sql
    assert args == (1, "João Silva", "Carro de passeio", False, "Maria Souza (maria@zubale.com)")
    assert not any(re.search(r"\bDELETE\b", c[1] or "", re.IGNORECASE) for c in conn.chamadas)


def test_reativar_e_trocar_tipo(api):
    cliente, conn = api
    conn.respostas = ["Fiorino/Utilitário", _motorista(1, "João Silva", "Fiorino/Utilitário", True)]
    r = cliente.put("/api/motoristas/1", json={"nome": "João Silva", "tipo_veiculo": "Fiorino/Utilitário", "ativo": True})
    assert r.status_code == 200 and r.json()["tipo_veiculo"] == "Fiorino/Utilitário" and r.json()["ativo"] is True


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
    conn = FakeConn([[{"id": 1, "nome": "João", "tipo_veiculo": "Carro de passeio", "custo_rota": Decimal("130.00"), "peso_referencia_kg": None},
                      {"id": 2, "nome": "Ana", "tipo_veiculo": "Fiorino/Utilitário", "custo_rota": Decimal("260.00"), "peso_referencia_kg": Decimal("400.000")}]])
    resultado = _rodar(frota.frota_ativa(conn))
    assert resultado == [
        {"id": 1, "nome": "João", "tipo_veiculo": "Carro de passeio", "custo_rota": 130.0, "peso_referencia_kg": None},
        {"id": 2, "nome": "Ana", "tipo_veiculo": "Fiorino/Utilitário", "custo_rota": 260.0, "peso_referencia_kg": 400.0},
    ]
    assert "WHERE m.ativo" in conn.chamadas[0][1]


def test_otimizar_sem_motoristas_cadastrados_pede_o_cadastro_sem_erro_tecnico(api, monkeypatch):
    cliente, conn = api
    conn.respostas = [[]]  # nenhum motorista ativo
    chamado = []
    monkeypatch.setattr(main, "_processar_otimizacao", lambda *a, **k: chamado.append(a))
    corpo = {"origem_rua": "Av Paulista", "origem_num": "1", "pedidos": [{"id": 1}]}
    r = cliente.post("/api/otimizar", json=corpo)
    assert r.status_code == 422
    assert r.json()["detail"] == frota.MSG_SEM_MOTORISTAS and "Cadastre" in r.json()["detail"]
    assert chamado == []
    assert not re.search(r"traceback|exception|null|none", r.json()["detail"], re.IGNORECASE)


def test_otimizar_usa_os_motoristas_ativos_e_ignora_frota_e_custos_do_cliente(api, monkeypatch):
    cliente, conn = api
    conn.respostas = [[{"id": 5, "nome": "Ana", "tipo_veiculo": "Fiorino/Utilitário", "custo_rota": Decimal("260.00"), "peso_referencia_kg": None}]]
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None):
        capturado["frota"] = frota_usar
        capturado["req"] = req
        capturado["valores"] = valores_informados

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    corpo = {"origem_rua": "Av Paulista", "origem_num": "1", "pedidos": [{"id": 1}],
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
    conn.respostas = [[{"id": 5, "nome": "Ana", "tipo_veiculo": "Fiorino/Utilitário", "custo_rota": Decimal("260.00"), "peso_referencia_kg": None}]]
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None):
        capturado["valores"] = valores_informados

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    corpo = {"origem_rua": "Av Paulista", "origem_num": "1", "pedidos": [{"id": 1}],
             "valores_por_rota": {"Carro de passeio": "", "Fiorino/Utilitário": "300,50"}}
    assert cliente.post("/api/otimizar", json=corpo).status_code == 200
    assert capturado["valores"] == {"fiorino/utilitário": Decimal("300.50")}


def test_otimizar_sem_o_campo_nao_informa_nada(api, monkeypatch):
    cliente, conn = api
    conn.respostas = [[{"id": 5, "nome": "Ana", "tipo_veiculo": "Carro de passeio", "custo_rota": Decimal("130.00"), "peso_referencia_kg": None}]]
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None):
        capturado["valores"] = valores_informados

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    assert cliente.post("/api/otimizar", json={"origem_rua": "A", "origem_num": "1", "pedidos": [{"id": 1}]}).status_code == 200
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
    r = cliente.post("/api/otimizar", json={"origem_rua": "A", "origem_num": "1", "pedidos": [{"id": 1}], "valores_por_rota": valores})
    assert r.status_code == 422 and trecho in r.json()["detail"]
    assert criados == [] and conn.chamadas == []


def _roteirizar(monkeypatch, valores_informados, capacidades=(2, 10)):
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
    frota_usar = [main.MotoristaItem(id=1, motorista="João", modal="Carro de passeio", custo_rota=130.0),
                  main.MotoristaItem(id=2, motorista="Ana", modal="Fiorino/Utilitário", custo_rota=260.0)]
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
