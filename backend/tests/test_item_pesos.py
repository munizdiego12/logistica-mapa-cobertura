"""Pesos dos itens: valores, CSV em português, consultas (com conexão simulada), migration e configuração do Alembic."""
import asyncio
import importlib.util
import os
import re
import sqlite3
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from backend import db_url, item_pesos as ip
from backend.tests.fakes_asyncpg import FakeConn

RAIZ = Path(__file__).resolve().parents[2]
BACKEND = RAIZ / "backend"


def rodar(corrotina):
    return asyncio.run(corrotina)


# ----------------------------------------------------------------------------------------------------------
# Valores
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("entrada, esperado", [
    ("1,5", "1.5000"), ("1.5", "1.5000"), ("0,045", "0.0450"), ("2 kg", "2.0000"), ("2KG", "2.0000"),
    (" 3 ", "3.0000"), (0.5, "0.5000"), (3, "3.0000"), (Decimal("1.25"), "1.2500"), ("1.000", "1.0000"),
    ("1.234,56", "1234.5600") if False else ("999,9", "999.9000"), ("1000", "1000.0000"),
])
def test_interpretar_peso_aceita_virgula_ponto_e_unidade(entrada, esperado):
    assert ip.interpretar_peso(entrada) == Decimal(esperado)


@pytest.mark.parametrize("vazio", [None, "", "   ", "-", "\xa0"])
def test_peso_em_branco_e_sem_peso(vazio):
    assert ip.interpretar_peso(vazio) is None


@pytest.mark.parametrize("ruim, trecho", [
    ("abc", "não é um número"), ("12,3,4", "não é um número"), ("-2", "não é um número"), ("0", "maior que zero"),
    ("0,00001", "maior que zero"), ("1000,01", "passa de"), ("1.234,56", "passa de"), (True, "inválido"),
    (float("nan"), "inválido"), (float("inf"), "inválido"),
])
def test_interpretar_peso_recusa_valores_invalidos(ruim, trecho):
    with pytest.raises(ValueError, match=trecho):
        ip.interpretar_peso(ruim)


def test_confianca_normaliza_acento_e_caixa_e_recusa_o_resto():
    assert [ip.normalizar_confianca(x) for x in ("Alta", "média", "MEDIA", " baixa ")] == ["alta", "media", "media", "baixa"]
    assert ip.normalizar_confianca("") is None and ip.normalizar_confianca(None) is None
    with pytest.raises(ValueError, match="inválida"):
        ip.normalizar_confianca("talvez")


def test_id_sku_aceita_numero_da_planilha_e_recusa_vazio_ou_com_espaco():
    assert ip.normalizar_id_sku(" 27439.0 ") == "27439" and ip.normalizar_id_sku("AB-12") == "AB-12"
    for ruim in ("", "   ", None, "a b", "x" * 41):
        with pytest.raises(ValueError):
            ip.normalizar_id_sku(ruim)


def test_escapar_like():
    assert ip.escapar_like("50%_a\\b") == "50\\%\\_a\\\\b"


# ----------------------------------------------------------------------------------------------------------
# CSV em português
# ----------------------------------------------------------------------------------------------------------
def _csv(tmp_path, texto, nome="p.csv", codificacao="utf-8"):
    caminho = tmp_path / nome
    caminho.write_bytes(texto.encode(codificacao))
    return caminho


CABECALHO = "id_sku;reference_code;nome;peso_kg_sugerido;fonte;confianca;unidades_vendidas"


def test_csv_ponto_e_virgula_com_virgula_decimal(tmp_path):
    r = ip.ler_csv(_csv(tmp_path, CABECALHO + "\n1;r1;Açúcar 1kg;1;nome;alta;2.624\n2;r2;Maionese;1,05;manual;Média;82\n3;r3;Ovo;;;;203\n"))
    assert r.delimitador == ";" and r.coluna_peso == "peso_kg_sugerido"
    a, b, c = r.linhas
    assert (a.id_sku, a.peso, a.status, a.confianca, a.unidades) == ("1", Decimal("1.0000"), "com_peso", "alta", 2624)  # 2.624 = milhar
    assert (b.peso, b.confianca, b.fonte) == (Decimal("1.0500"), "media", "manual")
    assert (c.status, c.peso, c.unidades) == ("sem_peso", None, 203)


def test_csv_virgula_como_separador_com_decimal_entre_aspas(tmp_path):
    texto = 'id_sku,nome,peso_kg,fonte,confianca,unidades_vendidas\n7,"Óleo, 900ml","0,9",nome,alta,10\n8,Sal,,,,5\n'
    r = ip.ler_csv(_csv(tmp_path, texto))
    assert r.delimitador == "," and r.coluna_peso == "peso_kg"
    assert (r.linhas[0].nome, r.linhas[0].peso) == ("Óleo, 900ml", Decimal("0.9000")) and r.linhas[1].status == "sem_peso"


def test_csv_windows_1252_e_bom(tmp_path):
    texto = CABECALHO + "\n1;r1;Açúcar;2,5;nome;alta;1\n"
    assert ip.ler_csv(_csv(tmp_path, texto, codificacao="cp1252")).linhas[0].nome == "Açúcar"
    r = ip.ler_csv(_csv(tmp_path, texto, "bom.csv", codificacao="utf-8-sig"))
    assert r.codificacao == "utf-8" and r.linhas[0].nome == "Açúcar"


def test_csv_classifica_linhas_com_peso_sem_peso_invalidas_e_repetidas(tmp_path):
    texto = CABECALHO + "\n".join(["", "1;r1;A;1;nome;alta;1", "2;r2;B;;;;1", "3;r3;C;abc;;;1", "4;r4;D;2;nome;talvez;1",
                                    "1;r1;A de novo;1,5;manual;alta;1", ";r9;sem id;1;;;1", "", "5;r5;E;1000,5;;;1"])
    r = ip.ler_csv(_csv(tmp_path, texto))
    resumo = ip.resumir(r)
    assert resumo["com_peso"] == 1 and resumo["sem_peso"] == 1 and resumo["duplicado_ignorado"] == 1
    assert resumo["invalido"] == 4 and resumo["linhas"] == 7  # abc, confiança, sem id, peso acima do máximo
    motivos = " | ".join(m for _, _, m in resumo["invalidos_exemplos"])
    assert "não é um número" in motivos and "confiança 'talvez'" in motivos and "id_sku" in motivos and "passa de" in motivos
    vale = [l for l in r.linhas if l.status == "com_peso"][0]
    assert vale.id_sku == "1" and vale.peso == Decimal("1.5000")  # a última linha do mesmo SKU vale


def test_csv_aponta_pesos_suspeitos_e_unidades_ilegiveis(tmp_path):
    r = ip.ler_csv(_csv(tmp_path, CABECALHO + "\n1;;Saco;45;;;1\n2;;Hastes;0,001;;;1\n3;;Normal;1;;;xyz\n"))
    resumo = ip.resumir(r)
    assert resumo["total_suspeitos"] == 2 and {s[1] for s in resumo["suspeitos"]} == {"1", "2"}
    assert any("ilegíveis" in a for a in r.avisos) and r.linhas[2].unidades == 0


def test_csv_prioriza_a_coluna_peso_kg_sobre_a_sugerida(tmp_path):
    texto = "id_sku;nome;peso_kg_sugerido;peso_kg\n1;A;9;2\n"
    r = ip.ler_csv(_csv(tmp_path, texto))
    assert r.coluna_peso == "peso_kg" and r.linhas[0].peso == Decimal("2.0000")


def test_csv_sem_as_colunas_certas_da_erro_claro(tmp_path):
    with pytest.raises(ValueError, match="id_sku e peso"):
        ip.ler_csv(_csv(tmp_path, "produto;valor\nA;1\n"))


def test_fonte_padrao_e_confianca_so_com_peso(tmp_path):
    r = ip.ler_csv(_csv(tmp_path, "id_sku;peso_kg;confianca\n1;2;alta\n2;;baixa\n"))
    assert r.linhas[0].fonte == ip.FONTE_PLANILHA and r.linhas[1].confianca is None


# ----------------------------------------------------------------------------------------------------------
# Consultas (conexão simulada)
# ----------------------------------------------------------------------------------------------------------
def _item(**kw):
    base = {"id_sku": "1", "reference_code": "r1", "nome": "Açúcar", "peso_kg": Decimal("1.0000"), "fonte": "nome",
            "confianca": "alta", "unidades_vendidas": 10, "atualizado_em": None, "atualizado_por": None}
    base.update(kw)
    return base


def test_listar_escapa_a_busca_limita_e_avisa_quando_tem_mais():
    conn = FakeConn([[_item(id_sku=str(i)) for i in range(6)]])
    r = rodar(ip.listar(conn, "50%", True, limite=5, deslocamento=10))
    _, sql, args = conn.chamadas[0]
    assert args == ("50\\%", "50%", True, 6, 10) and "ORDER BY unidades_vendidas DESC" in sql
    assert len(r["itens"]) == 5 and r["tem_mais"] is True and r["itens"][0]["peso_kg"] == 1.0
    conn = FakeConn([[_item()]])
    assert rodar(ip.listar(conn, "  ", False, limite=9999))["tem_mais"] is False
    assert conn.chamadas[0][2] == (None, None, False, ip.LIMITE_MAXIMO_LISTA + 1, 0)


def test_resumo_conta_com_e_sem_peso():
    assert rodar(ip.resumo(FakeConn([{"total": 10, "com_peso": 7}]))) == {"total": 10, "com_peso": 7, "sem_peso": 3}


def test_atualizar_peso_registra_quem_e_quando_e_normaliza():
    conn = FakeConn([_item(peso_kg=Decimal("1.5"))])
    r = rodar(ip.atualizar_peso(conn, "27439.0", "1,5", "Média", "Maria (maria@x.com)"))
    _, sql, args = conn.chamadas[0]
    assert "atualizado_em = now()" in sql and "atualizado_por = $5" in sql
    assert args == ("27439", Decimal("1.5000"), "manual", "media", "Maria (maria@x.com)")
    assert r["peso_kg"] == 1.5


def test_atualizar_peso_vazio_tira_o_peso_e_a_confianca():
    conn = FakeConn([_item(peso_kg=None)])
    rodar(ip.atualizar_peso(conn, "1", None, "alta", "Maria (m@x.com)"))
    assert conn.chamadas[0][2] == ("1", None, None, None, "Maria (m@x.com)")


def test_atualizar_peso_de_sku_inexistente_devolve_none_e_peso_invalido_levanta():
    assert rodar(ip.atualizar_peso(FakeConn([None]), "999", "1", "alta", "x")) is None
    with pytest.raises(ValueError):
        rodar(ip.atualizar_peso(FakeConn(), "1", "0", "alta", "x"))
    with pytest.raises(ValueError, match="inválida"):
        rodar(ip.atualizar_peso(FakeConn(), "1", "1", "talvez", "x"))


def test_skus_vistos_somam_unidades_e_so_os_novos_entram_na_fila():
    conn = FakeConn([[{"id_sku": "1"}]])  # o SKU 1 já existe
    r = rodar(ip.registrar_skus_vistos(conn, [
        {"id_sku": "1", "quantidade": 3}, {"id_sku": "1", "quantidade": 2, "nome": "A"},
        {"id_sku": "2", "quantidade": 4, "nome": " Novo ", "reference_code": "r2"}]))
    assert r == {"novos": 1, "ja_existiam": 1}
    _, sql, linhas = [c for c in conn.chamadas if c[0] == "executemany"][0]
    assert sorted(linhas) == [("1", None, "A", 5), ("2", "r2", "Novo", 4)]
    assert "ON CONFLICT (id_sku) DO UPDATE" in sql and "peso_kg" not in sql and "atualizado_por" not in sql  # não mexe no peso
    assert rodar(ip.registrar_skus_vistos(FakeConn(), [])) == {"novos": 0, "ja_existiam": 0}
    with pytest.raises(ValueError):
        rodar(ip.registrar_skus_vistos(FakeConn(), [{"id_sku": "1", "quantidade": 0}]))


def _linhas_para_gravar(tmp_path):
    texto = CABECALHO + "\n1;r1;A;1;nome;alta;10\n2;r2;B;;;;5\n3;r3;C;2,5;manual;baixa;1\n"
    return ip.ler_csv(_csv(tmp_path, texto))


def test_separar_para_gravar_ignora_sem_peso_por_padrao(tmp_path):
    r = _linhas_para_gravar(tmp_path)
    com, sem = ip.separar_para_gravar(r)
    assert [l.id_sku for l in com] == ["1", "3"] and sem == []
    com, sem = ip.separar_para_gravar(r, incluir_sem_peso=True)
    assert [l.id_sku for l in sem] == ["2"]


def test_previsao_nao_escreve_e_preserva_o_que_operador_editou(tmp_path):
    com, sem = ip.separar_para_gravar(_linhas_para_gravar(tmp_path), True)
    existentes = [{"id_sku": "1", "atualizado_por": "Maria (m@x.com)"}, {"id_sku": "3", "atualizado_por": ip.OPERADOR_CARGA_INICIAL}]
    conn = FakeConn([existentes])
    p = rodar(ip.prever_carga(conn, com, sem))
    assert p == {"novos": 0, "atualizados": 1, "preservados_editados": 1, "sem_peso_novos": 1, "sem_peso_ja_existentes": 0}
    assert all(c[0] == "fetch" for c in conn.chamadas)  # só leitura
    p2 = rodar(ip.prever_carga(FakeConn([existentes]), com, sem, sobrescrever_editados=True))
    assert p2["preservados_editados"] == 0 and p2["atualizados"] == 2


def test_gravar_carga_usa_upsert_numa_transacao_e_protege_edicoes(tmp_path):
    com, sem = ip.separar_para_gravar(_linhas_para_gravar(tmp_path), True)
    conn = FakeConn()
    rodar(ip.gravar_carga(conn, com, sem))
    tipos = [c[0] for c in conn.chamadas]
    assert tipos == ["begin", "executemany", "executemany", "commit"]
    _, sql, linhas = conn.chamadas[1]
    assert "ON CONFLICT (id_sku) DO UPDATE" in sql and "WHERE item_pesos.atualizado_por IS NULL OR item_pesos.atualizado_por = $8" in sql
    assert linhas[0] == ("1", "r1", "A", Decimal("1.0000"), "nome", "alta", 10, ip.OPERADOR_CARGA_INICIAL)
    assert "DO NOTHING" in conn.chamadas[2][1] and conn.chamadas[2][2] == [("2", "r2", "B", 5)]
    livre = FakeConn()
    rodar(ip.gravar_carga(livre, com, [], sobrescrever_editados=True))
    assert "atualizado_por IS NULL OR" not in livre.chamadas[1][1]


def test_sql_nunca_apaga_nada():
    todos = " ".join(getattr(ip, n) for n in dir(ip) if n.startswith("SQL_"))
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE)\b", todos, re.IGNORECASE)


# ----------------------------------------------------------------------------------------------------------
# Migration e Alembic
# ----------------------------------------------------------------------------------------------------------
def _carregar_migration(nome):
    spec = importlib.util.spec_from_file_location(nome, BACKEND / "migrations" / "versions" / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _aplicar(modulo, conexao, direcao="upgrade"):
    with Operations.context(MigrationContext.configure(conexao)):
        getattr(modulo, direcao)()


def test_migration_cria_a_tabela_com_as_colunas_pedidas_e_regras():
    engine = sa.create_engine("sqlite://")
    modulo = _carregar_migration("0002_item_pesos")
    with engine.begin() as conexao:
        _aplicar(modulo, conexao)
    colunas = [c["name"] for c in sa.inspect(engine).get_columns("item_pesos")]
    assert colunas == ["id_sku", "reference_code", "nome", "peso_kg", "fonte", "confianca", "unidades_vendidas", "atualizado_em", "atualizado_por"]
    assert sa.inspect(engine).get_pk_constraint("item_pesos")["constrained_columns"] == ["id_sku"]
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO item_pesos (id_sku, peso_kg, confianca) VALUES ('1', 1.5, 'alta')"))
        c.execute(sa.text("INSERT INTO item_pesos (id_sku) VALUES ('2')"))  # novo SKU: sem peso
        linha = c.execute(sa.text("SELECT unidades_vendidas, atualizado_em, atualizado_por, peso_kg FROM item_pesos WHERE id_sku = '2'")).one()
    assert linha[0] == 0 and linha[1] is not None and linha[2] is None and linha[3] is None
    for sql in ("INSERT INTO item_pesos (id_sku, peso_kg) VALUES ('3', 0)", "INSERT INTO item_pesos (id_sku, peso_kg) VALUES ('4', 1000.1)",
                "INSERT INTO item_pesos (id_sku, peso_kg) VALUES ('5', -1)", "INSERT INTO item_pesos (id_sku, confianca) VALUES ('6', 'talvez')"):
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as c:
                c.execute(sa.text(sql))
    with engine.begin() as c:
        with pytest.raises(sa.exc.IntegrityError):  # id_sku é a chave
            c.execute(sa.text("INSERT INTO item_pesos (id_sku) VALUES ('1')"))


def test_migration_desfaz_com_downgrade():
    engine = sa.create_engine("sqlite://")
    modulo = _carregar_migration("0002_item_pesos")
    with engine.begin() as conexao:
        _aplicar(modulo, conexao)
        _aplicar(modulo, conexao, "downgrade")
    assert "item_pesos" not in sa.inspect(engine).get_table_names()


def test_alembic_tem_uma_cabeca_e_a_ordem_certa():
    script = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert script.get_heads() == ["0002"]
    assert [r.revision for r in script.walk_revisions()] == ["0002", "0001"]
    assert script.get_revision("0001").down_revision is None


def test_alembic_nao_tem_credencial_nem_url_no_arquivo():
    for arquivo in (BACKEND / "alembic.ini", BACKEND / "migrations" / "env.py"):
        texto = arquivo.read_text(encoding="utf-8")
        assert not re.search(r"postgres(ql)?(\+\w+)?://[^\s\"']*:[^\s\"'@]+@", texto), arquivo
        assert "sqlalchemy.url" not in texto.replace("# ", "") or "sqlalchemy.url =" not in texto
    assert "DATABASE_URL" in (BACKEND / "migrations" / "env.py").read_text(encoding="utf-8")


def _alembic(*args, ambiente=None):
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    env.update({"PYTHONIOENCODING": "utf-8", **(ambiente or {})})
    return subprocess.run([sys.executable, "-m", "alembic", "-c", str(BACKEND / "alembic.ini"), *args],
                          cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)


def test_alembic_sem_database_url_para_com_mensagem_clara():
    r = _alembic("upgrade", "head")
    assert r.returncode != 0 and "DATABASE_URL" in (r.stderr + r.stdout)


def test_alembic_gera_o_sql_sem_conectar_no_banco():
    r = _alembic("upgrade", "head", "--sql")
    sql = r.stdout
    assert r.returncode == 0, r.stderr
    assert "CREATE TABLE item_pesos" in sql and "CREATE INDEX ix_item_pesos_fila_sem_peso" in sql and "WHERE peso_kg IS NULL" in sql
    assert "ck_item_pesos_peso_plausivel" in sql and "ck_item_pesos_confianca" in sql
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE)\b", sql, re.IGNORECASE)


def test_requirements_tem_alembic_e_continua_em_utf8():
    bruto = (BACKEND / "requirements.txt").read_bytes()
    assert not bruto.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")) and b"\x00" not in bruto
    assert re.search(r"^alembic[<>=]", bruto.decode("utf-8"), re.MULTILINE)


# ----------------------------------------------------------------------------------------------------------
# Conversão da URL do banco
# ----------------------------------------------------------------------------------------------------------
NEON = "postgres://usuario:segredo@ep-exemplo-123.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


def test_dsn_asyncpg_tira_channel_binding_e_mantem_sslmode():
    dsn = db_url.dsn_asyncpg(NEON)
    assert dsn.startswith("postgresql://usuario:segredo@ep-exemplo-123") and "sslmode=require" in dsn and "channel_binding" not in dsn


def test_url_sqlalchemy_asyncpg_troca_driver_e_vira_ssl_true():
    url, args = db_url.url_sqlalchemy_asyncpg(NEON)
    assert url == "postgresql+asyncpg://usuario:segredo@ep-exemplo-123.sa-east-1.aws.neon.tech/neondb" and args == {"ssl": True}
    url, args = db_url.url_sqlalchemy_asyncpg("postgresql://u:p@localhost:5432/db")
    assert url == "postgresql+asyncpg://u:p@localhost:5432/db" and args == {}


def test_url_invalida_e_senha_mascarada():
    for ruim in ("", "   ", "mysql://u:p@h/db", None):
        with pytest.raises(ValueError):
            db_url.normalizar_url(ruim)
    assert "segredo" not in db_url.mascarar_senha(NEON) and "***" in db_url.mascarar_senha(NEON)
