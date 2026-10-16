"""Etapa 6b: motoristas por loja (vínculos), código único, telefone (validação, máscara, privacidade) e migration 0008."""
import asyncio
import re
import time

import pytest
from fastapi.testclient import TestClient

import frota
import main
from backend.tests.fakes_asyncpg import FakePool, _migracao, criar_banco_sqlite

OPERADOR = "Maria Souza (maria@zubale.com)"
FONE = "(11) 91234-5678"
FONE_DIGITOS = "11912345678"


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


@pytest.fixture
def api(monkeypatch):
    banco = criar_banco_sqlite()

    async def get_pool():
        return FakePool(banco)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), banco
    main.app.dependency_overrides.clear()


def _loja(banco, nome, ativo=True):
    return banco.db.execute("INSERT INTO lojas (nome, lat, lng, ativo) VALUES (?, -23.5, -46.6, ?)", (nome, 1 if ativo else 0)).lastrowid


def _novo(**extra):
    corpo = {"codigo": "MOT-0001", "nome": "Carlos Lima", "tipo_veiculo": "Carro de passeio"}
    corpo.update(extra)
    return corpo


def _edicao(**extra):
    corpo = {"nome": "Carlos Lima", "tipo_veiculo": "Carro de passeio", "ativo": True}
    corpo.update(extra)
    return corpo


# ----------------------------------------------------------------------------------------------------------
# Código
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("entrada, esperado", [("mot 0001", "MOT0001"), (" Mót-0001 ", "MOT-0001"), ("mot-0001", "MOT-0001"), ("", ""), (None, "")])
def test_normalizar_codigo(entrada, esperado):
    assert frota.normalizar_codigo(entrada) == esperado


def test_codigo_obrigatorio_no_cadastro_novo(api):
    cliente, banco = api
    for codigo in (None, "", "   "):
        r = cliente.post("/api/motoristas", json=_novo(codigo=codigo))
        assert r.status_code == 422 and r.json()["detail"] == frota.MSG_CODIGO_VAZIO
    r = cliente.post("/api/motoristas", json={"nome": "Carlos", "tipo_veiculo": "Carro de passeio"})
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_CODIGO_VAZIO
    assert cliente.get("/api/motoristas").json() == []


def test_codigo_unico_sem_diferenca_de_maiusculas_acentos_ou_espacos(api):
    cliente, banco = api
    assert cliente.post("/api/motoristas", json=_novo(codigo="MOT-0001")).status_code == 201
    for repetido in ("mot-0001", "  Mot-0001 ", "MÓT-0001", "M O T - 0 0 0 1"):
        r = cliente.post("/api/motoristas", json=_novo(codigo=repetido, nome="Outro"))
        assert r.status_code == 422 and r.json()["detail"] == frota.MSG_CODIGO_REPETIDO, repetido
    assert len(cliente.get("/api/motoristas").json()) == 1


def test_nomes_repetidos_sao_aceitos_com_codigos_diferentes(api):
    cliente, banco = api
    assert cliente.post("/api/motoristas", json=_novo(codigo="MOT-0001", nome="João Silva")).status_code == 201
    assert cliente.post("/api/motoristas", json=_novo(codigo="MOT-0002", nome="João Silva")).status_code == 201


def test_codigo_vem_normalizado_na_resposta(api):
    cliente, banco = api
    r = cliente.post("/api/motoristas", json=_novo(codigo=" mót 0007 "))
    assert r.json()["codigo"] == "MOT0007"


def test_editar_para_codigo_de_outro_motorista_e_recusado_mas_o_proprio_vale(api):
    cliente, banco = api
    a = cliente.post("/api/motoristas", json=_novo(codigo="MOT-0001")).json()["id"]
    cliente.post("/api/motoristas", json=_novo(codigo="MOT-0002", nome="Ana"))
    r = cliente.put(f"/api/motoristas/{a}", json=_edicao(codigo="mot-0002"))
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_CODIGO_REPETIDO
    r = cliente.put(f"/api/motoristas/{a}", json=_edicao(codigo="mot-0001"))  # o próprio código, só em minúsculas
    assert r.status_code == 200 and r.json()["codigo"] == "MOT-0001"
    r = cliente.put(f"/api/motoristas/{a}", json=_edicao(codigo="MOT-0010"))
    assert r.status_code == 200 and r.json()["codigo"] == "MOT-0010"


def test_codigo_nao_pode_ser_apagado_de_quem_ja_tem_e_ausente_mantem(api):
    cliente, banco = api
    a = cliente.post("/api/motoristas", json=_novo()).json()["id"]
    for vazio in ("", "  ", None):
        r = cliente.put(f"/api/motoristas/{a}", json=_edicao(codigo=vazio))
        assert r.status_code == 422 and r.json()["detail"] == frota.MSG_CODIGO_NAO_PODE_FICAR_VAZIO
    r = cliente.put(f"/api/motoristas/{a}", json=_edicao())  # sem o campo: mantém
    assert r.status_code == 200 and r.json()["codigo"] == "MOT-0001"


def test_motorista_antigo_sem_codigo_continua_funcionando(api):
    cliente, banco = api
    antigo = banco.inserir_motorista("Antigo", ativo=False)
    lista = cliente.get("/api/motoristas").json()
    assert lista[0]["codigo"] is None
    r = cliente.put(f"/api/motoristas/{antigo}", json=_edicao(nome="Antigo", ativo=False))
    assert r.status_code == 200 and r.json()["codigo"] is None
    r = cliente.put(f"/api/motoristas/{antigo}", json=_edicao(nome="Antigo", ativo=False, codigo="MOT-0009"))
    assert r.status_code == 200 and r.json()["codigo"] == "MOT-0009"


def test_proximo_codigo(api):
    cliente, banco = api
    assert cliente.get("/api/motoristas/proximo-codigo").json() == {"codigo": "MOT-0001"}
    cliente.post("/api/motoristas", json=_novo(codigo="MOT-0001"))
    assert cliente.get("/api/motoristas/proximo-codigo").json()["codigo"] == "MOT-0002"
    cliente.post("/api/motoristas", json=_novo(codigo="MOT-0007", nome="Ana"))  # buraco: vale o maior + 1
    assert cliente.get("/api/motoristas/proximo-codigo").json()["codigo"] == "MOT-0008"
    cliente.post("/api/motoristas", json=_novo(codigo="ABC-9", nome="Fora do padrão"))
    cliente.post("/api/motoristas", json=_novo(codigo="mot 0012", nome="Com espaço"))  # vira MOT0012
    assert cliente.get("/api/motoristas/proximo-codigo").json()["codigo"] == "MOT-0013"


# ----------------------------------------------------------------------------------------------------------
# Telefone
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("entrada, esperado", [
    ("(11) 91234-5678", "11912345678"), ("11 91234 5678", "11912345678"), ("11912345678", "11912345678"),
    ("+55 11 91234-5678", "11912345678"), ("55 (11) 91234-5678", "11912345678"), ("011 91234-5678", "11912345678"),
    ("(11) 3123-4567", "1131234567"), ("+55 (21) 2123-4567", "2121234567"), ("11.91234.5678", "11912345678"),
    ("", None), ("   ", None), (None, None),
])
def test_telefone_valido_guarda_so_os_digitos(entrada, esperado):
    assert frota.normalizar_telefone(entrada) == esperado


@pytest.mark.parametrize("entrada", ["91234-5678", "3123-4567", "123", "(11) 1234-5678", "(11) 91234-567", "(00) 91234-5678",
                                     "(11) 81234-5678", "abc", "11 9123x-5678", "(11) 91234-56789", "1191234567890123"])
def test_telefone_invalido_e_recusado_sem_repetir_o_numero(entrada):
    with pytest.raises(ValueError) as erro:
        frota.normalizar_telefone(entrada)
    assert str(erro.value) in (frota.MSG_TELEFONE_INVALIDO, frota.MSG_TELEFONE_SEM_DDD)
    assert not re.search(r"\d{4}", str(erro.value).replace("98765-4321", "")) and entrada not in str(erro.value)


def test_telefone_sem_ddd_pede_o_ddd():
    for entrada in ("91234-5678", "3123-4567", "991234567"):
        with pytest.raises(ValueError, match="DDD"):
            frota.normalizar_telefone(entrada)


@pytest.mark.parametrize("digitos, esperado", [("11912345678", "(11) *****-5678"), ("1131234567", "(11) ****-4567"), ("", None), (None, None), ("123", None)])
def test_telefone_mascarado(digitos, esperado):
    assert frota.mascarar_telefone(digitos) == esperado


def test_lista_traz_so_o_telefone_mascarado_e_o_detalhe_o_completo(api):
    cliente, banco = api
    r = cliente.post("/api/motoristas", json=_novo(telefone=FONE))
    assert r.status_code == 201
    id_ = r.json()["id"]
    assert r.json()["telefone_mascarado"] == "(11) *****-5678" and r.json()["tem_telefone"] is True
    assert FONE_DIGITOS not in r.text and "telefone" not in {k for k in r.json() if k == "telefone"}
    lista = cliente.get("/api/motoristas")
    assert FONE_DIGITOS not in lista.text and "91234" not in lista.text
    assert lista.json()[0]["telefone_mascarado"] == "(11) *****-5678" and "telefone" not in lista.json()[0]
    detalhe = cliente.get(f"/api/motoristas/{id_}")
    assert detalhe.status_code == 200 and detalhe.json()["telefone"] == FONE_DIGITOS
    # a resposta de gravação (PUT) também não devolve o número completo
    r = cliente.put(f"/api/motoristas/{id_}", json=_edicao(telefone="(21) 98888-7777"))
    assert r.status_code == 200 and "98888" not in r.text and r.json()["telefone_mascarado"] == "(21) *****-7777"
    assert cliente.get(f"/api/motoristas/{id_}").json()["telefone"] == "21988887777"


def test_telefone_invalido_na_tela_da_422_clara_e_nao_grava(api):
    cliente, banco = api
    r = cliente.post("/api/motoristas", json=_novo(telefone="91234-5678"))
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_TELEFONE_SEM_DDD
    r = cliente.post("/api/motoristas", json=_novo(telefone="não é telefone"))
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_TELEFONE_INVALIDO
    assert "91234" not in r.text
    assert cliente.get("/api/motoristas").json() == []


def test_telefone_sem_telefone_ausente_mantem_e_vazio_apaga(api):
    cliente, banco = api
    id_ = cliente.post("/api/motoristas", json=_novo(telefone=FONE)).json()["id"]
    cliente.put(f"/api/motoristas/{id_}", json=_edicao(nome="Carlos Lima Filho"))  # sem o campo: mantém
    assert cliente.get(f"/api/motoristas/{id_}").json()["telefone"] == FONE_DIGITOS
    r = cliente.put(f"/api/motoristas/{id_}", json=_edicao(telefone=""))  # vazio: apaga (pedido de remoção de dados)
    assert r.status_code == 200 and r.json()["tem_telefone"] is False and r.json()["telefone_mascarado"] is None
    assert cliente.get(f"/api/motoristas/{id_}").json()["telefone"] is None
    assert banco.db.execute("SELECT telefone FROM motoristas WHERE id = ?", (id_,)).fetchone()[0] is None


def test_telefone_nao_vai_para_o_log_nem_para_a_mensagem_de_erro(api, capsys):
    cliente, banco = api

    async def explode(*a, **k):
        raise RuntimeError(f'new row for relation "motoristas" violates check constraint, Failing row contains (1, {FONE_DIGITOS})')

    banco.fetch = explode
    r = cliente.get("/api/motoristas")
    saida = capsys.readouterr()
    assert r.status_code == 503 and FONE_DIGITOS not in r.text
    assert FONE_DIGITOS not in saida.out + saida.err and "Failing row" not in saida.out + saida.err
    assert "RuntimeError" in saida.out  # o log registra só a classe do erro


def test_erro_de_validacao_do_telefone_nao_chega_ao_log(api, capsys):
    cliente, banco = api
    cliente.post("/api/motoristas", json=_novo(telefone="(11) 1234-567"))
    saida = capsys.readouterr()
    assert "1234-567" not in saida.out + saida.err


# ----------------------------------------------------------------------------------------------------------
# Lojas do motorista
# ----------------------------------------------------------------------------------------------------------
def test_criar_motorista_com_lojas_e_listar_com_nomes(api):
    cliente, banco = api
    a, b = _loja(banco, "Atacadão Guarujá"), _loja(banco, "Atacadão Campinas")
    r = cliente.post("/api/motoristas", json=_novo(lojas=[a, b]))
    assert r.status_code == 201
    assert [l["nome"] for l in r.json()["lojas"]] == ["Atacadão Campinas", "Atacadão Guarujá"]
    assert all(l["ativo"] is True for l in r.json()["lojas"])
    lista = cliente.get("/api/motoristas").json()
    assert {l["id"] for l in lista[0]["lojas"]} == {a, b}


def test_trocar_as_lojas_substitui_o_conjunto_e_ausente_mantem(api):
    cliente, banco = api
    a, b, c = _loja(banco, "A"), _loja(banco, "B"), _loja(banco, "C")
    id_ = cliente.post("/api/motoristas", json=_novo(lojas=[a, b])).json()["id"]
    r = cliente.put(f"/api/motoristas/{id_}", json=_edicao(lojas=[b, c]))
    assert [l["id"] for l in r.json()["lojas"]] == [b, c]
    r = cliente.put(f"/api/motoristas/{id_}", json=_edicao())  # sem o campo: mantém
    assert [l["id"] for l in r.json()["lojas"]] == [b, c]
    r = cliente.put(f"/api/motoristas/{id_}", json=_edicao(lojas=[]))  # lista vazia: sem lojas
    assert r.json()["lojas"] == []
    assert banco.db.execute("SELECT COUNT(*) FROM motorista_lojas").fetchone()[0] == 0


def test_loja_inexistente_ou_desativada_e_recusada_para_vinculo_novo(api):
    cliente, banco = api
    ok, desativada = _loja(banco, "Ativa"), _loja(banco, "Fechada", ativo=False)
    r = cliente.post("/api/motoristas", json=_novo(lojas=[ok, 9999]))
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_LOJA_INEXISTENTE
    r = cliente.post("/api/motoristas", json=_novo(lojas=[desativada]))
    assert r.status_code == 422 and "Fechada" in r.json()["detail"] and "desativada" in r.json()["detail"]
    assert cliente.get("/api/motoristas").json() == []  # nada foi gravado (transação)
    assert banco.db.execute("SELECT COUNT(*) FROM motorista_lojas").fetchone()[0] == 0
    r = cliente.post("/api/motoristas", json=_novo(lojas="não é lista"))
    assert r.status_code == 422
    r = cliente.post("/api/motoristas", json=_novo(lojas=["abc"]))
    assert r.status_code == 422 and r.json()["detail"] == frota.MSG_LOJAS_FORMATO


def test_loja_desativada_depois_continua_vinculada(api):
    cliente, banco = api
    a, b = _loja(banco, "A"), _loja(banco, "B")
    id_ = cliente.post("/api/motoristas", json=_novo(lojas=[a, b])).json()["id"]
    banco.db.execute("UPDATE lojas SET ativo = 0 WHERE id = ?", (a,))
    lojas = cliente.get("/api/motoristas").json()[0]["lojas"]
    assert {(l["id"], l["ativo"]) for l in lojas} == {(a, False), (b, True)}  # o vínculo continua, marcado como desativada
    # salvar de novo com a mesma lista (inclui a desativada que já estava vinculada) é aceito
    r = cliente.put(f"/api/motoristas/{id_}", json=_edicao(lojas=[a, b]))
    assert r.status_code == 200 and len(r.json()["lojas"]) == 2
    # sem mandar as lojas, também continuam
    r = cliente.put(f"/api/motoristas/{id_}", json=_edicao(nome="Carlos Lima Jr"))
    assert len(r.json()["lojas"]) == 2
    # mas um vínculo NOVO com a desativada é recusado
    outro = cliente.post("/api/motoristas", json=_novo(codigo="MOT-0002", nome="Ana")).json()["id"]
    r = cliente.put(f"/api/motoristas/{outro}", json=_edicao(nome="Ana", lojas=[a]))
    assert r.status_code == 422


def test_lojas_repetidas_na_lista_viram_um_vinculo(api):
    cliente, banco = api
    a = _loja(banco, "A")
    r = cliente.post("/api/motoristas", json=_novo(lojas=[a, a, str(a)]))
    assert r.status_code == 201 and len(r.json()["lojas"]) == 1


def test_get_por_id_inexistente_da_404(api):
    cliente, banco = api
    assert cliente.get("/api/motoristas/999").status_code == 404


def test_registra_quem_alterou_e_quando_nos_motoristas_e_nos_vinculos(api):
    cliente, banco = api
    a = _loja(banco, "A")
    r = cliente.post("/api/motoristas", json=_novo(lojas=[a]))
    assert r.json()["atualizado_por"] == OPERADOR and r.json()["atualizado_em"]
    assert banco.db.execute("SELECT atualizado_por FROM motorista_lojas").fetchone()[0] == OPERADOR


# ----------------------------------------------------------------------------------------------------------
# Desempenho com 500 motoristas
# ----------------------------------------------------------------------------------------------------------
def test_listar_500_motoristas_com_lojas_e_rapido(api):
    cliente, banco = api
    lojas = [_loja(banco, f"Loja {i:03d}") for i in range(20)]
    for i in range(500):
        id_ = banco.db.execute("INSERT INTO motoristas (codigo, nome, tipo_veiculo, ativo) VALUES (?, ?, 'Carro de passeio', 1)", (f"MOT-{i + 1:04d}", f"Motorista {i}")).lastrowid
        banco.db.execute("INSERT INTO motorista_lojas (motorista_id, loja_id) VALUES (?, ?)", (id_, lojas[i % 20]))
    inicio = time.perf_counter()
    r = cliente.get("/api/motoristas")
    assert r.status_code == 200 and len(r.json()) == 500
    assert time.perf_counter() - inicio < 3
    assert cliente.get("/api/motoristas/proximo-codigo").json()["codigo"] == "MOT-0501"


# ----------------------------------------------------------------------------------------------------------
# Migration 0008
# ----------------------------------------------------------------------------------------------------------
def test_migration_0008_e_idempotente_e_nao_apaga_nada():
    modulo = _migracao("0008_motorista_lojas.py")
    assert modulo.revision == "0008" and modulo.down_revision == "0007"
    texto = " ".join(modulo.COMANDOS).upper()
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE)\b", texto)
    assert "IF NOT EXISTS" in texto and "PRIMARY KEY (MOTORISTA_ID, LOJA_ID)" in texto
    assert "UX_MOTORISTAS_CODIGO" in texto and "WHERE CODIGO IS NOT NULL" in texto
    assert all("IF NOT EXISTS" in c.upper() for c in modulo.COMANDOS)


def test_migration_0008_roda_duas_vezes_e_preserva_os_dados():
    banco = criar_banco_sqlite()
    antigo = banco.inserir_motorista("Antigo", ativo=False)
    modulo = _migracao("0008_motorista_lojas.py")
    for comando in modulo.COMANDOS:
        if comando.lstrip().upper().startswith("ALTER TABLE"):
            continue  # o SQLite não tem ADD COLUMN IF NOT EXISTS; a coluna já existe depois da primeira vez
        banco.db.execute(comando.replace("TIMESTAMPTZ", "TIMESTAMP").replace("NOW()", "CURRENT_TIMESTAMP"))
    assert banco.db.execute("SELECT nome FROM motoristas WHERE id = ?", (antigo,)).fetchone()[0] == "Antigo"


def test_banco_recusa_codigo_repetido_e_telefone_com_tamanho_errado():
    import sqlite3
    banco = criar_banco_sqlite()
    banco.db.execute("INSERT INTO motoristas (codigo, nome, tipo_veiculo) VALUES ('MOT-0001', 'A', 'Carro de passeio')")
    with pytest.raises(sqlite3.IntegrityError):
        banco.db.execute("INSERT INTO motoristas (codigo, nome, tipo_veiculo) VALUES (' mot-0001 ', 'B', 'Carro de passeio')")
    # vários sem código (motoristas antigos) são permitidos
    banco.db.execute("INSERT INTO motoristas (nome, tipo_veiculo) VALUES ('Antigo 1', 'Carro de passeio')")
    banco.db.execute("INSERT INTO motoristas (nome, tipo_veiculo) VALUES ('Antigo 2', 'Carro de passeio')")
    with pytest.raises(sqlite3.IntegrityError):
        banco.db.execute("INSERT INTO motoristas (codigo, nome, tipo_veiculo, telefone) VALUES ('X', 'C', 'Carro de passeio', '123')")


def test_cadastro_indisponivel_sem_banco_nao_vaza_nada(monkeypatch):
    async def sem_pool():
        return None

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", sem_pool)
    try:
        for caminho in ("/api/motoristas/proximo-codigo", "/api/motoristas/1"):
            r = TestClient(main.app).get(caminho)
            assert r.status_code == 503 and "neondb" not in r.text
    finally:
        main.app.dependency_overrides.clear()
