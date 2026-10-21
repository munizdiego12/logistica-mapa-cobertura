"""Etapa 6a: lojas (validações, CSV de importação, CRUD, desativar), cobertura pela coordenada da loja e hub da roteirização."""
import asyncio
import importlib.util
import re
from datetime import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import ibge
import lojas
import main
from backend.tests.fakes_asyncpg import ConexaoSqlite, FakePool, criar_banco_sqlite

BACKEND = Path(__file__).resolve().parents[1]
ARQUIVO_MIGRACAO = BACKEND / "migrations" / "versions" / "0007_lojas.py"
OPERADOR = "Maria Souza (maria@zubale.com)"


def _rodar(corotina):
    return asyncio.run(corotina)


def _loja(**extra):
    base = {"nome": "Atacadão Guarujá", "uf": "SP", "endereco": "Av. Santos Dumont, 100", "lat": -23.993, "lng": -46.2564}
    base.update(extra)
    return base


@pytest.fixture
def banco():
    return criar_banco_sqlite()


# ----------------------------------------------------------------------------------------------------------
# Coordenadas e valores
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("entrada, esperado", [("-23,5614", -23.5614), ("-23.5614", -23.5614), (" -23,5614 ", -23.5614), (-23.5, -23.5),
                                               ("1.234,5", 1234.5), ("−23,5", -23.5), ("0", 0.0)])
def test_coordenada_aceita_virgula_decimal_e_ponto(entrada, esperado):
    assert lojas.interpretar_coordenada(entrada, "latitude") == esperado


@pytest.mark.parametrize("entrada", ["", "abc", "-23,5,6", "-23.561.400", None, True, "12 graus", float("nan")])
def test_coordenada_ilegivel_da_erro_em_linguagem_do_operador(entrada):
    with pytest.raises(ValueError) as erro:
        lojas.interpretar_coordenada(entrada, "latitude")
    assert "A latitude precisa ser um número" in str(erro.value)


@pytest.mark.parametrize("lat, lng, esperado", [
    (-23.5, -46.6, "ok"), (-34, -34, "ok"), (6, -74, "ok"), (-34, -74, "ok"), (6, -34, "ok"),  # os limites valem
    (-34.0001, -46, "fora_do_brasil"), (6.0001, -46, "fora_do_brasil"), (-23, -74.0001, "fora_do_brasil"), (-23, -33.9999, "fora_do_brasil"),
    (-46.6333, -23.5505, "trocadas"), (-47.0, -22.9, "trocadas"), (40.7, -74.0, "fora_do_brasil"),
])
def test_classificacao_das_coordenadas_no_brasil(lat, lng, esperado):
    assert lojas.classificar_coordenadas(lat, lng) == esperado


def test_validar_coordenadas_recusa_trocadas_e_fora_do_brasil_com_mensagens_diferentes():
    assert lojas.validar_coordenadas("-23,5614", "-46,6333") == (-23.5614, -46.6333)
    with pytest.raises(ValueError) as trocadas:
        lojas.validar_coordenadas(-46.6333, -23.5505)
    assert "trocadas" in str(trocadas.value)
    with pytest.raises(ValueError) as fora:
        lojas.validar_coordenadas(40.7, -74.0)
    assert "fora do Brasil" in str(fora.value)


def test_uf_aceita_sigla_e_nome_do_estado():
    assert lojas.normalizar_uf("sp") == "SP" and lojas.normalizar_uf("São Paulo") == "SP" and lojas.normalizar_uf("  rio  grande do sul ") == "RS"
    assert lojas.normalizar_uf("") is None and lojas.normalizar_uf(None) is None
    for ruim in ("ZZ", "Atlântida", "S"):
        with pytest.raises(ValueError):
            lojas.normalizar_uf(ruim)
    with pytest.raises(ValueError):
        lojas.normalizar_uf("", obrigatorio=True)


def test_janelas_padrao_noite_opcional_e_inicio_antes_do_fim():
    padrao = lojas.montar_janelas({})
    assert (padrao["janela_manha_inicio"], padrao["janela_manha_fim"]) == (time(8), time(13))
    assert (padrao["janela_tarde_inicio"], padrao["janela_tarde_fim"]) == (time(13), time(18))
    assert (padrao["janela_noite_inicio"], padrao["janela_noite_fim"]) == (time(18), time(21))
    sem_noite = lojas.montar_janelas({"usa_noite": False, "janela_noite_inicio": "19:00"})
    assert sem_noite["janela_noite_inicio"] is None and sem_noite["janela_noite_fim"] is None
    assert lojas.montar_janelas({"janela_manha_inicio": "7:30", "janela_manha_fim": "12"})["janela_manha_inicio"] == time(7, 30)
    for ruim in ({"janela_manha_inicio": "14:00"}, {"janela_tarde_fim": "13:00"}, {"janela_noite_inicio": "22:00"}, {"janela_manha_inicio": "25:00"}, {"janela_manha_fim": "abc"}):
        with pytest.raises(ValueError):
            lojas.montar_janelas(ruim)


def test_capacidades_sao_opcionais_e_so_aceitam_numero_positivo():
    assert lojas.interpretar_capacidade(None, "peso") is None and lojas.interpretar_capacidade("  ", "peso") is None
    assert float(lojas.interpretar_capacidade("12.500,5", "peso")) == 12500.5
    for ruim in (0, "-1", "muito"):
        with pytest.raises(ValueError):
            lojas.interpretar_capacidade(ruim, "volume")


def test_mensagens_de_validacao_sem_termo_tecnico():
    textos = []
    for dados in ({"nome": ""}, _loja(uf="ZZ"), _loja(lat="abc"), _loja(lat=-46.6, lng=-23.5), _loja(lat=40, lng=-74), _loja(capacidade_peso=-1),
                  _loja(janela_manha_inicio="14:00"), _loja(nome="x" * 200)):
        try:
            lojas.validar_loja(dados)
        except ValueError as erro:
            textos.append(str(erro))
    assert len(textos) == 8
    assert not any(re.search(r"sql|tabela|banco|api|json|token|null|constraint|asyncpg|float", t, re.IGNORECASE) for t in textos), textos


def test_hover_mostra_nome_endereco_e_uf_uma_informacao_por_linha_so_o_que_existir():
    assert lojas.texto_do_hover(_loja()) == ["Atacadão Guarujá", "Av. Santos Dumont, 100", "SP"]
    assert lojas.texto_do_hover(_loja(endereco=None)) == ["Atacadão Guarujá", "SP"]
    assert lojas.texto_do_hover(_loja(uf=None, endereco="")) == ["Atacadão Guarujá"]
    assert "filial" not in " ".join(lojas.texto_do_hover(_loja())).lower()


# ----------------------------------------------------------------------------------------------------------
# CSV
# ----------------------------------------------------------------------------------------------------------
def _csv(tmp_path, texto, codificacao="utf-8", nome="lojas.csv"):
    caminho = tmp_path / nome
    caminho.write_bytes(texto.encode(codificacao))
    return caminho


CSV_COLUNAS = (
    'Nome;Estado;Endereço;Latitude;Longitude\n'
    '"Atacadão Guarujá";SP;"Av. Santos Dumont, 100";"-23,9930";"-46,2564"\n'
    'Atacadão Campinas;São Paulo;;-22.9099;-47.0626\n'
    'Atacadão Trocada;SP;Rua A;-46,6333;-23,5505\n'
    'Atacadão Nova York;SP;;40,7;-74,0\n'
    ';SP;sem nome;-23,5;-46,6\n'
    'Atacadão Guarujá;SP;;"-23,9931";"-46,2565"\n'
    'Atacadão Estado Ruim;ZZ;;-23,5;-46,6\n'
    'Atacadão Texto;SP;;abc;-46,6\n'
    'Atacadão Sem Estado;;;-23,5;-46,6\n'
)


def test_csv_em_colunas_com_virgula_decimal_aspas_e_ponto_e_virgula(tmp_path):
    r = lojas.ler_csv_lojas(_csv(tmp_path, CSV_COLUNAS))
    assert (r.formato, r.delimitador, r.codificacao) == ("colunas", ";", "utf-8")
    por_nome = {}
    for l in r.linhas:
        por_nome.setdefault(l.nome, []).append(l)
    guaruja_primeira, guaruja_ultima = por_nome["Atacadão Guarujá"]
    assert guaruja_primeira.status == "duplicada_ignorada" and "vale a linha 7" in guaruja_primeira.motivo
    assert guaruja_ultima.status == "valida" and (guaruja_ultima.lat, guaruja_ultima.lng) == (-23.9931, -46.2565)
    campinas = por_nome["Atacadão Campinas"][0]
    assert (campinas.status, campinas.uf, campinas.sem_endereco, campinas.lat) == ("valida", "SP", True, -22.9099)  # "São Paulo" vira SP
    assert (guaruja_primeira.endereco, guaruja_primeira.lat) == ("Av. Santos Dumont, 100", -23.993)  # aspas e vírgula decimal
    assert por_nome["Atacadão Trocada"][0].status == "suspeita" and por_nome["Atacadão Trocada"][0].suspeita == "trocadas"
    assert "trocadas" in por_nome["Atacadão Trocada"][0].motivo and "-23.5505" in por_nome["Atacadão Trocada"][0].motivo.replace("-23,5505", "-23.5505")
    assert por_nome["Atacadão Nova York"][0].suspeita == "fora_do_brasil"
    assert por_nome["Atacadão Estado Ruim"][0].status == "invalida" and "Estado inválido" in por_nome["Atacadão Estado Ruim"][0].motivo
    assert por_nome["Atacadão Texto"][0].status == "invalida" and "latitude" in por_nome["Atacadão Texto"][0].motivo
    assert por_nome["Atacadão Sem Estado"][0].status == "invalida"  # no CSV com coluna Estado o UF é exigido
    sem_nome = por_nome[""][0]
    assert sem_nome.status == "invalida" and "nome" in sem_nome.motivo.lower()


def test_resumo_conta_validas_sem_endereco_duplicadas_e_suspeitas(tmp_path):
    r = lojas.ler_csv_lojas(_csv(tmp_path, CSV_COLUNAS))
    resumo = lojas.resumir(r)
    assert resumo["linhas"] == 9
    assert resumo["validas"] == 2  # Guarujá (a última) e Campinas
    assert resumo["sem_endereco"] == 2 and resumo["sem_uf"] == 0  # Campinas e a última linha do Guarujá
    assert resumo["duplicadas"] == 1
    assert resumo["suspeitas"] == 2 and len(resumo["trocadas"]) == 1 and len(resumo["fora_do_brasil"]) == 1
    assert len(resumo["invalidas"]) == 4
    assert [l.nome for l in lojas.para_gravar(r)] == ["Atacadão Campinas", "Atacadão Guarujá"]  # suspeitas, inválidas e duplicadas ficam fora


def test_csv_com_virgula_como_separador_e_windows_1252(tmp_path):
    texto = 'Nome,Estado,Endereço,Latitude,Longitude\n"Atacadão São José",SC,"Rua do Açaí, 5","-27,5954","-48,5480"\n'
    r = lojas.ler_csv_lojas(_csv(tmp_path, texto, "cp1252"))
    assert (r.delimitador, r.codificacao) == (",", "windows-1252")
    assert (r.linhas[0].nome, r.linhas[0].endereco, r.linhas[0].lat, r.linhas[0].lng, r.linhas[0].status) == ("Atacadão São José", "Rua do Açaí, 5", -27.5954, -48.548, "valida")


def test_csv_utf8_com_bom_e_cabecalho_sem_acento_ou_em_maiusculas(tmp_path):
    texto = "﻿NOME;ESTADO;ENDERECO;LATITUDE;LONGITUDE\nLoja Um;rj;;-22,9;-43,2\n"
    r = lojas.ler_csv_lojas(_csv(tmp_path, texto))
    assert r.linhas[0].nome == "Loja Um" and r.linhas[0].uf == "RJ" and r.linhas[0].status == "valida"


CSV_MY_MAPS = (
    'WKT,name,description\n'
    '"POINT (-46.2564 -23.9930)",Atacadão Guarujá,"Av. Santos Dumont, 100"\n'
    '"POINT (-47.0626 -22.9099)",Atacadão Campinas,\n'
    '"POINT Z (-43.1729 -22.9068 0)",Atacadão Rio,Rua B\n'
    '"POINT (-23.5505 -46.6333)",Atacadão Trocada,\n'
    '"LINESTRING (0 0, 1 1)",Atacadão Linha,\n'
)


def test_formato_google_my_maps_wkt_longitude_primeiro_sem_estado(tmp_path):
    r = lojas.ler_csv_lojas(_csv(tmp_path, CSV_MY_MAPS))
    assert r.formato == "my_maps" and r.delimitador == ","
    guaruja, campinas, rio, trocada, linha = r.linhas
    assert (guaruja.lat, guaruja.lng, guaruja.endereco, guaruja.uf, guaruja.sem_uf, guaruja.status) == (-23.993, -46.2564, "Av. Santos Dumont, 100", None, True, "valida")
    assert (campinas.lat, campinas.lng, campinas.sem_endereco) == (-22.9099, -47.0626, True)
    assert (rio.lat, rio.lng, rio.status) == (-22.9068, -43.1729, "valida")  # POINT Z também vale
    assert trocada.status == "suspeita" and trocada.suspeita == "trocadas"  # WKT com latitude no lugar da longitude
    assert linha.status == "invalida" and "POINT" in linha.motivo
    resumo = lojas.resumir(r)
    assert (resumo["validas"], resumo["sem_uf"], resumo["sem_endereco"], resumo["suspeitas"], len(resumo["invalidas"])) == (3, 3, 1, 1, 1)


def test_csv_sem_as_colunas_certas_e_recusado_com_mensagem_clara(tmp_path):
    with pytest.raises(ValueError) as erro:
        lojas.ler_csv_lojas(_csv(tmp_path, "id;peso\n1;2\n"))
    assert "Nome, Estado, Endereço, Latitude e Longitude" in str(erro.value) and "My Maps" in str(erro.value)


def test_limites_da_faixa_do_brasil_no_csv(tmp_path):
    texto = ("Nome;Estado;Endereço;Latitude;Longitude\nA;SP;;-34;-74\nB;SP;;6;-34\nC;SP;;-34,0001;-50\nD;SP;;0;-33,9999\n")
    r = lojas.ler_csv_lojas(_csv(tmp_path, texto))
    assert [l.status for l in r.linhas] == ["valida", "valida", "suspeita", "suspeita"]


# ----------------------------------------------------------------------------------------------------------
# Banco (SQLite com o DDL real da 0007)
# ----------------------------------------------------------------------------------------------------------
def test_criar_loja_registra_quem_alterou_e_usa_as_janelas_padrao(banco):
    loja = _rodar(lojas.criar(banco, _loja(nome="  Atacadão   Guarujá ", uf="são paulo"), OPERADOR))
    assert (loja["nome"], loja["uf"], loja["ativo"], loja["atualizado_por"]) == ("Atacadão Guarujá", "SP", True, OPERADOR)
    assert (loja["janela_manha_inicio"], loja["janela_manha_fim"], loja["janela_tarde_inicio"], loja["janela_tarde_fim"]) == ("08:00", "13:00", "13:00", "18:00")
    assert (loja["janela_noite_inicio"], loja["janela_noite_fim"], loja["usa_noite"]) == ("18:00", "21:00", True)
    assert loja["capacidade_peso"] is None and loja["capacidade_volume"] is None
    assert "filial" not in loja


def test_nome_unico_sem_diferenca_de_maiusculas_e_espacos_inclusive_desativadas(banco):
    criada = _rodar(lojas.criar(banco, _loja(), OPERADOR))
    with pytest.raises(ValueError) as erro:
        _rodar(lojas.criar(banco, _loja(nome="ATACADãO  GUARUJá", lat=-23.9, lng=-46.2), OPERADOR))
    assert str(erro.value) == lojas.MSG_NOME_REPETIDO
    _rodar(lojas.atualizar(banco, criada["id"], _loja(ativo=False), OPERADOR))
    with pytest.raises(ValueError):
        _rodar(lojas.criar(banco, _loja(), OPERADOR))  # desativada ainda ocupa o nome
    outra = _rodar(lojas.criar(banco, _loja(nome="Atacadão Santos"), OPERADOR))
    with pytest.raises(ValueError):
        _rodar(lojas.atualizar(banco, outra["id"], _loja(nome="atacadão guarujá"), OPERADOR))
    assert _rodar(lojas.atualizar(banco, outra["id"], _loja(nome="Atacadão Santos", endereco="Rua Nova"), OPERADOR))["endereco"] == "Rua Nova"  # manter o próprio nome vale


def test_desativar_loja_nao_apaga_e_ela_deixa_de_servir_de_hub(banco):
    loja = _rodar(lojas.criar(banco, _loja(), OPERADOR))
    desativada = _rodar(lojas.atualizar(banco, loja["id"], _loja(ativo=False), "Ana (ana@zubale.com)"))
    assert desativada["ativo"] is False and desativada["atualizado_por"] == "Ana (ana@zubale.com)"
    assert [l["nome"] for l in _rodar(lojas.listar(banco))] == ["Atacadão Guarujá"]
    assert _rodar(lojas.listar(banco, incluir_inativas=False)) == []
    assert banco.db.execute("SELECT count(*) FROM lojas").fetchone()[0] == 1
    with pytest.raises(ValueError) as erro:
        _rodar(lojas.obter_ativa(banco, loja["id"]))
    assert str(erro.value) == lojas.MSG_INATIVA
    with pytest.raises(ValueError) as inexistente:
        _rodar(lojas.obter_ativa(banco, 9999))
    assert str(inexistente.value) == lojas.MSG_NAO_ENCONTRADA
    reativada = _rodar(lojas.atualizar(banco, loja["id"], _loja(ativo=True), OPERADOR))
    assert reativada["ativo"] is True and _rodar(lojas.obter_ativa(banco, loja["id"]))["id"] == loja["id"]


def test_noite_pode_nao_ser_usada(banco):
    loja = _rodar(lojas.criar(banco, _loja(usa_noite=False), OPERADOR))
    assert (loja["janela_noite_inicio"], loja["janela_noite_fim"], loja["usa_noite"]) == (None, None, False)


def test_banco_tambem_recusa_coordenada_fora_do_brasil_e_janela_invertida(banco):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        banco.db.execute("INSERT INTO lojas (nome, lat, lng) VALUES ('X', 40, -46)")
    with pytest.raises(sqlite3.IntegrityError):
        banco.db.execute("INSERT INTO lojas (nome, lat, lng, janela_manha_inicio, janela_manha_fim) VALUES ('Y', -23, -46, '14:00', '13:00')")
    with pytest.raises(sqlite3.IntegrityError):
        banco.db.execute("INSERT INTO lojas (nome, lat, lng, capacidade_peso) VALUES ('Z', -23, -46, 0)")


# ----------------------------------------------------------------------------------------------------------
# Migration 0007
# ----------------------------------------------------------------------------------------------------------
def test_migration_0007_idempotente_sem_apagar_e_sem_coluna_filial():
    spec = importlib.util.spec_from_file_location("migracao_0007", ARQUIVO_MIGRACAO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.down_revision == "0006"
    for comando in modulo.COMANDOS:
        assert not re.search(r"\b(DROP|TRUNCATE|DELETE|UPDATE|INSERT)\b", comando, re.IGNORECASE), comando
        assert "IF NOT EXISTS" in comando
    assert not re.search(r"\bfilial\b", " ".join(modulo.COMANDOS), re.IGNORECASE)
    conn = ConexaoSqlite()
    for _ in range(2):  # rodar de novo, como num banco já migrado
        for comando in modulo.COMANDOS:
            conn.db.execute(comando.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY").replace("TIMESTAMPTZ", "TIMESTAMP").replace("NOW()", "CURRENT_TIMESTAMP"))
    colunas = [l[1] for l in conn.db.execute("PRAGMA table_info(lojas)")]
    assert colunas == ["id", "nome", "uf", "endereco", "cidade", "lat", "lng", "ativo", "capacidade_peso", "capacidade_volume", "janela_manha_inicio", "janela_manha_fim",
                       "janela_tarde_inicio", "janela_tarde_fim", "janela_noite_inicio", "janela_noite_fim", "atualizado_em", "atualizado_por"]


# ----------------------------------------------------------------------------------------------------------
# Rotas HTTP
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


CORPO = {"nome": "Atacadão Guarujá", "uf": "SP", "endereco": "Av. Santos Dumont, 100", "lat": "-23,9930", "lng": "-46,2564"}


def test_api_criar_listar_editar_e_desativar_loja(api):
    cliente, banco = api
    r = cliente.post("/api/lojas", json=CORPO)
    assert r.status_code == 201 and r.json()["lat"] == -23.993 and r.json()["atualizado_por"] == OPERADOR
    id_loja = r.json()["id"]
    assert [l["nome"] for l in cliente.get("/api/lojas").json()] == ["Atacadão Guarujá"]
    editada = cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "endereco": "Rua Nova, 5", "capacidade_peso": "1.500,5"})
    assert editada.status_code == 200 and editada.json()["endereco"] == "Rua Nova, 5" and editada.json()["capacidade_peso"] == 1500.5
    desativada = cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "ativo": False})
    assert desativada.json()["ativo"] is False
    assert cliente.get("/api/lojas", params={"incluir_inativas": "false"}).json() == []
    assert len(cliente.get("/api/lojas").json()) == 1
    assert cliente.put("/api/lojas/9999", json=CORPO).status_code == 404
    assert cliente.delete(f"/api/lojas/{id_loja}").status_code == 405  # loja não é apagada


@pytest.mark.parametrize("mudanca, trecho", [
    ({"nome": ""}, "nome da loja"), ({"nome": "   "}, "nome da loja"), ({"uf": "ZZ"}, "Estado inválido"),
    ({"lat": "abc"}, "latitude precisa ser um número"), ({"lng": ""}, "longitude precisa ser um número"),
    ({"lat": "40", "lng": "-74"}, "fora do Brasil"), ({"lat": "-46,6333", "lng": "-23,5505"}, "trocadas"),
    ({"capacidade_volume": "-3"}, "capacidade de volume"), ({"janela_tarde_inicio": "19:00"}, "janela da tarde"),
])
def test_api_validacoes_em_linguagem_do_operador(api, mudanca, trecho):
    cliente, banco = api
    r = cliente.post("/api/lojas", json={**CORPO, **mudanca})
    assert r.status_code == 422 and trecho in r.json()["detail"], r.text
    assert banco.db.execute("SELECT count(*) FROM lojas").fetchone()[0] == 0


def test_api_nome_repetido_da_422(api):
    cliente, banco = api
    cliente.post("/api/lojas", json=CORPO)
    r = cliente.post("/api/lojas", json={**CORPO, "nome": "atacadão guarujá"})
    assert r.status_code == 422 and r.json()["detail"] == lojas.MSG_NOME_REPETIDO


@pytest.mark.parametrize("metodo, caminho, args", [
    ("get", "/api/lojas", {}), ("post", "/api/lojas", {"json": CORPO}), ("put", "/api/lojas/1", {"json": CORPO}),
])
def test_rotas_de_lojas_exigem_login(metodo, caminho, args):
    main.app.dependency_overrides.clear()
    cliente = TestClient(main.app)
    assert getattr(cliente, metodo)(caminho, **args).status_code == 401
    assert getattr(cliente, metodo)(caminho, headers={"Authorization": "Bearer lixo"}, **args).status_code == 401


def test_cadastro_de_lojas_indisponivel_vira_mensagem_clara(monkeypatch):
    async def sem_pool():
        return None

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", sem_pool)
    try:
        r = TestClient(main.app).get("/api/lojas")
        assert r.status_code == 503 and "cadastro de lojas não está disponível" in r.json()["detail"]
    finally:
        main.app.dependency_overrides.clear()


# ----------------------------------------------------------------------------------------------------------
# Cobertura e roteirização pela coordenada da loja (sem geocodificar)
# ----------------------------------------------------------------------------------------------------------
def _prefixo(prefixo, distancia, cidade="Guarujá", uf="SP", cod=3518701):
    return {"prefixo": prefixo, "uf": uf, "cod_municipio": cod, "cidade": cidade, "localidade": "CENTRO", "localidade_pct": 100.0,
            "lat": -23.99, "lon": -46.25, "n_enderecos": 100, "dispersao_km": 0.5, "distancia_km": distancia}


@pytest.fixture
def cobertura_api(api, monkeypatch):
    cliente, banco = api
    chamadas = {"raios": [], "geocode": 0}

    async def geocode_proibido(*a, **k):
        chamadas["geocode"] += 1
        raise AssertionError("não era para geocodificar o endereço da loja")

    async def prefixos(lat, lon, raio):
        chamadas["raios"].append((lat, lon, raio))
        return [_prefixo("11400", 2.0), _prefixo("11410", 25.0, cidade="Santos", cod=3548500)]

    monkeypatch.setattr(main, "geocode_async", geocode_proibido)
    monkeypatch.setattr(main.database, "consultar_prefixos_por_raio", prefixos)
    id_loja = cliente.post("/api/lojas", json=CORPO).json()["id"]
    return cliente, banco, id_loja, chamadas


def test_cobertura_usa_a_coordenada_da_loja_sem_geocodificar(cobertura_api):
    cliente, banco, id_loja, chamadas = cobertura_api
    r = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja, "raio_km": 40})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert chamadas["geocode"] == 0
    assert chamadas["raios"] == [(-23.993, -46.2564, 40.0)]  # coordenada cadastrada e raio escolhido
    assert corpo["raio_limite_km"] == 40.0 and corpo["total_pontos"] == 2
    hub = corpo["hub"]
    assert (hub["lat"], hub["lon"], hub["loja_id"], hub["nome"], hub["uf"]) == (-23.993, -46.2564, id_loja, "Atacadão Guarujá", "SP")
    assert (hub["cidade"], hub["ibge"]) == ("Guarujá", 3518701)  # do prefixo de CEP mais próximo (a menos de 10 km)
    assert hub["endereco"] == "Atacadão Guarujá - Av. Santos Dumont, 100"


def test_cobertura_da_loja_sem_prefixo_por_perto_deixa_cidade_e_ibge_vazios(cobertura_api, monkeypatch):
    cliente, banco, id_loja, chamadas = cobertura_api

    async def longe(lat, lon, raio):
        return [_prefixo("11410", 25.0, cidade="Santos", cod=3548500)]

    monkeypatch.setattr(main.database, "consultar_prefixos_por_raio", longe)
    hub = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja}).json()["hub"]
    assert hub["cidade"] == "" and hub["ibge"] is None  # nunca inventa


def test_cobertura_raio_padrao_30_e_limites(cobertura_api):
    cliente, banco, id_loja, chamadas = cobertura_api
    cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja})
    assert chamadas["raios"][-1][2] == 30.0
    for valido in (1, 200):
        assert cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja, "raio_km": valido}).status_code == 200
    for invalido in (0, -5, 200.1, 500):
        r = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja, "raio_km": invalido})
        assert r.status_code == 422 and r.json()["detail"] == main.MSG_RAIO_INVALIDO


def test_cobertura_com_loja_desativada_ou_inexistente_da_422(cobertura_api):
    cliente, banco, id_loja, chamadas = cobertura_api
    cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "ativo": False})
    r = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja})
    assert r.status_code == 422 and r.json()["detail"] == lojas.MSG_INATIVA
    r = cliente.post("/api/cobertura-ceps", json={"loja_id": 9999})
    assert r.status_code == 422 and r.json()["detail"] == lojas.MSG_NAO_ENCONTRADA
    assert chamadas["raios"] == [] and chamadas["geocode"] == 0


def test_cobertura_sem_loja_e_sem_endereco_pede_a_escolha(api):
    cliente, banco = api
    r = cliente.post("/api/cobertura-ceps", json={})
    assert r.status_code == 422 and "Escolha uma loja" in r.json()["detail"]


def test_outro_endereco_continua_geocodificando_como_antes(api, monkeypatch):
    cliente, banco = api

    async def geocode_falso(client, *a, **k):
        return -15.8198, -47.9012, "Brasília", "DF", "70347000", "Asa Sul", "VALIDO"

    async def prefixos(lat, lon, raio):
        return []

    async def ibge(uf, cidade):
        return 5300108

    monkeypatch.setattr(main, "geocode_async", geocode_falso)
    monkeypatch.setattr(main.database, "consultar_prefixos_por_raio", prefixos)
    monkeypatch.setattr(main.database, "buscar_ibge_municipio", ibge)
    r = cliente.post("/api/cobertura-ceps", json={"origem_rua": "SQS 108", "origem_num": "1", "origem_cep": "70347000"})
    assert r.status_code == 200 and r.json()["hub"]["cidade"] == "Brasília" and "loja_id" not in r.json()["hub"]


def test_otimizar_com_loja_valida_loja_ativa_e_motoristas(api, monkeypatch):
    cliente, banco = api
    id_loja = cliente.post("/api/lojas", json=CORPO).json()["id"]
    motorista = banco.inserir_motorista("Ana", "Carro de passeio")
    capturado = {}

    async def falso(job_id, req, frota_usar, valores_informados=None, loja=None, contexto=None):
        capturado["loja"] = loja

    monkeypatch.setattr(main, "_processar_otimizacao", falso)
    corpo = {"loja_id": id_loja, "turno": "manha", "pedidos": [{"id": 1}], "motorista_ids": [motorista]}
    assert cliente.post("/api/otimizar", json=corpo).status_code == 200
    assert capturado["loja"]["nome"] == "Atacadão Guarujá" and capturado["loja"]["lat"] == -23.993
    cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "ativo": False})
    r = cliente.post("/api/otimizar", json=corpo)
    assert r.status_code == 422 and r.json()["detail"] == lojas.MSG_INATIVA
    r = cliente.post("/api/otimizar", json={"turno": "manha", "pedidos": [{"id": 1}], "motorista_ids": [motorista]})
    assert r.status_code == 422 and "Escolha uma loja" in r.json()["detail"]


def test_roteirizacao_com_loja_usa_a_coordenada_dela_e_grava_o_nome_como_loja_hub(monkeypatch):
    pedidos = [{"id": i, "Endereco": f"Rua {i}", "Numero": str(i), "Bairro": "Centro", "CEP": "11400000", "Volume": 1} for i in range(1, 5)]
    geocodificados = []

    async def geocode_proibido(client, *a, **k):
        geocodificados.append(a)
        raise AssertionError("o hub não pode ser geocodificado quando há loja cadastrada")

    async def lote_falso(lista):
        return {main._chave_cache(p["Endereco"], numero=p["Numero"], bairro=p["Bairro"], cep=p["CEP"], cidade="", uf=""):
                (-23.99 - i * 0.001, -46.25, "Guarujá", "SP", "11400000", "Centro", "VALIDO") for i, p in enumerate(lista)}

    async def osrm_falso(client, pontos):
        return 5.0, 20, []

    monkeypatch.setattr(main, "geocode_async", geocode_proibido)
    monkeypatch.setattr(main, "geocodificar_lote", lote_falso)
    monkeypatch.setattr(main, "get_osrm_route_async", osrm_falso)
    loja = {"id": 7, "nome": "Atacadão Guarujá", "endereco": "Av. Santos Dumont, 100", "lat": -23.993, "lng": -46.2564}
    req = main.OtimizarRequest(loja_id=7, pedidos=pedidos)
    frota_usar = [main.MotoristaItem(id=1, motorista="João", modal="Carro de passeio", custo_rota=130.0)]
    main.JOBS["loja-hub"] = {"status": "em_andamento", "etapa": "", "atual": 0, "total": 1, "resultado": None, "erro": None}
    _rodar(main._processar_otimizacao("loja-hub", req, frota_usar, {}, loja))
    job = main.JOBS.pop("loja-hub")
    assert job["status"] == "concluido", job["erro"]
    resultado = job["resultado"]
    assert geocodificados == []
    assert resultado["loja_hub"] == "Atacadão Guarujá"
    assert (resultado["origem"]["lat"], resultado["origem"]["lon"], resultado["origem"]["rua"], resultado["origem"]["loja_id"]) == (-23.993, -46.2564, "Atacadão Guarujá", 7)


# ----------------------------------------------------------------------------------------------------------
# Cidade, cabeçalhos reconhecidos por nome e hover sem o país (ajuste de 16/10/2026)
# ----------------------------------------------------------------------------------------------------------
CSV_REAL = (
    "Nome,UF,Endereço Completo,Cidade,Latitude,Longitude\n"
    '"Atacadão Guarujá",SP,"Av. Santos Dumont, 100, Guarujá, SP, Brazil",Guarujá,"-23,9930","-46,2564"\n'
    "Atacadão Campinas,SP,,campinas,-22.9099,-47.0626\n"
    "Atacadão Sem Cidade,RJ,Rua A,,-22.9,-43.2\n"
)


def test_csv_real_nome_uf_endereco_completo_cidade_latitude_longitude(tmp_path):
    r = lojas.ler_csv_lojas(_csv(tmp_path, CSV_REAL))
    assert r.formato == "colunas" and r.delimitador == ","
    assert r.colunas == {"nome": "Nome", "estado": "UF", "endereco": "Endereço Completo", "cidade": "Cidade", "latitude": "Latitude", "longitude": "Longitude"}
    guaruja, campinas, sem_cidade = r.linhas
    assert (guaruja.nome, guaruja.uf, guaruja.cidade, guaruja.lat, guaruja.lng, guaruja.status) == ("Atacadão Guarujá", "SP", "Guarujá", -23.993, -46.2564, "valida")
    assert guaruja.endereco == "Av. Santos Dumont, 100, Guarujá, SP, Brazil"  # o dado guardado não perde o país
    assert (campinas.cidade, campinas.sem_endereco, campinas.sem_cidade, campinas.lat) == ("campinas", True, False, -22.9099)  # ponto decimal também vale
    assert (sem_cidade.cidade, sem_cidade.sem_cidade, sem_cidade.sem_endereco, sem_cidade.status) == (None, True, False, "valida")
    resumo = lojas.resumir(r)
    assert (resumo["validas"], resumo["sem_cidade"], resumo["sem_endereco"]) == (3, 1, 1)


@pytest.mark.parametrize("cabecalho", [
    "Nome;UF;Endereço Completo;Cidade;Latitude;Longitude",
    "NOME;uf;ENDERECO COMPLETO;CIDADE;LAT;LNG",
    "nome;estado;endereco;cidade;latitude;lon",
    "Nome;Estado;EnderecoCompleto;Cidade;Lat;Longitude",
    "Nome ;UF ;Endereço  Completo ;Cidade ;LATITUDE ;LONGITUDE ",
    "Nome;UF;endereco_completo;Município;Latitude;Long",
])
def test_cabecalhos_com_variacoes_de_maiusculas_acentos_espacos_e_apelidos(tmp_path, cabecalho):
    r = lojas.ler_csv_lojas(_csv(tmp_path, cabecalho + "\nAtacadão Teste;sp;Rua X, 1;Santos;-23,96;-46,33\n"))
    linha = r.linhas[0]
    assert (linha.nome, linha.uf, linha.endereco, linha.cidade, linha.lat, linha.lng, linha.status) == ("Atacadão Teste", "SP", "Rua X, 1", "Santos", -23.96, -46.33, "valida")
    assert set(r.colunas) == {"nome", "estado", "endereco", "cidade", "latitude", "longitude"}


def test_a_ordem_das_colunas_nao_importa(tmp_path):
    texto = "Longitude;Latitude;Cidade;Endereço;UF;Nome\n-46,33;-23,96;Santos;Rua X, 1;SP;Atacadão Teste\n"
    linha = lojas.ler_csv_lojas(_csv(tmp_path, texto)).linhas[0]
    assert (linha.nome, linha.uf, linha.endereco, linha.cidade, linha.lat, linha.lng) == ("Atacadão Teste", "SP", "Rua X, 1", "Santos", -23.96, -46.33)


def test_csv_sem_a_coluna_cidade_continua_funcionando_e_avisa_nas_contagens(tmp_path):
    texto = "Nome;UF;Endereço;Latitude;Longitude\nLoja A;SP;Rua 1;-23,5;-46,6\n"
    r = lojas.ler_csv_lojas(_csv(tmp_path, texto))
    assert "cidade" not in r.colunas and r.linhas[0].status == "valida" and r.linhas[0].sem_cidade is True
    assert lojas.resumir(r)["sem_cidade"] == 1


def test_my_maps_com_coluna_cidade_tambem_e_lida(tmp_path):
    texto = 'WKT,name,description,Cidade\n"POINT (-46.2564 -23.9930)",Atacadão Guarujá,"Av. Santos Dumont, 100",Guarujá\n'
    r = lojas.ler_csv_lojas(_csv(tmp_path, texto))
    assert r.formato == "my_maps" and r.linhas[0].cidade == "Guarujá" and r.colunas["cidade"] == "Cidade"


@pytest.mark.parametrize("endereco, esperado", [
    ("Av. Santos Dumont, 100, Guarujá, SP, Brazil", "Av. Santos Dumont, 100, Guarujá, SP"),
    ("Av. Santos Dumont, 100, Guarujá - SP, Brasil", "Av. Santos Dumont, 100, Guarujá - SP"), ("Rua A, 5 - Brasil", "Rua A, 5 - Brasil"),
    ("Rua A, 5, BRAZIL", "Rua A, 5"), ("Rua A, 5 ,brasil.", "Rua A, 5"), ("Rua A, 5, Brazil ", "Rua A, 5"),
    ("Rua A, 5", "Rua A, 5"), ("Rua Brasil, 5", "Rua Brasil, 5"), ("Avenida do Brasil", "Avenida do Brasil"),
    ("Brazil", ""), ("", ""), (None, ""),
])
def test_hover_mostra_o_endereco_sem_o_pais_no_final(endereco, esperado):
    assert lojas.endereco_para_exibir(endereco) == esperado


def test_hover_usa_o_endereco_sem_o_pais_e_nao_altera_o_dado_guardado():
    loja = _loja(endereco="Av. Santos Dumont, 100, Guarujá, SP, Brazil")
    assert lojas.texto_do_hover(loja) == ["Atacadão Guarujá", "Av. Santos Dumont, 100, Guarujá, SP", "SP"]
    assert loja["endereco"].endswith("Brazil")
    assert lojas.texto_do_hover(_loja(endereco="Brazil")) == ["Atacadão Guarujá", "SP"]  # só o país: não sobra linha vazia


def test_cidade_e_opcional_normalizada_e_limitada(banco):
    loja = _rodar(lojas.criar(banco, _loja(cidade="  Praia   Grande "), OPERADOR))
    assert loja["cidade"] == "Praia Grande"
    assert _rodar(lojas.criar(banco, _loja(nome="Outra", cidade=""), OPERADOR))["cidade"] is None
    assert _rodar(lojas.criar(banco, _loja(nome="Outra 2"), OPERADOR))["cidade"] is None
    with pytest.raises(ValueError) as erro:
        lojas.validar_loja(_loja(cidade="x" * 200))
    assert "cidade" in str(erro.value)
    editada = _rodar(lojas.atualizar(banco, loja["id"], _loja(cidade="Santos"), OPERADOR))
    assert editada["cidade"] == "Santos"


def _com_municipios(banco):
    for comando in ibge.SCHEMA_IBGE_MUNICIPIOS:
        banco.db.execute(comando)
    for codigo, nome, uf in ((3518701, "Guarujá", "SP"), (3550308, "São Paulo", "SP"), (3509502, "Campinas", "SP"), (3304557, "Rio de Janeiro", "RJ")):
        banco.db.execute("INSERT INTO ibge_municipios (codigo, nome, uf, nome_normalizado) VALUES (?, ?, ?, ?)", (codigo, nome, uf, ibge.normalizar_nome(nome)))


def _loja_via_api(cliente, **extra):
    r = cliente.post("/api/lojas", json={**CORPO, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.parametrize("cidade", ["Guarujá", "Guaruja", "GUARUJÁ", "guarujá", "  guaruja  "])
def test_ibge_do_hub_vem_da_cidade_e_uf_com_ou_sem_acento_e_maiusculas(cobertura_api, cidade):
    cliente, banco, id_loja, chamadas = cobertura_api
    _com_municipios(banco)
    cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "cidade": cidade})
    r = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja})
    hub = r.json()["hub"]
    assert (hub["ibge"], hub["aviso_ibge"], r.json()["aviso_ibge"]) == (3518701, None, None)
    assert hub["cidade"] == " ".join(cidade.split())


def test_ibge_do_hub_pela_cidade_ganha_do_prefixo_de_cep_mais_proximo(cobertura_api, monkeypatch):
    cliente, banco, id_loja, chamadas = cobertura_api
    _com_municipios(banco)
    cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "cidade": "São Paulo"})  # o prefixo mais próximo é de Guarujá
    hub = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja}).json()["hub"]
    assert hub["ibge"] == 3550308 and hub["cidade"] == "São Paulo" and hub["aviso_ibge"] is None


def test_cidade_nao_encontrada_usa_o_cep_mais_proximo_e_avisa(cobertura_api):
    cliente, banco, id_loja, chamadas = cobertura_api
    _com_municipios(banco)
    cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "cidade": "Cidade Inexistente"})
    r = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja})
    hub = r.json()["hub"]
    assert hub["ibge"] == 3518701  # do prefixo de CEP mais próximo, como antes
    assert 'Não achei a cidade "Cidade Inexistente" (SP)' in hub["aviso_ibge"] and "CEP mais próximo" in hub["aviso_ibge"]
    assert r.json()["aviso_ibge"] == hub["aviso_ibge"]
    assert not re.search(r"sql|tabela|banco|api|json|ibge_municipios", hub["aviso_ibge"], re.IGNORECASE)


def test_cidade_com_o_mesmo_nome_em_outro_estado_nao_e_confundida(cobertura_api):
    cliente, banco, id_loja, chamadas = cobertura_api
    _com_municipios(banco)
    cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "cidade": "Rio de Janeiro"})  # a loja é de SP: a cidade é do RJ
    hub = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja}).json()["hub"]
    assert hub["ibge"] == 3518701 and "Não achei a cidade" in hub["aviso_ibge"]


def test_loja_sem_cidade_usa_o_cep_mais_proximo_e_avisa(cobertura_api):
    cliente, banco, id_loja, chamadas = cobertura_api
    r = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja})
    hub = r.json()["hub"]
    assert (hub["ibge"], hub["cidade"]) == (3518701, "Guarujá")
    assert hub["aviso_ibge"].startswith("A loja está sem cidade cadastrada.") and "CEP mais próximo" in hub["aviso_ibge"]


def test_loja_sem_cidade_e_sem_cep_por_perto_deixa_o_ibge_vazio_e_avisa(cobertura_api, monkeypatch):
    cliente, banco, id_loja, chamadas = cobertura_api

    async def longe(lat, lon, raio):
        return [_prefixo("11410", 25.0, cidade="Santos", cod=3548500)]

    monkeypatch.setattr(main.database, "consultar_prefixos_por_raio", longe)
    hub = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja}).json()["hub"]
    assert hub["ibge"] is None and hub["cidade"] == "" and "em branco" in hub["aviso_ibge"]


def test_cidade_sem_estado_nao_da_para_buscar_no_ibge_e_avisa(cobertura_api):
    cliente, banco, id_loja, chamadas = cobertura_api
    _com_municipios(banco)
    cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "uf": None, "cidade": "Guarujá"})
    hub = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja}).json()["hub"]
    assert hub["ibge"] == 3518701 and "sem Estado" in hub["aviso_ibge"] and hub["cidade"] == "Guarujá"


def test_exportacao_usa_o_ibge_do_hub_vindo_da_cidade(cobertura_api):
    import io
    import openpyxl
    cliente, banco, id_loja, chamadas = cobertura_api
    _com_municipios(banco)
    cliente.put(f"/api/lojas/{id_loja}", json={**CORPO, "cidade": "São Paulo"})
    cobertura_resp = cliente.post("/api/cobertura-ceps", json={"loja_id": id_loja}).json()
    sem_codigo_proprio = [{**p, "ibge": None} for p in cobertura_resp["pontos_cobertos"]]  # o código do hub vale onde o ponto não tem o seu
    r = cliente.post("/api/exportar-tabela-frete-xlsx", json={"hub": cobertura_resp["hub"], "pontos_cobertos": sem_codigo_proprio})
    assert r.status_code == 200
    planilha = openpyxl.load_workbook(io.BytesIO(r.content))
    textos = " ".join(str(c.value) for aba in planilha for linha in aba.iter_rows() for c in linha if c.value is not None)
    assert "3550308" in textos
