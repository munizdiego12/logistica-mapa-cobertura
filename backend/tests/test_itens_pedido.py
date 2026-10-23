"""Subetapa 3 do peso: arquivo de itens do pedido (id_pedido, sku, quantidade, descricao opcional), relatório de validação e consulta de pesos. Informativo; sem banco gravado."""
import io
import json
import logging

import openpyxl
import pytest
from fastapi.testclient import TestClient

import item_pesos
import itens_fonte as fonte
import main
from backend.tests.fakes_asyncpg import FakePool, criar_banco_sqlite


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


TABELA = """
CREATE TABLE item_pesos (
    id_sku TEXT PRIMARY KEY, reference_code TEXT, nome TEXT, peso_kg REAL, fonte TEXT, confianca TEXT,
    unidades_vendidas INTEGER NOT NULL DEFAULT 0, atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP, atualizado_por TEXT
)
"""


@pytest.fixture
def banco():
    b = criar_banco_sqlite()
    b.db.execute(TABELA)
    b.db.execute("INSERT INTO item_pesos (id_sku, nome, peso_kg, confianca) VALUES ('10001', 'Arroz 5kg', 5.0, 'alta')")
    b.db.execute("INSERT INTO item_pesos (id_sku, nome, peso_kg, confianca) VALUES ('10002', 'Creme de Leite', 0.2, 'media')")
    b.db.execute("INSERT INTO item_pesos (id_sku, nome) VALUES ('10003', 'Sem peso ainda')")
    return b


@pytest.fixture
def api(monkeypatch, banco):
    async def get_pool():
        return FakePool(banco)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), banco
    main.app.dependency_overrides.clear()


def _csv(texto, codificacao="utf-8"):
    return texto.encode(codificacao)


def _validar(cliente, conteudo, nome="itens.csv", ids=None):
    dados = {} if ids is None else {"ids_pedidos": json.dumps(ids)}
    return cliente.post("/api/itens-pedido/validar", files={"file": (nome, conteudo)}, data=dados)


def _xlsx(linhas):
    pasta = openpyxl.Workbook()
    aba = pasta.active
    for linha in linhas:
        aba.append(linha)
    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()


BASICO = "id_pedido;sku;quantidade\n1001;10001;2\n1001;10002;1,5\n1002;10001;1\n"


# ----------------------------------------------------------------------------------------------------------
# Leitura: cabeçalhos, separadores, codificações, XLSX
# ----------------------------------------------------------------------------------------------------------
def test_modelo_basico_valido_com_resumo_itens_e_pesos(api):
    cliente, _ = api
    r = _validar(cliente, _csv(BASICO))
    assert r.status_code == 200
    j = r.json()
    assert j["formato"] == "csv" and j["erros"] == [] and j["avisos"] == []
    assert j["resumo"] == {"linhas": 3, "validas": 3, "invalidas": 0, "fora_do_lote": 0, "pedidos_com_itens": 2, "skus_distintos": 2, "skus_novos": 0, "skus_sem_peso": 0}
    assert {(i["id_pedido"], i["sku"], i["quantidade"]) for i in j["itens"]} == {("1001", "10001", 2), ("1001", "10002", 1.5), ("1002", "10001", 1)}
    assert j["pesos"] == {"10001": {"peso_kg": 5.0, "confianca": "alta"}, "10002": {"peso_kg": 0.2, "confianca": "media"}}


@pytest.mark.parametrize("texto,codificacao", [
    ("Pedido,SKU,Qtd\n1001,10001,2\n", "utf-8"),
    ("ID do pedido;Código;Quantidade\n1001;10001;2\n", "utf-8"),
    ("N pedido;código do item;QTDE\n1001;10001;2\n", "cp1252"),
    ("order_id\tid_sku\tquantity_sku\n1001\t10001\t2\n", "utf-8"),
    ("﻿id_pedido;sku;quantidade\n1001;10001;2\n", "utf-8"),
    ('"id_pedido","sku","quantidade"\n"1001","10001","2"\n', "utf-8"),
])
def test_cabecalhos_variados_separadores_e_codificacoes(api, texto, codificacao):
    cliente, _ = api
    j = _validar(cliente, _csv(texto, codificacao)).json()
    assert j["erros"] == [] and j["resumo"]["validas"] == 1
    assert j["itens"][0] == {"id_pedido": "1001", "sku": "10001", "quantidade": 2, "descricao": None}


def test_quantidade_com_virgula_e_ponto_decimal(api):
    cliente, _ = api
    j = _validar(cliente, _csv("id_pedido;sku;quantidade\n1;10001;0,5\n2;10001;2.5\n3;10001;3\n")).json()
    assert [i["quantidade"] for i in j["itens"]] == [0.5, 2.5, 3]


def test_xlsx_com_titulo_acima_do_cabecalho_e_numeros(api):
    cliente, _ = api
    conteudo = _xlsx([["Itens do dia"], [], ["Pedido", "SKU", "Quantidade"], [1001, 10001, 2], [1001, "10002", 1.5], [1002.0, 10001.0, 1]])
    j = _validar(cliente, conteudo, "itens.xlsx").json()
    assert j["formato"] == "xlsx" and j["erros"] == [] and j["resumo"]["validas"] == 3
    assert {(i["id_pedido"], i["sku"]) for i in j["itens"]} == {("1001", "10001"), ("1001", "10002"), ("1002", "10001")}


def test_modelo_para_baixar_tem_as_colunas_com_a_descricao_opcional_e_volta_valido(api):
    cliente, _ = api
    r = cliente.get("/api/itens-pedido/modelo")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert r.content.startswith(b"\xef\xbb\xbf")
    linhas = r.content.decode("utf-8-sig").splitlines()
    assert linhas[0] == "id_pedido;sku;quantidade;descricao" and len(linhas) == 3
    j = _validar(cliente, r.content).json()
    assert j["erros"] == [] and j["resumo"]["validas"] == 2 and j["itens"][0]["descricao"] == "Arroz Branco Tipo 1 5kg"


# ----------------------------------------------------------------------------------------------------------
# Erros, avisos e relatório
# ----------------------------------------------------------------------------------------------------------
def test_relatorio_com_todos_os_tipos_de_erro(api):
    cliente, _ = api
    texto = (
        "id_pedido;sku;quantidade\n"
        ";10001;1\n"                      # linha 2: id_pedido vazio
        "1001;;1\n"                        # 3: sku vazio
        "1001;AB CD;1\n"                   # 4: sku inválido
        "1001;10001;\n"                    # 5: quantidade vazia
        "1001;10001;abc\n"                 # 6: texto
        "1001;10001;0\n"                   # 7: zero
        "1001;10001;-2\n"                  # 8: negativa
        "1001;10001;100001\n"              # 9: acima do limite
        + "9" * 61 + ";10001;1\n"          # 10: id_pedido longo
        "1001;10001;1\n"                   # 11: válida
    )
    j = _validar(cliente, _csv(texto)).json()
    por_linha = {e["linha"]: e["motivos"] for e in j["erros"]}
    assert list(por_linha) == [2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert por_linha[2] == ["id_pedido vazio"] and por_linha[3] == ["sku vazio"] and "sku inválido" in por_linha[4][0]
    assert por_linha[5] == ["quantidade vazia"] and "quantidade inválida" in por_linha[6][0] and "quantidade inválida" in por_linha[7][0]
    assert "quantidade inválida" in por_linha[8][0] and "acima do limite" in por_linha[9][0] and "id_pedido longo demais" in por_linha[10][0]
    assert j["resumo"]["validas"] == 1 and j["resumo"]["invalidas"] == 9 and len(j["itens"]) == 1


def test_pedido_fora_do_lote_e_listado_e_ignorado_sem_ser_erro(api):
    cliente, _ = api
    j = _validar(cliente, _csv(BASICO + "9999;10001;3\n9999;10002;1\n8888;10001;1\n"), ids=["1001", "1002"]).json()
    assert j["erros"] == [] and j["resumo"]["fora_do_lote"] == 3 and j["resumo"]["validas"] == 3
    assert sorted(j["pedidos_fora_do_lote"]) == ["8888", "9999"] and j["total_pedidos_fora_do_lote"] == 2
    assert {i["id_pedido"] for i in j["itens"]} == {"1001", "1002"}
    sem = _validar(cliente, _csv(BASICO + "9999;10001;3\n")).json()  # sem a lista do lote, não confere
    assert sem["pedidos_fora_do_lote"] == [] and sem["resumo"]["validas"] == 4


def test_id_do_pedido_do_xlsx_com_ponto_zero_casa_com_o_lote(api):
    cliente, _ = api
    j = _validar(cliente, _xlsx([["pedido", "sku", "quantidade"], [1001.0, 10001, 1]]), "i.xlsx", ids=["1001"]).json()
    assert j["resumo"]["validas"] == 1 and j["resumo"]["fora_do_lote"] == 0


def test_linha_repetida_soma_as_quantidades_com_aviso(api):
    cliente, _ = api
    j = _validar(cliente, _csv("id_pedido;sku;quantidade\n1001;10001;2\n1002;10001;1\n1001;10001;3\n1001;10001;0,5\n")).json()
    item = next(i for i in j["itens"] if i["id_pedido"] == "1001")
    assert item["quantidade"] == 5.5 and len(j["itens"]) == 2
    assert j["resumo"]["validas"] == 4
    assert [a for a in j["avisos"] if "repetida" in a["motivo"]] == [{"linha": 2, "motivo": "linha repetida (mesmo pedido e sku nas linhas 2, 4 e 5): as quantidades foram somadas"}]


@pytest.mark.parametrize("quantidade,esperado", [("1.000", "1,000"), ("2.500", "2,500"), ("10.125", "10,125")])
def test_aviso_de_quantidade_que_parece_milhar_a_linha_vale(api, quantidade, esperado):
    cliente, _ = api
    j = _validar(cliente, _csv(f"id_pedido;sku;quantidade\n1001;10001;{quantidade}\n")).json()
    assert j["erros"] == [] and j["resumo"]["validas"] == 1
    assert j["itens"][0]["quantidade"] == float(quantidade)  # lida como decimal
    avisos = [a for a in j["avisos"] if "decimal" in a["motivo"]]
    assert avisos == [{"linha": 2, "motivo": f"quantidade lida como decimal ({esperado}); se for milhar, o arquivo deve usar o número sem ponto"}]


@pytest.mark.parametrize("quantidade", ["1.000,5", "1,000", "1000", "2.5", "0.25", "1.0000", "1.00"])
def test_sem_aviso_de_milhar_nos_outros_formatos(api, quantidade):
    cliente, _ = api
    j = _validar(cliente, _csv(f'id_pedido;sku;quantidade\n1001;10001;"{quantidade}"\n')).json()
    assert j["erros"] == []
    assert not [a for a in j["avisos"] if "decimal" in a["motivo"]]


def test_sku_novo_e_sku_sem_peso_viram_avisos_e_listas(api):
    cliente, _ = api
    j = _validar(cliente, _csv("id_pedido;sku;quantidade;descricao\n1;10001;1;Arroz\n1;10003;2;Item sem peso\n2;77777;4;Produto novo\n")).json()
    assert j["resumo"]["skus_novos"] == 1 and j["resumo"]["skus_sem_peso"] == 1
    assert j["skus_novos"] == [{"sku": "77777", "descricao": "Produto novo"}]
    assert j["skus_sem_peso"] == [{"sku": "10003", "descricao": "Item sem peso"}]
    assert j["pesos"]["10003"] == {"peso_kg": None, "confianca": None} and "77777" not in j["pesos"]
    textos = [a["motivo"] for a in j["avisos"]]
    assert any("não estão no cadastro de pesos" in t for t in textos) and any("existem sem peso" in t for t in textos)


# ----------------------------------------------------------------------------------------------------------
# Descrição opcional
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("cabecalho", ["descricao", "Descrição", "nome", "produto", "Nome do item", "descrição do item"])
def test_descricao_opcional_com_variacoes_de_cabecalho(api, cabecalho):
    cliente, _ = api
    j = _validar(cliente, _csv(f"id_pedido;sku;quantidade;{cabecalho}\n1;77777;1;Biscoito Recheado\n")).json()
    assert j["erros"] == [] and j["itens"][0]["descricao"] == "Biscoito Recheado"
    assert j["skus_novos"][0]["descricao"] == "Biscoito Recheado"


def test_sem_a_coluna_descricao_continua_valido(api):
    cliente, _ = api
    j = _validar(cliente, _csv("id_pedido;sku;quantidade\n1;77777;1\n")).json()
    assert j["erros"] == [] and j["itens"][0]["descricao"] is None and j["skus_novos"] == [{"sku": "77777", "descricao": None}]


def test_mesmo_sku_com_descricoes_diferentes_vale_a_primeira_sem_erro(api):
    cliente, _ = api
    j = _validar(cliente, _csv("id_pedido;sku;quantidade;descricao\n1;77777;1;Primeira\n2;77777;1;Segunda\n3;77777;1;\n")).json()
    assert j["erros"] == [] and {i["descricao"] for i in j["itens"]} == {"Primeira"}
    assert j["skus_novos"] == [{"sku": "77777", "descricao": "Primeira"}]


def test_descricao_longa_e_cortada_em_300_com_aviso(api):
    cliente, _ = api
    longa = "A" * 350
    j = _validar(cliente, _csv(f"id_pedido;sku;quantidade;descricao\n1;77777;1;{longa}\n")).json()
    assert j["erros"] == [] and len(j["itens"][0]["descricao"]) == 300 == fonte.TAMANHO_DESCRICAO
    assert [a for a in j["avisos"] if "cortada em 300" in a["motivo"]]


# ----------------------------------------------------------------------------------------------------------
# Arquivo todo: erros de leitura, limites, login
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("conteudo,nome,trecho", [
    (b"id_pedido;sku\n1;10001\n", "a.csv", "Faltam colunas obrigatórias"),
    (b"", "a.csv", "vazio"),
    (b"qualquer", "a.txt", "Formato de arquivo inválido"),
    (b"qualquer", "a.xls", ".xls antigas"),
    (b"isto nao e uma planilha", "a.xlsx", "Não consegui ler a planilha"),
])
def test_erros_do_arquivo_todo_sao_400_com_texto_fixo(api, conteudo, nome, trecho):
    cliente, _ = api
    r = _validar(cliente, conteudo, nome)
    assert r.status_code == 400 and trecho in r.json()["detail"]


def test_arquivo_grande_demais_e_acima_de_20_mil_linhas(api):
    cliente, _ = api
    grande = b"id_pedido;sku;quantidade\n" + b"1;10001;1\n" * 600_000
    assert len(grande) > fonte.MAX_BYTES
    r = _validar(cliente, grande)
    assert r.status_code == 400 and "grande demais" in r.json()["detail"]
    muitas = "id_pedido;sku;quantidade\n" + "1;10001;1\n" * 20001
    r = _validar(cliente, _csv(muitas))
    assert r.status_code == 400 and "mais de 20.000 linhas" in r.json()["detail"]
    ok = "id_pedido;sku;quantidade\n" + "".join(f"{i};10001;1\n" for i in range(20000))
    r = _validar(cliente, _csv(ok))
    assert r.status_code == 200 and r.json()["resumo"]["validas"] == 20000


def test_lista_de_ids_do_lote_invalida_e_422(api):
    cliente, _ = api
    r = cliente.post("/api/itens-pedido/validar", files={"file": ("i.csv", _csv(BASICO))}, data={"ids_pedidos": "isto nao e json"})
    assert r.status_code == 422 and "lista de pedidos" in r.json()["detail"]
    r = cliente.post("/api/itens-pedido/validar", files={"file": ("i.csv", _csv(BASICO))}, data={"ids_pedidos": '{"a": 1}'})
    assert r.status_code == 422


def test_as_rotas_novas_exigem_login():
    main.app.dependency_overrides.clear()
    cliente = TestClient(main.app)
    assert cliente.get("/api/itens-pedido/modelo").status_code == 401
    assert cliente.post("/api/itens-pedido/validar", files={"file": ("i.csv", b"x")}).status_code == 401
    assert cliente.post("/api/item-pesos/consultar", json={"skus": ["1"]}).status_code == 401


# ----------------------------------------------------------------------------------------------------------
# Consulta de pesos
# ----------------------------------------------------------------------------------------------------------
def test_consultar_devolve_so_os_que_existem_com_peso_e_confianca(api):
    cliente, _ = api
    r = cliente.post("/api/item-pesos/consultar", json={"skus": ["10001", "10003", "00000", "10001", " 10002 ", "AB CD", ""]})
    assert r.status_code == 200
    assert r.json() == {"pesos": {"10001": {"peso_kg": 5.0, "confianca": "alta"}, "10002": {"peso_kg": 0.2, "confianca": "media"}, "10003": {"peso_kg": None, "confianca": None}}}
    texto = r.text
    assert "Arroz" not in texto and "atualizado" not in texto and "nome" not in texto  # sem nome nem quem alterou


def test_consultar_lista_vazia_e_limite_de_5000(api):
    cliente, _ = api
    assert cliente.post("/api/item-pesos/consultar", json={"skus": []}).json() == {"pesos": {}}
    assert cliente.post("/api/item-pesos/consultar", json={}).json() == {"pesos": {}}
    assert cliente.post("/api/item-pesos/consultar", json={"skus": [str(i) for i in range(5001)]}).status_code == 422


def test_consultar_acha_o_peso_cadastrado_depois_de_o_operador_editar(api):
    cliente, banco = api
    antes = cliente.post("/api/item-pesos/consultar", json={"skus": ["10003"]}).json()["pesos"]["10003"]
    assert antes["peso_kg"] is None
    banco.db.execute("UPDATE item_pesos SET peso_kg = 2.5, confianca = 'alta' WHERE id_sku = '10003'")  # o operador cadastrou o peso na tela "Pesos dos itens"
    depois = cliente.post("/api/item-pesos/consultar", json={"skus": ["10003"]}).json()["pesos"]["10003"]
    assert depois == {"peso_kg": 2.5, "confianca": "alta"}


def test_consultar_em_varios_blocos(banco):
    import asyncio
    for i in range(1200):
        banco.db.execute("INSERT OR IGNORE INTO item_pesos (id_sku, nome, peso_kg) VALUES (?, 'x', 1.0)", (f"S{i}",))
    achados = asyncio.run(item_pesos.consultar_pesos(banco, [f"S{i}" for i in range(1200)] + ["NAOEXISTE"]))
    assert len(achados) == 1200 and "NAOEXISTE" not in achados


# ----------------------------------------------------------------------------------------------------------
# Só leitura, privacidade e compatibilidade
# ----------------------------------------------------------------------------------------------------------
def test_validar_so_le_o_banco_nunca_grava(api):
    cliente, banco = api
    antes = [tuple(l) for l in banco.db.execute("SELECT * FROM item_pesos ORDER BY id_sku")]
    _validar(cliente, _csv("id_pedido;sku;quantidade;descricao\n1;77777;1;Novo\n1;10003;1;X\n"))
    cliente.post("/api/item-pesos/consultar", json={"skus": ["77777", "10003"]})
    assert [tuple(l) for l in banco.db.execute("SELECT * FROM item_pesos ORDER BY id_sku")] == antes
    assert not any(s.strip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in banco.sqls[-4:])


def test_sem_linha_valida_o_banco_nem_e_consultado(api, monkeypatch):
    cliente, _ = api
    chamadas = []

    async def espia(conn, skus):
        chamadas.append(skus)
        return {}

    monkeypatch.setattr(item_pesos, "consultar_pesos", espia)
    _validar(cliente, _csv("id_pedido;sku;quantidade\n;10001;1\n1001;10001;0\n"))
    assert chamadas == []
    _validar(cliente, _csv("id_pedido;sku;quantidade\n1001;10001;1\n"))
    assert chamadas == [["10001"]]


def test_nada_do_arquivo_em_log_ou_mensagem_de_erro(api, caplog, capsys, monkeypatch):
    cliente, _ = api
    caplog.set_level(logging.DEBUG)
    segredo = "PEDIDO-SECRETO-4242"
    respostas = [
        _validar(cliente, _csv(f"id_pedido;sku;quantidade;descricao\n{segredo};SKU-SECRETO-9;1;Produto Reservado Xyz\n{segredo};SKU-SECRETO-9;abc;Outro\n"), ids=["1"]),
        _validar(cliente, _csv(f"id_pedido;sku\n{segredo};10001\n")),  # coluna faltando
        _validar(cliente, _csv("id_pedido;sku;quantidade\n1;10001;1\n"), ids=None),
    ]
    # falha inesperada na leitura: só a classe do erro é registrada
    def quebra(self):
        raise RuntimeError(f"falha com {segredo} e SKU-SECRETO-9")

    monkeypatch.setattr(fonte.FonteArquivoItens, "ler", quebra)
    r = _validar(cliente, _csv("id_pedido;sku;quantidade\n1;10001;1\n"))
    assert r.status_code == 400 and r.json()["detail"] == main.MSG_ARQUIVO_DE_ITENS_DO_PEDIDO_ILEGIVEL
    saida = capsys.readouterr().out + caplog.text
    assert "RuntimeError" in saida
    for segredo_ in (segredo, "SKU-SECRETO-9", "Produto Reservado"):
        assert segredo_ not in saida
    # os motivos dos erros citam só o campo e a linha, nunca o valor da célula
    textos = json.dumps([e["motivos"] for e in respostas[0].json()["erros"]], ensure_ascii=False)
    assert "SKU-SECRETO" not in textos and segredo not in textos
    assert segredo not in respostas[1].text


def test_formato_antigo_continua_compativel(api):
    cliente, _ = api
    pedidos = "id;endereco;numero;cidade;uf\n1;Rua A;10;Santos;SP\n"
    r = cliente.post("/api/pedidos/validar", files={"file": ("p.csv", pedidos.encode())})
    assert r.status_code == 200 and r.json()["pedidos"][0]["id"] == "1"
    assert cliente.get("/api/item-pesos/modelo").status_code == 200


def test_skus_vistos_continua_igual_e_guarda_o_nome_so_de_sku_novo():
    import asyncio
    from backend.tests.fakes_asyncpg import FakeConn
    conn = FakeConn([[{"id_sku": "10003"}]])  # 10003 já existe; 55555 é novo
    resposta = asyncio.run(item_pesos.registrar_skus_vistos(conn, [{"id_sku": "10003", "quantidade": 1, "nome": "Outro nome"}, {"id_sku": "55555", "quantidade": 3, "nome": "Biscoito"}]))
    assert resposta == {"novos": 1, "ja_existiam": 1}
    gravado = next(c for c in conn.chamadas if c[0] == "executemany")[2]
    assert ("55555", None, "Biscoito", 3) in gravado
    # o SQL guarda o nome só se o item ainda não tem um: nunca sobrescreve um nome já cadastrado
    assert "COALESCE(item_pesos.nome, EXCLUDED.nome)" in item_pesos.SQL_REGISTRAR_VISTO


def test_a_fonte_de_itens_tem_interface_unica_e_registro_de_fontes():
    assert fonte.FONTES["arquivo"] is fonte.FonteArquivoItens
    bruto = fonte.FonteArquivoItens(_csv(BASICO), "x.csv").ler()
    assert isinstance(bruto, fonte.LoteItensBruto) and bruto.origem == "arquivo" and len(bruto.linhas) == 3

    class FonteDeTeste:  # uma fonte futura (Etapa 15) só precisa devolver o lote com os campos padrão
        def ler(self):
            return fonte.LoteItensBruto("bigquery", "api", {}, [fonte.LinhaItemBruta(2, {"id_pedido": "7", "sku": "10001", "quantidade": "2"})])

    resultado = fonte.validar_itens(FonteDeTeste().ler(), ["7"])
    assert resultado.erros == [] and resultado.itens[0]["quantidade"] == 2
