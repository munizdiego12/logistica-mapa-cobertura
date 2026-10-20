"""Etapa 6c: lojas a partir da exportação do Superset (leitura, agrupamento, proximidade, plano, gravação), código externo e
nome de operação (unicidade), migration 0009 e casamento dos motoristas por nome de operação."""
import asyncio
import csv
import importlib.util
import re
import sqlite3
from pathlib import Path

import pytest

import lojas
from backend import carga_motoristas as carga
from backend import carga_superset as superset
from backend.tests.fakes_asyncpg import criar_banco_sqlite

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("carregar_lojas_superset_teste", RAIZ / "scripts" / "carregar_lojas.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

CABECALHO = [
    "zoul_brand_id", "zoul_brand_internal_id", "zoul_brand_name", "store_id", "store_name", "store_number", "store_city",
    "store_state", "store_is_active", "store_address", "store_point", "retailer_name", "store_internal_id", "map_store_location",
]
OPERADOR_TELA = "Maria Souza (maria@zubale.com)"


def _linha(store_id, nome, ponto, cidade="Guarujá", estado="Sao Paulo", ativo="TRUE", endereco="Av. Santos Dumont, 100, Brazil", rede="Atacadão"):
    return ["1", "b1", "Marca", store_id, nome, "10", cidade, estado, ativo, endereco, ponto, rede, "99", "<a href='x'>mapa</a>"]


def _escrever(caminho, linhas, delimitador=","):
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f, delimiter=delimitador, quoting=csv.QUOTE_MINIMAL)
        escritor.writerow(CABECALHO)
        escritor.writerows(linhas)
    return str(caminho)


LINHAS = [
    _linha("S-1", "SDA Guarujá Op", "-23,9931;-46,2564"),                     # ~11 m da loja cadastrada "Atacadão Guarujá"
    _linha("S-1", "SDA Guarujá Op", "-23,9931;-46,2564", rede="Atacadão"),    # repetida (outra operação)
    _linha("S-2", "SDA Santos", "-23,9602;-46,3300", cidade="Santos"),        # entre duas lojas cadastradas: ambígua
    _linha("S-3", "SDA Mooca", "-23.5600;-46.6000", cidade="São Paulo", endereco="Rua da Mooca, 1"),  # nova
    _linha("S-4", "SDA Conflito", "-10,0;-50,0", cidade="Palmas", estado="Tocantins"),  # nome igual ao de uma loja distante
    _linha("S-5", "SDA Fechada", "-23,0;-46,0", ativo="FALSE"),               # inativa
    _linha("S-6", "SDA Sem Ponto", ""),                                       # sem store_point
    _linha("S-7", "SDA Ponto Ruim", "abc;def"),                               # store_point ilegível
    _linha("S-8", "SDA Atlantida", "-12,0;-48,0", estado="Atlantida"),        # estado não reconhecido (a loja entra sem UF)
    _linha("S-9", "SDA Nove", "-22,0;-47,0", cidade="Campinas", estado="SP"),  # código externo já cadastrado
    _linha("", "SDA Sem Id", "-12,5;-48,5"),                                  # sem store_id
    _linha("S-10", "SDA Fora", "40,0;10,0"),                                  # fora do Brasil
]


@pytest.fixture
def arquivo(tmp_path):
    return _escrever(tmp_path / "superset.csv", LINHAS)


def _cadastro(banco):
    ins = "INSERT INTO lojas (nome, uf, lat, lng, atualizado_por{extra}) VALUES (?, ?, ?, ?, ?{marc})"
    banco.db.execute(ins.format(extra="", marc=""), ("Atacadão Guarujá", "SP", -23.9930, -46.2564, OPERADOR_TELA))
    banco.db.execute(ins.format(extra="", marc=""), ("Atacadão Santos A", "SP", -23.9600, -46.3300, "carga inicial (script)"))
    banco.db.execute(ins.format(extra="", marc=""), ("Atacadão Santos B", "SP", -23.9605, -46.3300, "carga inicial (script)"))
    banco.db.execute(ins.format(extra="", marc=""), ("SDA Conflito", "RJ", -20.0, -45.0, "carga inicial (script)"))
    banco.db.execute(
        "INSERT INTO lojas (nome, lat, lng, codigo_externo, atualizado_por) VALUES (?, ?, ?, ?, ?)",
        ("Loja do Código", -22.5, -47.5, "s-9", OPERADOR_TELA),  # o código vale sem diferença de maiúsculas
    )


@pytest.fixture
def banco_falso(monkeypatch):
    banco = criar_banco_sqlite()
    _cadastro(banco)
    conexoes = []

    async def conectar(dsn):
        conexoes.append(dsn)
        return banco

    monkeypatch.setattr(script, "conectar", conectar)
    monkeypatch.setenv("DATABASE_URL", "postgres://usuario:segredo@host.neon.tech/db?sslmode=require&channel_binding=require")
    banco.conexoes = conexoes
    return banco


def _linha_banco(banco, nome):
    r = banco.db.execute("SELECT * FROM lojas WHERE nome = ?", (nome,)).fetchone()
    return None if r is None else dict(r)


# ----------------------------------------------------------------------------------------------------------
# Leitura
# ----------------------------------------------------------------------------------------------------------
def test_reconhece_a_exportacao_pelo_cabecalho_e_ignora_o_html(arquivo, tmp_path):
    assert superset.e_exportacao_superset(arquivo)
    outro = tmp_path / "comum.csv"
    outro.write_text("Nome;Estado;Endereço;Latitude;Longitude\nA;SP;;-23,5;-46,6\n", encoding="utf-8")
    assert not superset.e_exportacao_superset(outro)
    r = superset.ler_superset(arquivo)
    assert r.colunas["store_point"] == "store_point" and "map_store_location" not in r.colunas


def test_linhas_repetidas_sao_agrupadas_por_store_id_e_inativas_ignoradas(arquivo):
    r = superset.ler_superset(arquivo)
    assert r.linhas_lidas == 12
    assert r.linhas_inativas == 1 and r.inativas == 1
    assert r.repetidas == 1
    por_id = {l.codigo_externo: l for l in r.lojas}
    assert por_id["S-1"].linhas == [2, 3]
    assert "S-5" not in por_id
    resumo = superset.resumir(r)
    assert resumo["lojas_ativas"] == 9 and resumo["com_coordenada"] == 6  # S-1, 2, 3, 4, 8 e 9 (S-6, S-7 e S-10 sem coordenada válida)
    assert resumo["redes"] == {"Atacadão": 9}  # a rede conta as 9 lojas ativas, com ou sem coordenada


def test_estado_por_extenso_vira_uf_e_a_sigla_tambem_vale(arquivo):
    por_id = {l.codigo_externo: l for l in superset.ler_superset(arquivo).lojas}
    assert por_id["S-3"].uf == "SP" and por_id["S-4"].uf == "TO" and por_id["S-9"].uf == "SP"
    assert por_id["S-3"].cidade == "São Paulo" and por_id["S-3"].endereco == "Rua da Mooca, 1"


def test_estado_nao_reconhecido_e_contado_e_a_loja_fica_sem_uf(arquivo):
    r = superset.ler_superset(arquivo)
    assert r.estados_nao_reconhecidos == {"Atlantida": 1}
    assert {l.codigo_externo: l for l in r.lojas}["S-8"].uf is None


def test_store_point_em_uma_celula_com_virgula_ou_ponto_decimal(arquivo):
    por_id = {l.codigo_externo: l for l in superset.ler_superset(arquivo).lojas}
    assert (por_id["S-1"].lat, por_id["S-1"].lng) == (-23.9931, -46.2564)
    assert (por_id["S-3"].lat, por_id["S-3"].lng) == (-23.56, -46.6)


def test_sem_store_point_ou_invalido_ou_fora_do_brasil_e_listado(arquivo):
    r = superset.ler_superset(arquivo)
    assert {c: motivo for c, _, _, motivo in r.sem_coordenada} == {
        "S-6": "sem store_point", "S-7": "store_point com número ilegível", "S-10": "store_point fora do Brasil",
    }
    assert r.linhas_invalidas == [(12, "sem store_id")]
    assert {l.codigo_externo for l in r.lojas}.isdisjoint({"S-6", "S-7", "S-10"})


def test_latitude_e_longitude_trocadas_no_store_point_sao_recusadas(tmp_path):
    caminho = _escrever(tmp_path / "t.csv", [_linha("T-1", "SDA Troca", "-46,6;-23,5")])
    r = superset.ler_superset(caminho)
    assert r.lojas == [] and r.sem_coordenada[0][3] == "store_point com latitude e longitude trocadas"


def test_ponto_e_virgula_como_separador_e_windows_1252(tmp_path):
    caminho = tmp_path / "pv.csv"
    with open(caminho, "w", encoding="cp1252", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(CABECALHO)
        w.writerow(_linha("P-1", "SDA Atacadão", '-23,5;-46,6', cidade="São Paulo"))
    r = superset.ler_superset(str(caminho))
    assert r.delimitador == ";" and r.codificacao == "windows-1252"
    assert r.lojas[0].nome_operacao == "SDA Atacadão" and r.lojas[0].cidade == "São Paulo"  # store_point entre aspas, com ';' dentro


def test_linhas_do_mesmo_store_id_com_dados_diferentes_usam_o_primeiro_valor_e_avisam(tmp_path):
    caminho = _escrever(tmp_path / "d.csv", [
        _linha("D-1", "SDA Um", "-23,5;-46,6"),
        _linha("D-1", "SDA Dois", "-22,0;-47,0"),
    ])
    r = superset.ler_superset(caminho)
    loja = r.lojas[0]
    assert loja.nome_operacao == "SDA Um" and (loja.lat, loja.lng) == (-23.5, -46.6)
    assert len(r.conflitos) == 2 and {c[2].split(" ")[0] for c in r.conflitos} == {"nomes", "coordenadas"}


def test_store_is_active_ilegivel_e_linha_invalida(tmp_path):
    r = superset.ler_superset(_escrever(tmp_path / "a.csv", [_linha("A-1", "SDA A", "-23,5;-46,6", ativo="talvez")]))
    assert r.lojas == [] and "store_is_active não reconhecido" in r.linhas_invalidas[0][1]


# ----------------------------------------------------------------------------------------------------------
# Plano
# ----------------------------------------------------------------------------------------------------------
async def _plano(banco, arquivo):
    return superset.planejar(await superset.ler_cadastradas(banco), superset.ler_superset(arquivo).lojas)


def test_plano_classifica_ligada_ambigua_nova_conflito_e_codigo(arquivo):
    banco = criar_banco_sqlite()
    _cadastro(banco)
    plano = asyncio.run(_plano(banco, arquivo))
    assert [a.loja.codigo_externo for a in plano.ja_cadastradas] == ["S-9"]
    assert [a.loja.codigo_externo for a in plano.por_proximidade] == ["S-1"]
    assert [a.loja.codigo_externo for a in plano.ambiguas] == ["S-2"]
    assert [a.loja.codigo_externo for a in plano.nome_em_conflito] == ["S-4"]
    assert sorted(a.loja.codigo_externo for a in plano.novas) == ["S-3", "S-8"]
    ligada = plano.por_proximidade[0]
    assert ligada.destino["nome"] == "Atacadão Guarujá" and 0 < ligada.distancia_m < 20
    assert ligada.preencher == {"codigo_externo": "S-1", "nome_operacao": "SDA Guarujá Op", "nome_operacao_chave": "sdaguarujaop"}
    assert {n for n, _ in plano.ambiguas[0].candidatas} == {"Atacadão Santos A", "Atacadão Santos B"}


def test_resumo_com_o_plano(arquivo):
    banco = criar_banco_sqlite()
    _cadastro(banco)
    resultado = superset.ler_superset(arquivo)
    plano = superset.planejar(asyncio.run(superset.ler_cadastradas(banco)), resultado.lojas)
    resumo = superset.resumir(resultado, plano)
    assert (resumo["ja_cadastradas"], resumo["por_proximidade"], resumo["novas"], resumo["ambiguas"], resumo["nome_em_conflito"]) == (1, 1, 2, 1, 1)
    assert resumo["lojas_inativas"] == 1 and resumo["repetidas"] == 1 and len(resumo["sem_coordenada"]) == 3


def test_limite_de_150_metros():
    cad = [{"id": 1, "nome": "Loja A", "uf": "SP", "endereco": None, "cidade": None, "lat": -23.0, "lng": -46.0, "codigo_externo": None, "nome_operacao": None}]
    perto = superset.LojaSuperset("X-1", "Op Perto", lat=-23.0 + 0.00134, lng=-46.0)   # ~149 m
    longe = superset.LojaSuperset("X-2", "Op Longe", lat=-23.0 + 0.00136, lng=-46.0)   # ~151 m
    plano = superset.planejar(cad, [perto, longe])
    assert [a.loja.codigo_externo for a in plano.por_proximidade] == ["X-1"]
    assert [a.loja.codigo_externo for a in plano.novas] == ["X-2"]


def test_duas_lojas_do_arquivo_para_a_mesma_cadastrada_sao_ambiguas():
    cad = [{"id": 1, "nome": "Loja A", "uf": "SP", "endereco": None, "cidade": None, "lat": -23.0, "lng": -46.0, "codigo_externo": None, "nome_operacao": None}]
    a = superset.LojaSuperset("X-1", "Op A", lat=-23.0001, lng=-46.0)
    b = superset.LojaSuperset("X-2", "Op B", lat=-23.0002, lng=-46.0)
    plano = superset.planejar(cad, [a, b])
    assert len(plano.ambiguas) == 2 and not plano.por_proximidade and not plano.novas


def test_loja_proxima_que_ja_tem_outro_codigo_e_ambigua_e_nao_vira_duplicada():
    cad = [{"id": 1, "nome": "Loja A", "uf": "SP", "endereco": None, "cidade": None, "lat": -23.0, "lng": -46.0, "codigo_externo": "Z-9", "nome_operacao": None}]
    plano = superset.planejar(cad, [superset.LojaSuperset("X-1", "Op A", lat=-23.0001, lng=-46.0)])
    assert len(plano.ambiguas) == 1 and "já tem outro código externo" in plano.ambiguas[0].motivo and not plano.novas


def test_nome_de_operacao_ja_de_outra_loja_nao_impede_a_ligacao_mas_fica_de_fora():
    cad = [
        {"id": 1, "nome": "Loja A", "uf": "SP", "endereco": None, "cidade": None, "lat": -23.0, "lng": -46.0, "codigo_externo": None, "nome_operacao": None},
        {"id": 2, "nome": "Loja B", "uf": "SP", "endereco": None, "cidade": None, "lat": -10.0, "lng": -50.0, "codigo_externo": "B", "nome_operacao": "SDA  Mooca"},
    ]
    plano = superset.planejar(cad, [superset.LojaSuperset("X-1", "sda mooca", lat=-23.0001, lng=-46.0)])
    assert len(plano.por_proximidade) == 1 and len(plano.operacao_em_conflito) == 1
    assert plano.por_proximidade[0].preencher == {"codigo_externo": "X-1"}


def test_novas_do_mesmo_arquivo_com_o_mesmo_nome_so_a_primeira_entra():
    a = superset.LojaSuperset("X-1", "SDA Igual", lat=-23.0, lng=-46.0)
    b = superset.LojaSuperset("X-2", "sda  igual", lat=-20.0, lng=-44.0)
    plano = superset.planejar([], [a, b])
    assert [x.loja.codigo_externo for x in plano.novas] == ["X-1"] and len(plano.nome_em_conflito) == 1


# ----------------------------------------------------------------------------------------------------------
# Script
# ----------------------------------------------------------------------------------------------------------
def test_sem_gravar_e_sem_database_url_mostra_o_arquivo_e_nao_conecta(arquivo, monkeypatch, capsys):
    async def proibido(dsn):
        raise AssertionError("não era para conectar no banco")

    monkeypatch.setattr(script, "conectar", proibido)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    script.main(["--csv", arquivo])
    texto = capsys.readouterr().out
    assert "exportação do Superset" in texto and "LOJAS NO ARQUIVO: 9 ativas, 1 inativas" in texto
    assert "linhas repetidas agrupadas por store_id: 1" in texto
    assert "SEM COORDENADA OU INVÁLIDAS (não serão gravadas): 3" in texto
    assert "store_id S-6" in texto and "ESTADOS NÃO RECONHECIDOS (a loja entra sem UF): 1" in texto and '"Atlantida"' in texto
    assert "O cadastro NÃO foi consultado" in texto and "Nada foi gravado" in texto


def test_com_banco_o_resumo_traz_o_plano_sem_gravar(arquivo, banco_falso, capsys):
    script.main(["--csv", arquivo])
    texto = capsys.readouterr().out
    assert '"SDA Guarujá Op" (arquivo) = "Atacadão Guarujá" (cadastrada), a ' in texto
    assert "ligadas pelo código externo (só completa o que está vazio): 1" in texto
    assert "NOVAS (serão criadas): 2" in texto and "AMBÍGUAS (NÃO aplicadas): 1" in texto
    assert '"SDA Santos" (store_id S-2)' in texto and '"Atacadão Santos A" a ' in texto
    assert "NOME EM CONFLITO (NÃO gravadas): 1" in texto and "SDA Conflito" in texto
    assert "segredo" not in texto
    assert banco_falso.db.execute("SELECT count(*) FROM lojas").fetchone()[0] == 5  # nada gravado


def test_so_grava_com_a_confirmacao_digitada(arquivo, banco_falso, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "gravar")  # minúsculas não valem
    script.main(["--csv", arquivo, "--gravar"])
    assert "Cancelado: nada foi gravado." in capsys.readouterr().out
    assert banco_falso.db.execute("SELECT count(*) FROM lojas").fetchone()[0] == 5


def test_gravacao_liga_sem_mudar_o_nome_cria_as_novas_e_nao_grava_conflito_nem_ambigua(arquivo, banco_falso, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "GRAVAR")
    script.main(["--csv", arquivo, "--gravar"])
    assert "Gravado: 2 loja(s) nova(s), 1 ligada(s) por proximidade, 1 completada(s)." in capsys.readouterr().out

    guaruja = _linha_banco(banco_falso, "Atacadão Guarujá")  # ligada: nome, endereço e coordenadas intactos
    assert (guaruja["codigo_externo"], guaruja["nome_operacao"]) == ("S-1", "SDA Guarujá Op")
    assert (guaruja["lat"], guaruja["lng"], guaruja["endereco"], guaruja["uf"]) == (-23.9930, -46.2564, None, "SP")
    assert guaruja["atualizado_por"] == OPERADOR_TELA  # a edição do operador mantém o registro dele
    assert _linha_banco(banco_falso, "SDA Guarujá Op") is None  # não criou duplicada

    nova = _linha_banco(banco_falso, "SDA Mooca")
    assert (nova["uf"], nova["cidade"], nova["codigo_externo"], nova["nome_operacao"]) == ("SP", "São Paulo", "S-3", "SDA Mooca")
    assert nova["endereco"] == "Rua da Mooca, 1" and nova["atualizado_por"] == "carga inicial (script)"
    assert _linha_banco(banco_falso, "SDA Atlantida")["uf"] is None

    codigo = _linha_banco(banco_falso, "Loja do Código")  # a): completa o vazio
    assert (codigo["uf"], codigo["cidade"], codigo["nome_operacao"], codigo["lat"]) == ("SP", "Campinas", "SDA Nove", -22.5)
    assert codigo["atualizado_por"] == OPERADOR_TELA

    assert _linha_banco(banco_falso, "SDA Santos") is None  # ambígua
    assert _linha_banco(banco_falso, "Atacadão Santos A")["codigo_externo"] is None
    assert _linha_banco(banco_falso, "SDA Conflito")["codigo_externo"] is None and _linha_banco(banco_falso, "SDA Conflito")["uf"] == "RJ"
    assert banco_falso.db.execute("SELECT count(*) FROM lojas").fetchone()[0] == 7


def test_repetir_a_carga_e_seguro(arquivo, banco_falso, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "GRAVAR")
    script.main(["--csv", arquivo, "--gravar"])
    script.main(["--csv", arquivo, "--gravar"])
    # Na 2ª vez a loja ligada por proximidade já tem o código externo e entra na regra a): só completa o que está VAZIO
    # (cidade e endereço), nunca nome nem coordenadas. Nada novo é criado nem ligado.
    guaruja = _linha_banco(banco_falso, "Atacadão Guarujá")
    assert (guaruja["cidade"], guaruja["endereco"], guaruja["nome"], guaruja["lat"]) == ("Guarujá", "Av. Santos Dumont, 100, Brazil", "Atacadão Guarujá", -23.9930)
    antes = [tuple(r) for r in banco_falso.db.execute("SELECT * FROM lojas ORDER BY id")]
    capsys.readouterr()
    script.main(["--csv", arquivo, "--gravar"])
    assert [tuple(r) for r in banco_falso.db.execute("SELECT * FROM lojas ORDER BY id")] == antes  # a 3ª vez não muda nada
    assert "Gravado: 0 loja(s) nova(s), 0 ligada(s) por proximidade, 0 completada(s)." in capsys.readouterr().out


def test_loja_da_carga_ligada_recebe_atualizado_por_da_carga(banco_falso, tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "GRAVAR")
    caminho = _escrever(tmp_path / "um.csv", [_linha("K-1", "SDA Santos Norte", "-23,9600;-46,3301")])
    banco_falso.db.execute("DELETE FROM lojas WHERE nome = 'Atacadão Santos B'")  # agora só uma loja próxima (carga inicial)
    script.main(["--csv", caminho, "--gravar"])
    santos = _linha_banco(banco_falso, "Atacadão Santos A")
    assert santos["codigo_externo"] == "K-1" and santos["nome"] == "Atacadão Santos A" and santos["atualizado_por"] == "carga inicial (script)"


def test_o_formato_antigo_do_csv_continua_funcionando(tmp_path, monkeypatch, capsys):
    caminho = tmp_path / "antigo.csv"
    caminho.write_text("Nome;Estado;Endereço;Latitude;Longitude\nAtacadão X;SP;;-23,5;-46,6\n", encoding="utf-8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    script.main(["--csv", str(caminho)])
    texto = capsys.readouterr().out
    assert "LOJAS VÁLIDAS (serão gravadas): 1" in texto and "Superset" not in texto


# ----------------------------------------------------------------------------------------------------------
# Código externo e nome de operação no cadastro (unicidade)
# ----------------------------------------------------------------------------------------------------------
def _criar(banco, nome, **extra):
    base = {"nome": nome, "uf": "SP", "lat": -23.5, "lng": -46.6}
    base.update(extra)
    return asyncio.run(lojas.criar(banco, base, OPERADOR_TELA))


def test_criar_guarda_codigo_externo_e_nome_de_operacao_e_devolve_na_lista():
    banco = criar_banco_sqlite()
    loja = _criar(banco, "Atacadão Mooca", codigo_externo=" S-77 ", nome_operacao="SDA   Mooca")
    assert loja["codigo_externo"] == "S-77" and loja["nome_operacao"] == "SDA Mooca"
    assert "nome_operacao_chave" not in loja
    assert asyncio.run(lojas.listar(banco))[0]["nome_operacao"] == "SDA Mooca"
    assert _criar(banco, "Sem Nada")["codigo_externo"] is None


@pytest.mark.parametrize("repetido", ["SDA Mooca", "sda mooca", "  SDA   MOOCA ", "Sda Moóca", "sdamooca", "SDÁ Mooca"])
def test_nome_de_operacao_unico_sem_diferenca_de_maiusculas_acentos_nem_espacos(repetido):
    banco = criar_banco_sqlite()
    _criar(banco, "Loja Um", nome_operacao="SDA Mooca")
    with pytest.raises(ValueError, match="Já existe uma loja com esse nome de operação."):
        _criar(banco, "Loja Dois", nome_operacao=repetido)


@pytest.mark.parametrize("repetido", ["S-77", "s-77", " S-77 "])
def test_codigo_externo_unico(repetido):
    banco = criar_banco_sqlite()
    _criar(banco, "Loja Um", codigo_externo="S-77")
    with pytest.raises(ValueError, match="Já existe uma loja com esse código externo."):
        _criar(banco, "Loja Dois", codigo_externo=repetido)


def test_varias_lojas_sem_codigo_nem_operacao_sao_permitidas():
    banco = criar_banco_sqlite()
    _criar(banco, "A")
    _criar(banco, "B")
    _criar(banco, "C", nome_operacao="  ", codigo_externo="")
    assert len(asyncio.run(lojas.listar(banco))) == 3


def test_editar_a_propria_loja_nao_conta_como_repetida_e_o_conflito_e_avisado():
    banco = criar_banco_sqlite()
    a = _criar(banco, "Loja A", codigo_externo="A-1", nome_operacao="Op A")
    b = _criar(banco, "Loja B", codigo_externo="B-1", nome_operacao="Op B")
    ok = asyncio.run(lojas.atualizar(banco, a["id"], {**a, "nome_operacao": "OP a"}, OPERADOR_TELA))
    assert ok["nome_operacao"] == "OP a"
    with pytest.raises(ValueError, match="nome de operação"):
        asyncio.run(lojas.atualizar(banco, b["id"], {**b, "nome_operacao": "op  A"}, OPERADOR_TELA))
    with pytest.raises(ValueError, match="código externo"):
        asyncio.run(lojas.atualizar(banco, b["id"], {**b, "codigo_externo": "a-1"}, OPERADOR_TELA))


def test_editar_sem_enviar_os_dois_campos_mantem_o_valor_e_enviar_em_branco_limpa():
    banco = criar_banco_sqlite()
    a = _criar(banco, "Loja A", codigo_externo="A-1", nome_operacao="Op A")
    sem = {c: v for c, v in a.items() if c not in ("codigo_externo", "nome_operacao")}
    mantida = asyncio.run(lojas.atualizar(banco, a["id"], {**sem, "uf": "RJ"}, OPERADOR_TELA))
    assert (mantida["codigo_externo"], mantida["nome_operacao"], mantida["uf"]) == ("A-1", "Op A", "RJ")
    limpa = asyncio.run(lojas.atualizar(banco, a["id"], {**sem, "codigo_externo": "", "nome_operacao": None}, OPERADOR_TELA))
    assert limpa["codigo_externo"] is None and limpa["nome_operacao"] is None
    assert banco.db.execute("SELECT nome_operacao_chave FROM lojas WHERE id = ?", (a["id"],)).fetchone()[0] is None
    assert _criar(banco, "Loja B", nome_operacao="Op A")["nome_operacao"] == "Op A"  # a chave foi liberada


def test_tamanhos_maximos():
    banco = criar_banco_sqlite()
    with pytest.raises(ValueError, match="código externo pode ter até 40"):
        _criar(banco, "A", codigo_externo="x" * 41)
    with pytest.raises(ValueError, match="nome de operação pode ter até 120"):
        _criar(banco, "A", nome_operacao="x" * 121)


def test_banco_recusa_codigo_e_operacao_repetidos_mesmo_sem_o_app():
    banco = criar_banco_sqlite()
    banco.db.execute("INSERT INTO lojas (nome, lat, lng, codigo_externo, nome_operacao_chave) VALUES ('A', -23, -46, 'X-1', 'sdamooca')")
    with pytest.raises(sqlite3.IntegrityError):
        banco.db.execute("INSERT INTO lojas (nome, lat, lng, codigo_externo) VALUES ('B', -23, -46, ' x-1 ')")
    with pytest.raises(sqlite3.IntegrityError):
        banco.db.execute("INSERT INTO lojas (nome, lat, lng, nome_operacao_chave) VALUES ('C', -23, -46, 'sdamooca')")


def test_mensagem_de_unicidade_pelo_nome_do_indice():
    assert lojas._mensagem_de_unicidade(Exception('duplicate key value violates unique constraint "ux_lojas_codigo_externo"')) == lojas.MSG_CODIGO_EXTERNO_REPETIDO
    assert lojas._mensagem_de_unicidade(Exception('violates unique constraint "ux_lojas_nome_operacao_chave"')) == lojas.MSG_OPERACAO_REPETIDA
    assert lojas._mensagem_de_unicidade(Exception('violates unique constraint "ux_lojas_nome"')) == lojas.MSG_NOME_REPETIDO


# ----------------------------------------------------------------------------------------------------------
# Rotas (login obrigatório, mensagens, e o PUT de um cliente antigo não apaga os campos)
# ----------------------------------------------------------------------------------------------------------
class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


@pytest.fixture
def api(monkeypatch):
    import main
    from fastapi.testclient import TestClient

    from backend.tests.fakes_asyncpg import FakePool

    banco = criar_banco_sqlite()

    async def get_pool():
        return FakePool(banco)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), banco, main
    main.app.dependency_overrides.clear()


CORPO = {"nome": "Atacadão Mooca", "uf": "SP", "lat": "-23,56", "lng": "-46,6"}


def test_rotas_de_lojas_continuam_exigindo_login():
    import main
    from fastapi.testclient import TestClient

    cliente = TestClient(main.app)
    assert cliente.get("/api/lojas").status_code == 401
    assert cliente.post("/api/lojas", json=CORPO).status_code == 401
    assert cliente.put("/api/lojas/1", json=CORPO).status_code == 401


def test_api_cria_e_edita_codigo_externo_e_nome_de_operacao_com_mensagem_clara_de_repeticao(api):
    cliente, _, _ = api
    a = cliente.post("/api/lojas", json={**CORPO, "codigo_externo": "S-1", "nome_operacao": "SDA Mooca"})
    assert a.status_code == 201 and a.json()["codigo_externo"] == "S-1" and a.json()["nome_operacao"] == "SDA Mooca"
    repetida_op = cliente.post("/api/lojas", json={**CORPO, "nome": "Outra", "nome_operacao": "sda  moóca"})
    assert repetida_op.status_code == 422 and repetida_op.json()["detail"] == "Já existe uma loja com esse nome de operação."
    repetido_cod = cliente.post("/api/lojas", json={**CORPO, "nome": "Outra", "codigo_externo": "s-1"})
    assert repetido_cod.status_code == 422 and repetido_cod.json()["detail"] == "Já existe uma loja com esse código externo."
    b = cliente.post("/api/lojas", json={**CORPO, "nome": "Outra", "codigo_externo": "S-2", "nome_operacao": "SDA Outra"}).json()
    editar = cliente.put(f"/api/lojas/{b['id']}", json={**CORPO, "nome": "Outra", "codigo_externo": "S-1", "nome_operacao": "SDA Outra"})
    assert editar.status_code == 422 and "código externo" in editar.json()["detail"]


def test_api_put_sem_os_campos_novos_nao_apaga_e_em_branco_limpa(api):
    cliente, _, _ = api
    loja = cliente.post("/api/lojas", json={**CORPO, "codigo_externo": "S-1", "nome_operacao": "SDA Mooca"}).json()
    mantida = cliente.put(f"/api/lojas/{loja['id']}", json={**CORPO, "uf": "RJ"})  # cliente que não conhece os campos
    assert mantida.status_code == 200 and mantida.json()["codigo_externo"] == "S-1" and mantida.json()["nome_operacao"] == "SDA Mooca"
    limpa = cliente.put(f"/api/lojas/{loja['id']}", json={**CORPO, "codigo_externo": None, "nome_operacao": ""})
    assert limpa.json()["codigo_externo"] is None and limpa.json()["nome_operacao"] is None


# ----------------------------------------------------------------------------------------------------------
# Migration 0009
# ----------------------------------------------------------------------------------------------------------
def _migracao(nome):
    spec = importlib.util.spec_from_file_location("m0009", RAIZ / "backend" / "migrations" / "versions" / nome)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_migration_0009_e_idempotente_e_nao_apaga_nada():
    modulo = _migracao("0009_lojas_codigo_externo_nome_operacao.py")
    assert modulo.revision == "0009" and modulo.down_revision == "0008"
    texto = " ".join(modulo.COMANDOS).upper()
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE)\b", texto)
    assert all("IF NOT EXISTS" in c.upper() for c in modulo.COMANDOS)
    assert "CODIGO_EXTERNO VARCHAR(40)" in texto and "NOME_OPERACAO VARCHAR(120)" in texto
    assert "WHERE CODIGO_EXTERNO IS NOT NULL" in texto and "WHERE NOME_OPERACAO_CHAVE IS NOT NULL" in texto


def test_migration_0009_roda_duas_vezes_e_preserva_as_lojas():
    banco = criar_banco_sqlite()
    banco.db.execute("INSERT INTO lojas (nome, lat, lng) VALUES ('Antiga', -23, -46)")
    for comando in _migracao("0009_lojas_codigo_externo_nome_operacao.py").COMANDOS:
        if comando.lstrip().upper().startswith("ALTER TABLE"):
            continue  # o SQLite não tem ADD COLUMN IF NOT EXISTS; as colunas já existem depois da primeira vez
        banco.db.execute(comando)
    assert banco.db.execute("SELECT nome, codigo_externo, nome_operacao FROM lojas").fetchone()[:] == ("Antiga", None, None)


# ----------------------------------------------------------------------------------------------------------
# Motoristas: casamento da loja da planilha por nome de operação e código externo
# ----------------------------------------------------------------------------------------------------------
CADASTRO = [
    {"id": 1, "nome": "Atacadão Mooca", "nome_operacao": "SDA Mooca", "codigo_externo": "S-100", "ativo": True},
    {"id": 2, "nome": "Atacadão Guarujá", "nome_operacao": None, "codigo_externo": None, "ativo": True},
    {"id": 3, "nome": "Sam's Club Campinas", "nome_operacao": "SDA Campinas", "codigo_externo": "S-300", "ativo": True},
    {"id": 4, "nome": "Atacadão Fechada", "nome_operacao": "SDA Fechada", "codigo_externo": "S-400", "ativo": False},
]


def _resultado(*nomes):
    r = carga.ResultadoCsvMotoristas(delimitador=";", codificacao="utf-8")
    r.linhas.append(carga.LinhaMotorista(numero=2, codigo="M-1", nome="Ana", tipo="Carro de passeio", lojas_nomes=list(nomes)))
    return r


@pytest.mark.parametrize("nome", ["SDA Mooca", "sda mooca", "  SDA   MOOCA", "Sda Moóca", "sdamooca", "S-100", "s-100", " S-100 "])
def test_motorista_liga_pelo_nome_de_operacao_ou_codigo_externo(nome):
    r = _resultado(nome)
    carga.conferir_lojas(r, CADASTRO)
    assert r.linhas[0].lojas_ids == [1], nome
    assert r.linhas[0].lojas_por_operacao == [nome] and r.linhas[0].lojas_nao_encontradas == []


def test_depois_da_operacao_vale_o_nome_da_loja_e_as_siglas():
    r = _resultado("Atacadão Guarujá", "SAMS Campinas", "SDA Campinas")
    carga.conferir_lojas(r, CADASTRO)
    l = r.linhas[0]
    assert l.lojas_ids == [2, 3] and l.lojas_por_operacao == ["SDA Campinas"]  # SAMS e SDA Campinas são a mesma loja: uma só vez


def test_nome_de_operacao_vale_antes_do_nome_da_loja():
    cadastro = CADASTRO + [{"id": 5, "nome": "SDA Mooca", "nome_operacao": None, "codigo_externo": None, "ativo": True}]
    r = _resultado("SDA Mooca")
    carga.conferir_lojas(r, cadastro)
    assert r.linhas[0].lojas_ids == [1] and r.linhas[0].lojas_por_operacao == ["SDA Mooca"]


def test_apelido_so_vale_depois_de_operacao_nome_e_siglas(tmp_path):
    caminho = tmp_path / "ap.csv"
    caminho.write_text('nome_na_planilha,motoristas,sugestoes,nome_da_loja\nSDA Mooca,1,,Atacadão Guarujá\nXpto,1,,Atacadão Guarujá\n', encoding="utf-8")
    ap = carga.ler_apelidos(caminho)
    r = _resultado("SDA Mooca", "Xpto")
    carga.conferir_lojas(r, CADASTRO, ap)
    l = r.linhas[0]
    assert l.lojas_ids == [1, 2] and l.lojas_por_operacao == ["SDA Mooca"] and l.lojas_por_apelido == ["Xpto"]


def test_operacao_ambigua_nao_vira_vinculo_e_loja_desativada_conta_como_nao_achada():
    cadastro = CADASTRO + [{"id": 6, "nome": "Outra", "nome_operacao": "sda  mooca", "codigo_externo": None, "ativo": True}]
    r = _resultado("SDA Mooca", "SDA Fechada")
    carga.conferir_lojas(r, cadastro)
    l = r.linhas[0]
    assert l.lojas_ids == [] and l.lojas_ambiguas == ["SDA Mooca"] and l.lojas_nao_encontradas == ["SDA Fechada (desativada)"]


def test_lojas_sem_as_colunas_novas_continuam_casando_pelo_nome():
    r = _resultado("Atacadão Guarujá")
    carga.conferir_lojas(r, [{"id": 2, "nome": "Atacadão Guarujá", "ativo": True}])
    assert r.linhas[0].lojas_ids == [2] and r.linhas[0].lojas_por_operacao == []


def test_resumo_conta_motoristas_ligados_por_nome_de_operacao():
    r = _resultado("SDA Mooca", "Atacadão Guarujá")
    r.linhas.append(carga.LinhaMotorista(numero=3, codigo="M-2", nome="Bia", tipo="Carro de passeio", lojas_nomes=["Atacadão Guarujá"]))
    carga.conferir_lojas(r, CADASTRO)
    assert carga.resumir(r)["ligados_por_operacao"] == 1


def test_ler_lojas_do_banco_traz_nome_de_operacao_e_codigo_externo():
    banco = criar_banco_sqlite()
    banco.db.execute("INSERT INTO lojas (nome, lat, lng, codigo_externo, nome_operacao) VALUES ('Atacadão Mooca', -23, -46, 'S-100', 'SDA Mooca')")
    achadas = asyncio.run(carga.ler_lojas(banco))
    assert achadas[0]["nome_operacao"] == "SDA Mooca" and achadas[0]["codigo_externo"] == "S-100"


def test_script_de_motoristas_mostra_quantos_foram_ligados_por_nome_de_operacao(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("carregar_motoristas_6c", RAIZ / "scripts" / "carregar_motoristas.py")
    mot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mot)
    banco = criar_banco_sqlite()
    banco.db.execute("INSERT INTO lojas (nome, lat, lng, codigo_externo, nome_operacao) VALUES ('Atacadão Mooca', -23, -46, 'S-100', 'SDA Mooca')")

    async def conectar(dsn):
        return banco

    monkeypatch.setattr(mot, "conectar", conectar)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:s@host.neon.tech/db?sslmode=require")
    caminho = tmp_path / "m.csv"
    caminho.write_text("Código,Nome,Tipo de veículo,Loja\nM-1,Ana,Passeio,SDA Mooca\nM-2,Bia,Passeio,Atacadão Mooca\n", encoding="utf-8")
    mot.main(["--csv", str(caminho), "--gravar", "--sim"])
    texto = capsys.readouterr().out
    assert "LIGADOS POR NOME DE OPERAÇÃO (ou código externo da loja): 1 motorista(s)" in texto
    assert banco.db.execute("SELECT count(*) FROM motorista_lojas").fetchone()[0] == 2
