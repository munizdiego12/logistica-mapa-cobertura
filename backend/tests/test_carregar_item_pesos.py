"""Script de carga de item_pesos: resumo antes de gravar, confirmação, conexão só quando precisa e proteção das edições."""
import asyncio
import importlib.util
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest

from backend.item_pesos import OPERADOR_CARGA_INICIAL
from backend.tests.fakes_asyncpg import FakeConn

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("carregar_item_pesos_teste", RAIZ / "scripts" / "carregar_item_pesos.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

CSV = (
    "id_sku;reference_code;nome;peso_kg_sugerido;fonte;confianca;unidades_vendidas\n"
    "1;r1;Açúcar 1kg;1;nome;alta;2.624\n"
    "2;r2;Maionese 2x500g;1,05;manual;média;82\n"
    "3;r3;Ovo 20 un;;;;203\n"
    "4;r4;Item ruim;abc;;;5\n"
)


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "revisado.csv"
    caminho.write_bytes(CSV.encode("utf-8"))
    return str(caminho)


def _sem_banco(monkeypatch):
    async def proibido(dsn):
        raise AssertionError("não era para conectar no banco")

    monkeypatch.setattr(script, "conectar", proibido)


def _banco_falso(monkeypatch, respostas_por_conexao, eventos, **kw):
    conexoes = []

    async def conectar(dsn):
        eventos.append("conectar")
        conn = FakeConn(respostas_por_conexao[len(conexoes)] if len(conexoes) < len(respostas_por_conexao) else [], eventos, **kw)
        conexoes.append(conn)
        return conn

    monkeypatch.setattr(script, "conectar", conectar)
    monkeypatch.setenv("DATABASE_URL", "postgres://usuario:segredo@host.neon.tech/db?sslmode=require&channel_binding=require")
    return conexoes


def test_sem_gravar_mostra_o_resumo_e_nem_conecta_no_banco(arquivo, monkeypatch, capsys):
    _sem_banco(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    script.main(["--csv", arquivo])
    texto = capsys.readouterr().out
    assert "COM PESO (serão gravadas): 2" in texto and "SEM PESO (ignoradas" in texto and "INVÁLIDAS (ignoradas): 1" in texto
    assert "peso 'abc' não é um número" in texto and "separador: ';'" in texto and "Nada foi gravado" in texto


def test_arquivo_inexistente_lista_os_csvs_disponiveis(tmp_path):
    with pytest.raises(SystemExit) as erro:
        script.main(["--csv", str(tmp_path / "nao_existe.csv")])
    assert "não achei" in str(erro.value)


def test_csv_sem_as_colunas_certas_para_com_erro_claro(tmp_path):
    caminho = tmp_path / "ruim.csv"
    caminho.write_text("produto;valor\nA;1\n", encoding="utf-8")
    with pytest.raises(SystemExit) as erro:
        script.main(["--csv", str(caminho)])
    assert "id_sku e peso" in str(erro.value)


def test_gravar_sem_database_url_para_antes_de_tentar_conectar(arquivo, monkeypatch):
    _sem_banco(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as erro:
        script.main(["--csv", arquivo, "--gravar"])
    assert "DATABASE_URL" in str(erro.value)


def test_gravar_pede_confirmacao_e_nao_segura_conexao_aberta_enquanto_espera(arquivo, monkeypatch, capsys):
    eventos = []
    conexoes = _banco_falso(monkeypatch, [[]], eventos)  # 1ª conexão (previsão): nenhum item existe ainda
    monkeypatch.setattr("builtins.input", lambda prompt="": eventos.append("input") or "GRAVAR")
    script.main(["--csv", arquivo, "--gravar"])
    assert eventos == ["conectar", "fetch", "fechar", "input", "conectar", "begin", "executemany", "commit", "fechar"]
    previsao_conn, gravacao_conn = conexoes
    assert previsao_conn.chamadas[0][0] == "fetch" and all(c[0] == "fetch" for c in previsao_conn.chamadas)  # a previsão só lê
    _, sql, linhas = [c for c in gravacao_conn.chamadas if c[0] == "executemany"][0]
    assert "ON CONFLICT (id_sku) DO UPDATE" in sql
    assert linhas == [
        ("1", "r1", "Açúcar 1kg", Decimal("1.0000"), "nome", "alta", 2624, OPERADOR_CARGA_INICIAL),
        ("2", "r2", "Maionese 2x500g", Decimal("1.0500"), "manual", "media", 82, OPERADOR_CARGA_INICIAL),
    ]
    saida = capsys.readouterr().out
    assert "itens novos: 2" in saida and "Gravado: 2 item(ns) com peso" in saida
    assert "segredo" not in saida  # a string do banco nunca aparece


def test_resposta_diferente_de_gravar_cancela_sem_abrir_a_segunda_conexao(arquivo, monkeypatch, capsys):
    eventos = []
    conexoes = _banco_falso(monkeypatch, [[]], eventos)
    monkeypatch.setattr("builtins.input", lambda prompt="": "sim")
    script.main(["--csv", arquivo, "--gravar"])
    assert len(conexoes) == 1 and "executemany" not in eventos and "Cancelado: nada foi gravado" in capsys.readouterr().out


def test_sem_terminal_para_responder_cancela(arquivo, monkeypatch, capsys):
    eventos = []
    conexoes = _banco_falso(monkeypatch, [[]], eventos)

    def sem_entrada(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", sem_entrada)
    script.main(["--csv", arquivo, "--gravar"])
    assert len(conexoes) == 1 and "Cancelado" in capsys.readouterr().out


def test_sim_dispensa_a_confirmacao_digitada(arquivo, monkeypatch):
    eventos = []
    _banco_falso(monkeypatch, [[]], eventos)

    def nao_deveria_perguntar(prompt=""):
        raise AssertionError("não era para perguntar")

    monkeypatch.setattr("builtins.input", nao_deveria_perguntar)
    script.main(["--csv", arquivo, "--gravar", "--sim"])
    assert "executemany" in eventos


def test_previsao_mostra_o_que_um_operador_editou_e_sera_preservado(arquivo, monkeypatch, capsys):
    eventos = []
    existentes = [{"id_sku": "1", "atualizado_por": "Maria Souza (maria@zubale.com)"}, {"id_sku": "2", "atualizado_por": OPERADOR_CARGA_INICIAL}]
    _banco_falso(monkeypatch, [[existentes]], eventos)  # 1ª conexão: o 1º fetch devolve a lista de existentes
    monkeypatch.setattr("builtins.input", lambda prompt="": "nao")
    script.main(["--csv", arquivo, "--gravar"])
    saida = capsys.readouterr().out
    assert "itens PRESERVADOS (um operador editou o peso na tela): 1" in saida and "itens novos: 0" in saida
    assert "itens já existentes que serão atualizados: 1" in saida


def test_incluir_sem_peso_poe_o_item_na_fila_e_sobrescrever_remove_a_protecao(arquivo, monkeypatch):
    eventos = []
    conexoes = _banco_falso(monkeypatch, [[]], eventos)
    script.main(["--csv", arquivo, "--gravar", "--sim", "--incluir-sem-peso", "--sobrescrever-editados"])
    chamadas = [c for c in conexoes[-1].chamadas if c[0] == "executemany"]
    assert "atualizado_por IS NULL OR" not in chamadas[0][1]
    assert "DO NOTHING" in chamadas[1][1] and chamadas[1][2] == [("3", "r3", "Ovo 20 un", 203)]


def test_tabela_inexistente_orienta_a_rodar_o_alembic(arquivo, monkeypatch):
    _banco_falso(monkeypatch, [[]], [], erro_no_fetch=asyncpg.UndefinedTableError("relation does not exist"))
    with pytest.raises(SystemExit) as erro:
        script.main(["--csv", arquivo, "--gravar", "--sim"])
    assert "alembic upgrade head" in str(erro.value)


def test_database_url_invalida_nao_vaza_a_senha(arquivo, monkeypatch):
    _sem_banco(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "mysql://usuario:segredo@host/db")
    with pytest.raises(SystemExit) as erro:
        script.main(["--csv", arquivo, "--gravar", "--sim"])
    assert "inválida" in str(erro.value) and "segredo" not in str(erro.value)


def test_reconecta_se_a_conexao_cair_e_desiste_depois_de_3_tentativas(monkeypatch):
    tentativas = []
    esperas = []

    async def instavel(dsn):
        tentativas.append(1)
        if len(tentativas) < 3:
            raise ConnectionResetError("derrubada")
        return FakeConn()

    async def dormir(segundos):
        esperas.append(segundos)

    monkeypatch.setattr(script, "conectar", instavel)

    async def operacao(conn):
        return "ok"

    assert asyncio.run(script.com_conexao("dsn", operacao, esperas=(2, 5), dormir=dormir)) == "ok"
    assert len(tentativas) == 3 and esperas == [2, 5]

    tentativas.clear()

    async def sempre_cai(dsn):
        tentativas.append(1)
        raise ConnectionResetError("derrubada")

    monkeypatch.setattr(script, "conectar", sempre_cai)
    with pytest.raises(ConnectionResetError):
        asyncio.run(script.com_conexao("dsn", operacao, esperas=(0,), dormir=dormir))
    assert len(tentativas) == 3


def test_script_nao_tem_credencial_nem_usa_psycopg2():
    texto = (RAIZ / "scripts" / "carregar_item_pesos.py").read_text(encoding="utf-8")
    assert "psycopg2" not in texto.replace("psycopg2 pode estar bloqueado", "") and "import asyncpg" in texto
    import re

    assert not re.search(r"postgres(ql)?://[^\s\"']+:[^\s\"'@]+@(?!host)", texto)
    assert 'os.getenv("DATABASE_URL")' in texto
