"""Pesos dos itens: novo item (um por vez) e importação de vários itens por CSV/XLSX (relatório antes, confirmação revalidada)."""
import asyncio
import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

import item_pesos
import item_pesos_importacao as imp
import main
from backend.tests.fakes_asyncpg import FakePool, criar_banco_sqlite

OPERADOR = "Maria Souza (maria@zubale.com)"
OUTRO = "João Lima (joao@zubale.com)"


class OperadorFalso:
    nome = "Maria Souza"
    email = "maria@zubale.com"


TABELA = """
CREATE TABLE item_pesos (
    id_sku TEXT PRIMARY KEY, reference_code TEXT, nome TEXT, peso_kg REAL, fonte TEXT, confianca TEXT,
    unidades_vendidas INTEGER NOT NULL DEFAULT 0, atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP, atualizado_por TEXT,
    CHECK (peso_kg IS NULL OR (peso_kg > 0 AND peso_kg <= 1000)),
    CHECK (confianca IS NULL OR confianca IN ('alta', 'media', 'baixa'))
)
"""


@pytest.fixture
def banco():
    b = criar_banco_sqlite()
    b.db.execute(TABELA)
    return b


@pytest.fixture
def api(monkeypatch, banco):
    chamadas = {"pool": 0}

    async def get_pool():
        chamadas["pool"] += 1
        return FakePool(banco)

    main.app.dependency_overrides[main.obter_operador_atual] = lambda: OperadorFalso()
    monkeypatch.setattr(main.database, "get_pool", get_pool)
    yield TestClient(main.app), banco, chamadas
    main.app.dependency_overrides.clear()


def _item(banco, id_sku, nome="Item", peso=None, por=None, fonte=None, confianca=None, unidades=0):
    banco.db.execute(
        "INSERT INTO item_pesos (id_sku, nome, peso_kg, fonte, confianca, unidades_vendidas, atualizado_por) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id_sku, nome, peso, fonte, confianca, unidades, por),
    )


def _linha(banco, id_sku):
    r = banco.db.execute("SELECT * FROM item_pesos WHERE id_sku = ?", (id_sku,)).fetchone()
    return None if r is None else dict(r)


def _total(banco):
    return banco.db.execute("SELECT count(*) FROM item_pesos").fetchone()[0]


# ----------------------------------------------------------------------------------------------------------
# Novo item, um por vez
# ----------------------------------------------------------------------------------------------------------
def _novo(cliente, **extra):
    corpo = {"id_sku": "90001", "nome": "Arroz 5kg", "peso_kg": "5"}
    corpo.update(extra)
    return cliente.post("/api/item-pesos", json=corpo)


def test_criar_com_peso_virgula_decimal_confianca_padrao_media_e_registra_quem_criou(api):
    cliente, banco, _ = api
    r = _novo(cliente, peso_kg="1,5", reference_code="REF-1", fonte="balança da loja")
    assert r.status_code == 201
    item = r.json()
    assert (item["id_sku"], item["nome"], item["peso_kg"], item["confianca"], item["fonte"], item["reference_code"]) == ("90001", "Arroz 5kg", 1.5, "media", "balança da loja", "REF-1")
    assert item["atualizado_por"] == OPERADOR and item["atualizado_em"] and item["unidades_vendidas"] == 0
    assert _linha(banco, "90001")["atualizado_por"] == OPERADOR


def test_criar_com_peso_sem_fonte_grava_manual_e_aceita_confianca_escolhida(api):
    cliente, banco, _ = api
    item = _novo(cliente, id_sku="90002", peso_kg=0.045, confianca="Alta").json()
    assert item["fonte"] == "manual" and item["confianca"] == "alta" and item["peso_kg"] == 0.045


def test_criar_sem_peso_entra_na_fila_sem_peso(api):
    cliente, banco, _ = api
    r = _novo(cliente, id_sku="90003", peso_kg=None)
    assert r.status_code == 201 and r.json()["peso_kg"] is None and r.json()["confianca"] is None
    fila = banco.db.execute("SELECT id_sku FROM item_pesos WHERE peso_kg IS NULL").fetchall()
    assert [f[0] for f in fila] == ["90003"]
    assert _novo(cliente, id_sku="90004", peso_kg="").json()["peso_kg"] is None  # vazio também é "sem peso"


@pytest.mark.parametrize("repetido", ["90001", " 90001 "])
def test_codigo_repetido_responde_409_com_a_mensagem_combinada(api, repetido):
    cliente, banco, _ = api
    assert _novo(cliente).status_code == 201
    r = _novo(cliente, id_sku=repetido, nome="Outro")
    assert r.status_code == 409 and r.json()["detail"] == "Já existe um item com este código. Edite-o na lista."
    assert _total(banco) == 1


@pytest.mark.parametrize("novo, existente", [("abc-1", "ABC-1"), ("ABC-1", "abc-1"), ("Sku.9", "sKU.9")])
def test_codigo_repetido_ignora_maiusculas(api, novo, existente):
    cliente, banco, _ = api
    _item(banco, existente)
    r = _novo(cliente, id_sku=novo)
    assert r.status_code == 409 and r.json()["detail"] == item_pesos.MSG_ITEM_JA_EXISTE
    assert _total(banco) == 1


def test_codigo_repetido_ignora_espacos_nas_pontas_do_que_ja_esta_gravado(api):
    cliente, banco, _ = api
    _item(banco, " X1 ")  # gravado com espaços (dado antigo)
    assert _novo(cliente, id_sku="x1").status_code == 409


@pytest.mark.parametrize("mudanca, mensagem", [
    ({"id_sku": ""}, "Informe o código do item."),
    ({"id_sku": "   "}, "Informe o código do item."),
    ({"id_sku": "a b"}, "O código do item pode ter até 40 letras"),
    ({"id_sku": "x" * 41}, "O código do item pode ter até 40 letras"),
    ({"nome": ""}, "Informe o nome do item."),
    ({"nome": "   "}, "Informe o nome do item."),
    ({"nome": "n" * 301}, "O nome do item pode ter até 300"),
    ({"peso_kg": "abc"}, "O peso precisa ser um número em kg, maior que 0 e até 1000"),
    ({"peso_kg": "0"}, "O peso precisa ser um número em kg"),
    ({"peso_kg": "-2"}, "O peso precisa ser um número em kg"),
    ({"peso_kg": "1000,5"}, "O peso precisa ser um número em kg"),
    ({"confianca": "altíssima"}, "Escolha a confiança: alta, média ou baixa."),
    ({"reference_code": "r" * 61}, "O código de referência pode ter até 60"),
    ({"fonte": "f" * 101}, "A fonte pode ter até 100"),
])
def test_mensagens_de_validacao_em_linguagem_do_operador(api, mudanca, mensagem):
    cliente, banco, _ = api
    r = _novo(cliente, **mudanca)
    assert r.status_code == 422 and mensagem in r.json()["detail"]
    assert _total(banco) == 0


def test_peso_maximo_de_1000_kg_e_aceito(api):
    cliente, _, _ = api
    assert _novo(cliente, peso_kg="1000").status_code == 201


def test_criar_exige_login():
    main.app.dependency_overrides.clear()
    assert TestClient(main.app).post("/api/item-pesos", json={"id_sku": "1", "nome": "x"}).status_code == 401


# ----------------------------------------------------------------------------------------------------------
# Importação: leitura do arquivo
# ----------------------------------------------------------------------------------------------------------
def _csv(texto, codificacao="utf-8"):
    return texto.encode(codificacao)


def _validar(cliente, conteudo, nome="itens.csv"):
    return cliente.post("/api/item-pesos/importar/validar", files={"file": (nome, conteudo, "application/octet-stream")})


def _confirmar(cliente, conteudo, nome="itens.csv", **opcoes):
    dados = {k: ("true" if v else "false") for k, v in opcoes.items()}
    return cliente.post("/api/item-pesos/importar/confirmar", files={"file": (nome, conteudo, "application/octet-stream")}, data=dados)


def _xlsx(cabecalho, linhas):
    pasta = openpyxl.Workbook()
    ws = pasta.active
    ws.append(cabecalho)
    for l in linhas:
        ws.append(l)
    saida = io.BytesIO()
    pasta.save(saida)
    return saida.getvalue()


@pytest.mark.parametrize("texto, codificacao", [
    ('Código;Descrição;Peso;Fonte;Confiança;Unidades vendidas\n"101";"Café Pilão 500g";"0,5";"embalagem";"Alta";"1.200"\n102;Açúcar 1kg;1;;;\n', "utf-8"),
    ('SKU,Produto,Peso (kg),Fonte,Confianca\n101,Café Pilão 500g,"0,5",embalagem,alta\n102,Açúcar 1kg,"1,0",,\n', "utf-8"),
    ('ID_SKU;Nome do item;PESO_KG;fonte;CONFIANÇA\n101;Café Pilão 500g;0.5;embalagem;ALTA\n102;Açúcar 1kg;1;;\n', "cp1252"),
    ("﻿id sku;referência;nome;peso kg;fonte;confiança\n101;;Café Pilão 500g;0,5;embalagem;média\n102;;Açúcar 1kg;1;;\n", "utf-8"),
])
def test_cabecalhos_variados_decimal_virgula_aspas_e_codificacoes(api, texto, codificacao):
    cliente, banco, _ = api
    r = _validar(cliente, _csv(texto, codificacao))
    assert r.status_code == 200, r.text
    resumo = r.json()["resumo"]
    assert (resumo["linhas"], resumo["validas"], resumo["invalidos"], resumo["novos_com_peso"]) == (2, 2, 0, 2)
    r = _confirmar(cliente, _csv(texto, codificacao))
    assert r.status_code == 200 and r.json()["novos"] == 2
    assert _linha(banco, "101")["peso_kg"] == 0.5 and _linha(banco, "101")["nome"] == "Café Pilão 500g"
    assert _linha(banco, "102")["peso_kg"] == 1.0


def test_formato_antigo_do_estudo_de_pesos(api):
    cliente, banco, _ = api
    texto = ("id_sku,reference_code,nome,peso_kg_sugerido,fonte,confianca,unidades_vendidas\n"
             '27439,23290909,Creme de Leite 200g,"0,2",nome,alta,2954\n27440,,Item sem peso,,,,10\n')
    r = _validar(cliente, _csv(texto)).json()
    assert r["resumo"]["validas"] == 2 and r["resumo"]["novos_sem_peso"] == 1 and r["colunas"]["peso"] == "peso_kg_sugerido"
    _confirmar(cliente, _csv(texto))
    assert _linha(banco, "27439")["unidades_vendidas"] == 2954 and _linha(banco, "27439")["reference_code"] == "23290909"
    assert _linha(banco, "27440")["peso_kg"] is None and _linha(banco, "27440")["unidades_vendidas"] == 10


def test_xlsx_tambem_e_aceito(api):
    cliente, banco, _ = api
    conteudo = _xlsx(["código", "nome", "peso_kg", "confiança"], [[201, "Feijão 1kg", 1.0, "alta"], [202, "Sal 1kg", "1,2", None]])
    r = _validar(cliente, conteudo, "itens.xlsx").json()
    assert r["formato"] == "xlsx" and r["resumo"]["validas"] == 2
    assert _confirmar(cliente, conteudo, "itens.xlsx").json()["novos"] == 2
    assert _linha(banco, "201")["peso_kg"] == 1.0 and _linha(banco, "202")["peso_kg"] == 1.2 and _linha(banco, "202")["confianca"] == "media"


def test_modelo_para_baixar_tem_as_colunas_e_dois_exemplos_e_volta_valido(api):
    cliente, banco, _ = api
    r = cliente.get("/api/item-pesos/modelo")
    assert r.status_code == 200 and "modelo_itens_pesos.csv" in r.headers["content-disposition"]
    linhas = r.content.decode("utf-8-sig").splitlines()
    assert linhas[0] == "id_sku;reference_code;nome;peso_kg;fonte;confianca" and len(linhas) == 3
    rel = _validar(cliente, r.content).json()
    assert rel["resumo"]["validas"] == 2 and rel["resumo"]["invalidos"] == 0 and rel["resumo"]["novos_com_peso"] == 2


# ----------------------------------------------------------------------------------------------------------
# Importação: relatório
# ----------------------------------------------------------------------------------------------------------
def test_relatorio_com_todos_os_tipos_de_erro_e_as_contagens(api):
    cliente, banco, _ = api
    _item(banco, "300", nome="Já existia", peso=2.0, por="carga inicial (script)")
    _item(banco, "301", nome="Editado na tela", peso=3.0, por=OUTRO)
    texto = (
        "id_sku;nome;peso_kg;confianca\n"
        "1;Novo com peso;1,5;alta\n"          # linha 2: novo com peso
        "2;Novo sem peso;;\n"                  # linha 3: novo sem peso
        "300;Já existia;5;\n"                  # linha 4: existente (atualizável)
        "301;Editado na tela;5;\n"             # linha 5: existente e preservado
        ";Sem código;1;\n"                     # linha 6: código vazio
        "3;;1;\n"                              # linha 7: nome vazio
        "4;Peso ruim;abc;\n"                   # linha 8: peso inválido
        "5;Peso zero;0;\n"                     # linha 9: peso inválido
        "6;Confiança ruim;1;talvez\n"          # linha 10: confiança inválida
        "1;Repetido;2;\n"                      # linha 11: código repetido
        "7;Com espaço no código;1;\n"          # válida
    ).replace("7;Com espaço no código;1;", "7 8;Código com espaço;1;")  # inválido: código com espaço
    rel = _validar(cliente, _csv(texto)).json()
    assert rel["resumo"] == {"linhas": 11, "validas": 4, "invalidos": 7, "novos_com_peso": 1, "novos_sem_peso": 1, "existentes": 2,
                             "existentes_atualizaveis": 1, "existentes_atualizaveis_sem_peso": 0, "existentes_preservados": 1, "sem_peso": 1}
    motivos = {e["linha"]: e["motivos"][0] for e in rel["erros"]}
    assert motivos == {
        6: "código vazio", 7: "nome vazio", 8: "peso inválido (use um número em kg, maior que 0 e até 1000)",
        9: "peso inválido (use um número em kg, maior que 0 e até 1000)", 10: "confiança inválida (use alta, média ou baixa)",
        11: "código repetido no arquivo (a primeira vez está na linha 2)", 12: "código inválido (até 40 letras, números, ponto, hífen ou sublinhado, sem espaços)",
    }
    assert rel["erros_truncados"] is False and _total(banco) == 2  # o relatório não grava nada


def test_codigo_repetido_ignora_maiusculas_dentro_do_arquivo(api):
    cliente, _, _ = api
    rel = _validar(cliente, _csv("id_sku;nome\nabc;Um\nABC;Dois\n")).json()
    assert rel["resumo"]["validas"] == 1 and "código repetido" in rel["erros"][0]["motivos"][0]


def test_existencia_ignora_maiusculas_e_espacos_nas_pontas(api):
    cliente, banco, _ = api
    _item(banco, " ab-1 ", nome="Gravado com espaços", peso=1.0, por=None)
    rel = _validar(cliente, _csv("id_sku;nome\nAB-1;Mesmo item\n")).json()
    assert rel["resumo"]["existentes"] == 1 and rel["resumo"]["novos_sem_peso"] == 0


def test_o_relatorio_nao_traz_o_conteudo_das_celulas_nos_motivos(api):
    cliente, _, _ = api
    rel = _validar(cliente, _csv("id_sku;nome;peso_kg\n1;Produto Secreto;12 quilos de abóbora\n")).json()
    assert "Produto Secreto" not in str(rel["erros"]) and "abóbora" not in str(rel["erros"])


# ----------------------------------------------------------------------------------------------------------
# Importação: confirmar
# ----------------------------------------------------------------------------------------------------------
ARQUIVO = "id_sku;nome;peso_kg;fonte;confianca\n10;Novo A;1,5;;\n11;Novo B;;;\n12;Existente da carga;9;minha fonte;baixa\n13;Existente editado;9;;\n14;Existente sem peso;4;;\n"


def _preparar_existentes(banco):
    _item(banco, "12", nome="Antigo 12", peso=2.0, fonte="nome", confianca="alta", por="carga inicial (script)")
    _item(banco, "13", nome="Antigo 13", peso=2.0, fonte="manual", confianca="alta", por=OUTRO)
    _item(banco, "14", nome="Antigo 14", peso=None, por=OUTRO)  # sem peso: nada de peso foi editado, pode receber o peso


def test_padrao_cria_os_novos_ignora_os_existentes_e_registra_quem_importou(api):
    cliente, banco, _ = api
    _preparar_existentes(banco)
    r = _confirmar(cliente, _csv(ARQUIVO))
    assert r.status_code == 200
    assert r.json() == {"novos": 1, "novos_sem_peso": 1, "atualizados": 0, "preservados": 0, "ja_existentes_ignorados": 3, "sem_peso_ignorados": 0,
                        "importados": 2, "invalidos": 0}
    novo = _linha(banco, "10")
    assert (novo["nome"], novo["peso_kg"], novo["fonte"], novo["confianca"], novo["atualizado_por"]) == ("Novo A", 1.5, "importação pelo site", "media", OPERADOR)
    sem_peso = _linha(banco, "11")
    assert sem_peso["peso_kg"] is None and sem_peso["confianca"] is None and sem_peso["atualizado_por"] == OPERADOR
    assert _linha(banco, "12")["nome"] == "Antigo 12" and _linha(banco, "12")["peso_kg"] == 2.0  # existentes intactos


def test_atualizar_existentes_nunca_sobrescreve_peso_editado_por_operador(api):
    cliente, banco, _ = api
    _preparar_existentes(banco)
    r = _confirmar(cliente, _csv(ARQUIVO), atualizar_existentes=True)
    assert r.json()["atualizados"] == 2 and r.json()["preservados"] == 1 and r.json()["ja_existentes_ignorados"] == 0
    carga = _linha(banco, "12")  # da carga inicial: atualizado
    assert (carga["nome"], carga["peso_kg"], carga["fonte"], carga["confianca"], carga["atualizado_por"]) == ("Existente da carga", 9.0, "minha fonte", "baixa", OPERADOR)
    editado = _linha(banco, "13")  # peso editado por operador na tela: preservado
    assert (editado["nome"], editado["peso_kg"], editado["atualizado_por"]) == ("Antigo 13", 2.0, OUTRO)
    sem_peso = _linha(banco, "14")  # sem peso: recebe o peso (fonte e confiança padrão)
    assert (sem_peso["peso_kg"], sem_peso["fonte"], sem_peso["confianca"]) == (4.0, "importação pelo site", "media")


def test_atualizar_so_o_nome_quando_a_linha_nao_tem_peso_e_nunca_apaga_o_peso_existente(api):
    cliente, banco, _ = api
    _item(banco, "20", nome="Antigo", peso=3.0, por="carga inicial (script)")
    r = _confirmar(cliente, _csv("id_sku;nome;peso_kg\n20;Nome novo;\n"), atualizar_existentes=True, incluir_sem_peso=True)
    assert r.json()["atualizados"] == 1
    assert _linha(banco, "20")["nome"] == "Nome novo" and _linha(banco, "20")["peso_kg"] == 3.0


@pytest.mark.parametrize("incluir, esperado_sem_peso, ignorados", [(True, True, 0), (False, False, 1)])
def test_incluir_ou_nao_os_itens_sem_peso(api, incluir, esperado_sem_peso, ignorados):
    cliente, banco, _ = api
    r = _confirmar(cliente, _csv("id_sku;nome;peso_kg\n30;Com peso;1\n31;Sem peso;\n"), incluir_sem_peso=incluir)
    assert (_linha(banco, "31") is not None) is esperado_sem_peso and _linha(banco, "30") is not None
    assert r.json()["sem_peso_ignorados"] == ignorados


def test_sem_informar_as_opcoes_os_padroes_sao_incluir_sem_peso_e_nao_atualizar(api):
    cliente, banco, _ = api
    _item(banco, "40", nome="Antigo", peso=1.0, por="carga inicial (script)")
    r = _confirmar(cliente, _csv("id_sku;nome;peso_kg\n40;Mudou;5\n41;Sem peso;\n"))
    assert _linha(banco, "40")["nome"] == "Antigo" and _linha(banco, "41") is not None and r.json()["ja_existentes_ignorados"] == 1


def test_fonte_vazia_vira_importacao_pelo_site_e_confianca_vazia_vira_media(api):
    cliente, banco, _ = api
    _confirmar(cliente, _csv("id_sku;nome;peso_kg;fonte;confianca\n50;A;1;;\n51;B;2;balança;baixa\n"))
    assert (_linha(banco, "50")["fonte"], _linha(banco, "50")["confianca"]) == ("importação pelo site", "media")
    assert (_linha(banco, "51")["fonte"], _linha(banco, "51")["confianca"]) == ("balança", "baixa")


def test_confirmacao_revalida_tudo_e_grava_so_as_validas(api):
    cliente, banco, _ = api
    texto = "id_sku;nome;peso_kg\n60;Boa;1\n;Sem código;1\n61;Peso ruim;xx\n60;Repetida;3\n"
    r = _confirmar(cliente, _csv(texto))
    assert r.status_code == 200 and r.json()["novos"] == 1 and r.json()["invalidos"] == 3
    assert [x[0] for x in banco.db.execute("SELECT id_sku FROM item_pesos").fetchall()] == ["60"]


def test_confirmacao_usa_o_estado_do_banco_de_agora_nao_o_do_relatorio(api):
    cliente, banco, _ = api
    arquivo = _csv("id_sku;nome;peso_kg\n70;Novo;1\n")
    assert _validar(cliente, arquivo).json()["resumo"]["novos_com_peso"] == 1
    _item(banco, "70", nome="Criado no meio do caminho", peso=8.0, por=OUTRO)  # alguém criou antes de o operador confirmar
    r = _confirmar(cliente, arquivo, atualizar_existentes=True)
    assert r.json()["novos"] == 0 and r.json()["preservados"] == 1 and _total(banco) == 1
    assert _linha(banco, "70")["nome"] == "Criado no meio do caminho"


def test_arquivo_sem_nenhuma_linha_valida_nao_importa_nada(api):
    cliente, banco, _ = api
    r = _confirmar(cliente, _csv("id_sku;nome;peso_kg\n;sem código;1\n"))
    assert r.status_code == 422 and r.json()["detail"] == "Não há itens válidos para importar neste arquivo." and _total(banco) == 0


def test_falha_no_meio_desfaz_toda_a_transacao(banco):
    class ConexaoQueFalha:
        """Delega para o SQLite, mas estoura na atualização (depois de os novos já terem sido gravados)."""

        def __init__(self, base):
            self.base = base

        def __getattr__(self, nome):
            return getattr(self.base, nome)

        async def executemany(self, sql, linhas):
            if sql.startswith("UPDATE"):
                raise RuntimeError("falha simulada")
            await self.base.executemany(sql, linhas)

    _item(banco, "80", nome="Existente", peso=1.0, por="carga inicial (script)")
    lote = imp.ler_arquivo(b"id_sku;nome;peso_kg\n81;Novo;1\n80;Existente mudou;5\n", "x.csv")
    validas, erros = imp.validar_linhas(lote)
    with pytest.raises(RuntimeError):
        asyncio.run(imp.importar(ConexaoQueFalha(banco), validas, True, True, OPERADOR))
    assert _linha(banco, "81") is None and _linha(banco, "80")["nome"] == "Existente" and _total(banco) == 1
    # e sem a falha o mesmo arquivo grava os dois
    asyncio.run(imp.importar(banco, validas, True, True, OPERADOR))
    assert _linha(banco, "81") is not None and _linha(banco, "80")["nome"] == "Existente mudou"


# ----------------------------------------------------------------------------------------------------------
# Importação: arquivo com problema e conexão com o banco
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("nome, conteudo, trecho", [
    ("a.txt", b"id_sku;nome", "Formato de arquivo inválido"),
    ("a.xls", b"x", ".xls antigas"),
    ("a.csv", b"", "arquivo está vazio"),
    ("a.xlsx", b"isto nao e um xlsx", "Não consegui ler a planilha"),
    ("a.csv", b"coluna1;coluna2\n1;2\n", "Faltam colunas obrigatórias no cabeçalho: código (id_sku), nome"),
    ("a.csv", b"id_sku;peso\n1;2\n", "Faltam colunas obrigatórias no cabeçalho: nome"),
])
def test_arquivo_corrompido_ou_no_formato_errado_da_erro_claro_sem_detalhe_tecnico(api, nome, conteudo, trecho):
    cliente, _, _ = api
    for rota in (_validar, _confirmar):
        r = rota(cliente, conteudo, nome)
        assert r.status_code == 400 and trecho in r.json()["detail"]
        assert "Traceback" not in r.text and "Error" not in r.json()["detail"]


def test_arquivo_grande_demais_e_recusado(api, monkeypatch):
    cliente, _, _ = api
    monkeypatch.setattr(imp, "MAX_BYTES", 100)
    r = _validar(cliente, _csv("id_sku;nome\n" + "1;Item\n" * 50))
    assert r.status_code == 400 and "grande demais (máximo de 5 MB)" in r.json()["detail"]


def test_mais_linhas_que_o_limite_e_recusado(api, monkeypatch):
    cliente, _, _ = api
    assert imp.MAX_BYTES == 5 * 1024 * 1024 and imp.MAX_LINHAS == 20000
    monkeypatch.setattr(imp, "MAX_LINHAS", 3)
    r = _validar(cliente, _csv("id_sku;nome\n1;A\n2;B\n3;C\n4;D\n"))
    assert r.status_code == 400 and "mais de 3 linhas" in r.json()["detail"]


def test_celula_gigante_no_csv_da_mensagem_fixa(api):
    cliente, _, _ = api
    r = _validar(cliente, ("id_sku;nome\n1;" + "x" * 200000 + "\n").encode())
    assert r.status_code == 400 and "Não consegui ler o CSV" in r.json()["detail"]


def test_o_banco_so_e_consultado_quando_precisa(api):
    cliente, banco, chamadas = api
    _validar(cliente, b"isto nao e um csv de itens")  # arquivo ruim: nem abre conexão
    _validar(cliente, _csv("id_sku;nome;peso_kg\n;sem código;1\n"))  # nenhuma linha válida: nem abre conexão
    assert chamadas["pool"] == 0
    _validar(cliente, _csv("id_sku;nome\n1;Item\n"))
    assert chamadas["pool"] == 1
    _confirmar(cliente, b"isto nao e um csv de itens")
    assert chamadas["pool"] == 1


def test_rotas_novas_exigem_login():
    main.app.dependency_overrides.clear()
    cliente = TestClient(main.app)
    arquivo = {"file": ("a.csv", b"id_sku;nome\n1;x\n", "text/csv")}
    assert cliente.get("/api/item-pesos/modelo").status_code == 401
    assert cliente.post("/api/item-pesos/importar/validar", files=arquivo).status_code == 401
    assert cliente.post("/api/item-pesos/importar/confirmar", files=arquivo).status_code == 401


def test_sem_tabela_nova_e_sem_migration():
    import re
    from pathlib import Path
    fonte = Path(imp.__file__).read_text(encoding="utf-8") + Path(item_pesos.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\b(CREATE TABLE|DROP|TRUNCATE|ALTER TABLE)\b", fonte.upper())
    assert not list(Path(item_pesos.__file__).parent.joinpath("migrations", "versions").glob("0012*"))  # nenhuma migration nova
