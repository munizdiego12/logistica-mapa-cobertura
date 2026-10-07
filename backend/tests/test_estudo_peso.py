"""Testes do estudo de viabilidade do peso dos pedidos (scripts/estudo_peso.py). Só dados sintéticos: nada de data/peso."""
import importlib.util
import re
import subprocess
from pathlib import Path

import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("estudo_peso", RAIZ / "scripts" / "estudo_peso.py")
ep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ep)


# ----------------------------------------------------------------------------------------------------------
# Extração do peso
# ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("nome, peso, confianca", [
    ("Açúcar 1kg", 1.0, "alta"),
    ("Arroz 5kg", 5.0, "alta"),
    ("Lã de Aço 45g", 0.045, "alta"),
    ("Maionese 2x500g", 1.0, "baixa"),
    ("Óleo 900ml", 0.9, "alta"),
])
def test_exemplos_do_enunciado_com_peso(nome, peso, confianca):
    r = ep.extrair_peso(nome)
    assert r.peso_kg == pytest.approx(peso) and r.confianca == confianca


@pytest.mark.parametrize("nome, tag", [("Ovo 20 un", "ovos"), ("Papel Higiênico 24 rolos", "rolos")])
def test_exemplos_do_enunciado_sem_peso_marcam_o_risco(nome, tag):
    r = ep.extrair_peso(nome)
    assert r.peso_kg is None and r.confianca is None
    assert tag in r.tags_risco and "unidades (un)" in r.tags_risco


def test_multiplicador_em_varios_formatos_tem_confianca_baixa():
    casos = {
        "Maionese 2x500g": 1.0, "Refrigerante 12 x 1L": 12.0, "Creme Dental 4x90g": 0.36, "Leite Fermentado 6x75g": 0.45,
        "Detergente 500g x 2": 1.0, "Suco 1L x 12": 12.0, "Água 2 X 1 kg": 2.0, "Suco 3x1,5L": 4.5,
    }
    for nome, esperado in casos.items():
        r = ep.extrair_peso(nome)
        assert r.peso_kg == pytest.approx(esperado), nome
        assert r.confianca == "baixa" and "multiplicador" in r.motivos, nome


def test_decimais_e_separador_de_milhar_dependem_da_unidade():
    assert ep.extrair_peso("Chá 1,5L").peso_kg == pytest.approx(1.5)
    assert ep.extrair_peso("Biscoito 35,6g").peso_kg == pytest.approx(0.0356)
    assert ep.extrair_peso("Arroz 0,5kg").peso_kg == pytest.approx(0.5)
    assert ep.extrair_peso("Iogurte 1,150g").peso_kg == pytest.approx(1.15)  # em g, vírgula + 3 dígitos = milhar
    assert ep.extrair_peso("Caldo 1,010g").peso_kg == pytest.approx(1.01)
    assert ep.extrair_peso("Água 1.000ml").peso_kg == pytest.approx(1.0)
    assert ep.extrair_peso("Presunto 1,150kg").peso_kg == pytest.approx(1.15)  # em kg, é decimal
    assert ep.extrair_peso("Adoçante 0,06g").peso_kg == pytest.approx(0.00006)


def test_conversao_de_unidades_com_densidade_1():
    assert ep.extrair_peso("Leite 1L").peso_kg == 1.0
    assert ep.extrair_peso("Leite 200ml").peso_kg == pytest.approx(0.2)
    assert ep.extrair_peso("Suco 2 Litros").peso_kg == 2.0
    assert ep.extrair_peso("Farinha 500 gramas").peso_kg == pytest.approx(0.5)
    assert ep.extrair_peso("Vitamina 500mg").peso_kg == pytest.approx(0.0005)
    assert ep.extrair_peso("ARROZ 5KG").peso_kg == 5.0  # sem diferenciar maiúsculas


def test_dimensoes_contagens_e_nome_vazio_nao_viram_peso():
    for nome in ("Folha de Alumínio Pratsy 0,45x7,5m", "Pano para Pia 32x40cm 3 un", "Filtro de Papel 30 un",
                 "Saboneteira Plasvale Ref:531 un", "Alface Americana un", "", None, "Lata 1 lata"):
        assert ep.extrair_peso(nome).peso_kg is None, nome
    assert "só dimensões" in ep.extrair_peso("Folha de Alumínio 0,45x7,5m").tags_risco
    assert ep.extrair_peso("Lata 1 lata 500g").peso_kg == pytest.approx(0.5)  # "1 lata" não vira "1 l"


def test_contagem_kit_e_varias_medidas_dao_confianca_baixa():
    r = ep.extrair_peso("Kinder Bueno Chocolate ao Leite 2 unis 43g")
    assert r.peso_kg == pytest.approx(0.043) and r.confianca == "baixa" and "contagem de unidades" in r.motivos
    assert ep.extrair_peso("Leve 3 Pague 2 Sabão 200g").confianca == "baixa"
    assert ep.extrair_peso("Kit Shampoo 350ml e Condicionador 200ml").confianca == "baixa"
    r = ep.extrair_peso("Bebida Láctea Whey Cookies 23g Proteína 250ml")  # com várias medidas, o conteúdo é a maior
    assert r.peso_kg == pytest.approx(0.25) and r.confianca == "baixa" and "várias medidas" in r.motivos
    assert ep.extrair_peso("Limpador Cif LV 450ml PG 360ml").peso_kg == pytest.approx(0.45)


def test_nomes_de_marca_e_palavras_comuns_nao_viram_ambiguidade():
    assert ep.extrair_peso("Chocolate Kit Kat Nestlé 41,5g").confianca == "alta"
    assert ep.extrair_peso("Creme de Leite Damare Leve 200g").confianca == "alta"
    assert ep.extrair_peso("Bombom Garoto Sortido 220g").confianca == "alta"


def test_volume_de_capacidade_nao_vira_peso():
    for nome in ("Saco de Lixo Bulnez Reforçado 200L 15 un", "Saco para Lixo Embalixo 50L 50un", "Copo Descartável 180ml 100 un"):
        r = ep.extrair_peso(nome)
        assert r.peso_kg is None and "capacidade (ml/L)" in r.tags_risco, nome
    assert ep.extrair_peso("Água Mineral 200ml").peso_kg == pytest.approx(0.2)  # a água não é "copo"


def test_peso_implausivel_e_descartado_mas_pesos_grandes_reais_ficam():
    assert ep.extrair_peso("Farinha de Trigo 25kg").peso_kg == 25.0
    r = ep.extrair_peso("Ração 50kg")
    assert r.peso_kg is None and "medida implausível" in r.tags_risco


# ----------------------------------------------------------------------------------------------------------
# Cobertura, riscos e pedidos (dados sintéticos)
# ----------------------------------------------------------------------------------------------------------
def _skus():
    return pd.DataFrame({
        "id_sku": ["1", "2", "3", "4", "5"],
        "nome": ["Açúcar 1kg", "Maionese 2x500g", "Ovo 20 un", "Papel Higiênico 24 rolos", "Arroz 5kg"],
        "ref": ["r1", "r2", "r3", "r4", "r5"],
        "categorias": ["/2/18/", "/2/18/", "/7/368/", "/7/368/", "/2/19/"],
        "unidades": [100.0, 20.0, 30.0, 10.0, 40.0],
        "pedidos": [3.0, 2.0, 2.0, 1.0, 2.0],
    })


def _itens():
    # o1 completo (SKUs 1 e 5); o2 incompleto (1 e 3); o3 incompleto (2 e 4); o4 só SKU 2 (baixa)
    return pd.DataFrame({
        "order_id": ["o1", "o1", "o2", "o2", "o3", "o3", "o4"],
        "seller_name": ["Loja A", "Loja A", "Loja A", "Loja A", "Loja B", "Loja B", "Loja B"],
        "id_sku": ["1", "5", "1", "3", "2", "4", "2"],
        "quantity_sku": [10.0, 2.0, 5.0, 4.0, 3.0, 1.0, 6.0],
    })


def _tabela():
    return ep.montar_tabela_skus(_skus())


def test_cobertura_por_sku_unidades_e_linhas():
    c = ep.cobertura(_tabela(), _itens())
    assert c["skus"] == {"total": 5.0, "alta": 2.0, "baixa": 1.0, "sem": 2.0}
    assert c["unidades"] == {"total": 200.0, "alta": 140.0, "baixa": 20.0, "sem": 40.0}  # por UNIDADES, não por SKU
    assert c["linhas"] == {"total": 7.0, "alta": 3.0, "baixa": 2.0, "sem": 2.0}


def test_top_sem_peso_ordena_por_unidades_e_limita():
    topo = ep.top_sem_peso(_tabela(), 1)
    assert list(topo["id_sku"]) == ["3"]  # Ovo (30 un.) antes de Papel Higiênico (10 un.)
    assert list(ep.top_sem_peso(_tabela(), 100)["id_sku"]) == ["3", "4"]


def test_riscos_por_tag_e_por_categoria():
    r = ep.riscos(_tabela())
    assert r["total_unidades"] == 40.0
    assert r["por_tag"]["ovos"] == {"skus": 1, "unidades": 30.0}
    assert r["por_tag"]["rolos"] == {"skus": 1, "unidades": 10.0}
    assert r["por_tag"]["unidades (un)"]["skus"] == 2
    assert r["por_topo"].index[0] == "7" and r["por_topo"].iloc[0]["sum"] == 40.0


def test_peso_por_pedido_completo_e_incompleto():
    p = ep.pesos_pedidos(_itens(), _tabela()).set_index("order_id")
    assert p.loc["o1", "peso_kg"] == pytest.approx(10 * 1.0 + 2 * 5.0) and bool(p.loc["o1", "completo"])
    assert p.loc["o2", "peso_kg"] == pytest.approx(5.0)  # só o açúcar: é um piso
    assert not p.loc["o2", "completo"] and p.loc["o2", "itens_sem_peso"] == 1 and p.loc["o2", "unidades_sem_peso"] == 4
    assert p.loc["o3", "peso_kg"] == pytest.approx(3 * 1.0) and not p.loc["o3", "completo"]
    assert p.loc["o4", "peso_kg"] == pytest.approx(6.0) and bool(p.loc["o4", "completo"])  # peso de confiança baixa conta


def test_peso_por_pedido_so_com_confianca_alta():
    p = ep.pesos_pedidos(_itens(), _tabela(), so_alta=True).set_index("order_id")
    assert bool(p.loc["o1", "completo"])
    assert not p.loc["o4", "completo"] and p.loc["o4", "peso_kg"] == 0.0  # a maionese 2x500g é de confiança baixa


def test_decis_e_por_loja():
    d = ep.decis(pd.Series(range(1, 101)))
    assert d["min"] == 1 and d["max"] == 100 and d["P50"] == pytest.approx(50.5) and list(d)[1] == "P10" and len(d) == 11
    assert ep.decis(pd.Series([], dtype=float)) == {}
    lojas = ep.por_loja(ep.pesos_pedidos(_itens(), _tabela())).set_index("loja")
    assert lojas.loc["Loja A", "pedidos"] == 2 and lojas.loc["Loja A", "completos"] == 1 and lojas.loc["Loja A", "pct_completos"] == 50.0
    assert lojas.loc["Loja A", "peso_mediano_kg"] == pytest.approx(20.0)
    assert lojas.loc["Loja B", "completos"] == 1 and lojas.loc["Loja B", "peso_total_completos_kg"] == pytest.approx(6.0)


def test_simulacao_de_correcao_manual():
    sim = ep.simular_correcao(_itens(), _tabela(), "unidades", ns=(0, 1, 2, None))
    # fila por unidades: [SKU 3 (30), SKU 4 (10)]; completos hoje: o1 e o4
    assert [(l["n"], l["completos"]) for l in sim] == [(0, 2), (1, 3), (2, 4), (2, 4)]
    assert sim[-1]["pct"] == 100.0
    assert ep.skus_para_atingir(_itens(), _tabela(), 0.5) == 0  # 50% já estão completos
    assert ep.skus_para_atingir(_itens(), _tabela(), 0.75) == 1
    assert ep.skus_para_atingir(_itens(), _tabela(), 1.0) == 2


# ----------------------------------------------------------------------------------------------------------
# CSV, proteção do git, execução completa
# ----------------------------------------------------------------------------------------------------------
def test_csv_inicial_tem_as_colunas_pedidas_ordenado_por_unidades(tmp_path):
    destino = tmp_path / "item_pesos_inicial.csv"
    ep.escrever_csv(_tabela(), destino)
    bruto = destino.read_bytes()
    assert bruto.startswith(b"\xef\xbb\xbf")  # UTF-8 com BOM, para o Excel
    d = pd.read_csv(destino, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    assert list(d.columns) == ["id_sku", "reference_code", "nome", "peso_kg_sugerido", "fonte", "confianca", "unidades_vendidas"]
    assert list(d["unidades_vendidas"]) == ["100", "40", "30", "20", "10"]  # decrescente
    linhas = d.set_index("id_sku")
    assert linhas.loc["1", "reference_code"] == "r1"
    assert (linhas.loc["1", "peso_kg_sugerido"], linhas.loc["1", "fonte"], linhas.loc["1", "confianca"]) == ("1", "nome", "alta")
    assert (linhas.loc["2", "peso_kg_sugerido"], linhas.loc["2", "confianca"]) == ("1", "baixa")
    assert (linhas.loc["3", "peso_kg_sugerido"], linhas.loc["3", "fonte"], linhas.loc["3", "confianca"]) == ("", "", "")  # sem medida: tudo em branco


def test_csv_para_excel_usa_ponto_e_virgula_e_virgula_decimal(tmp_path):
    destino = tmp_path / "excel.csv"
    ep.escrever_csv(_tabela(), destino, excel=True)
    texto = destino.read_text(encoding="utf-8-sig")
    assert texto.splitlines()[0] == "id_sku;reference_code;nome;peso_kg_sugerido;fonte;confianca;unidades_vendidas"
    assert "Arroz 5kg;5;nome;alta;40" in texto
    tab = ep.montar_tabela_skus(_skus().assign(nome="Biscoito 35,6g"))  # 0,0356 kg
    ep.escrever_csv(tab.head(1), destino, excel=True)
    assert ";0,0356;" in destino.read_text(encoding="utf-8-sig")


def test_protecao_do_git_para_dados_do_bigquery():
    caminhos = (RAIZ / "data" / "peso" / "skus.csv", RAIZ / "data" / "peso" / "item_pesos_inicial.csv")
    for caminho in caminhos:
        assert ep.esta_protegido_do_git(caminho)  # data/peso/ está no .gitignore
    assert ep.esta_protegido_do_git(Path("/tmp/fora_do_repositorio/x.csv"))
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git indisponível")
    assert not ep.esta_protegido_do_git(RAIZ / "backend" / "nao_pode.csv")  # dentro do repo e não ignorado


def test_data_peso_esta_no_gitignore_e_nenhum_arquivo_dela_e_versionado():
    assert "data/peso/" in (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    try:
        rastreados = subprocess.run(["git", "ls-files", "data/peso"], cwd=RAIZ, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git indisponível")
    assert rastreados.strip() == ""


def test_script_nao_usa_rede_nem_banco():
    fonte = (RAIZ / "scripts" / "estudo_peso.py").read_text(encoding="utf-8")
    for proibido in ("urllib", "requests", "httpx", "socket", "psycopg2", "asyncpg", "sqlite3", "DATABASE_URL", "import database"):
        assert proibido not in fonte, proibido


def _gravar_csvs(pasta):
    _skus().to_csv(pasta / "skus.csv", index=False, encoding="utf-8")
    _itens().to_csv(pasta / "itens_pedidos.csv", index=False, encoding="utf-8")


def test_execucao_completa_imprime_o_relatorio_e_grava_o_csv(tmp_path, capsys):
    _gravar_csvs(tmp_path)
    saida = tmp_path / "saida" / "item_pesos_inicial.csv"
    ep.main(["--pasta", str(tmp_path), "--saida", str(saida), "--top", "10"])
    texto = capsys.readouterr().out
    for secao in ("1. DADOS", "2. COBERTURA DO PESO", "3. OS 10 SKUs MAIS VENDIDOS SEM PESO", "4. PESO ESTIMADO POR PEDIDO",
                  "QUANTO A CONFERÊNCIA MANUAL MELHORA ISSO", "Por loja", "5. LIMITES DESTE ESTUDO"):
        assert secao in texto, secao
    assert "Por UNIDADES vendidas" in texto and "ovos" in texto and "rolos" in texto
    assert "SKUs cuja soma de quantity_sku difere de 'unidades' do skus.csv: 5" in texto  # os dados de teste não batem de propósito
    assert re.search(r"Pedidos completos \(pesos de confiança alta \+ baixa\): 2 de 4 \(50,0%\)", texto)
    assert saida.exists()


def test_conferencia_entre_os_dois_csvs_aponta_divergencias_e_skus_fora_do_catalogo():
    consistentes = _skus().assign(unidades=[15.0, 9.0, 4.0, 1.0, 2.0])  # soma de quantity_sku de cada SKU em _itens()
    tabela = ep.montar_tabela_skus(consistentes)
    texto = ep.gerar_relatorio(consistentes, _itens(), tabela)
    assert "difere de 'unidades' do skus.csv: 0 | linhas de itens com SKU fora do catálogo: 0" in texto

    com_intruso = pd.concat([_itens(), pd.DataFrame({"order_id": ["o9"], "seller_name": ["Loja A"], "id_sku": ["999"], "quantity_sku": [1.0]})])
    texto = ep.gerar_relatorio(consistentes, com_intruso, tabela)
    assert "linhas de itens com SKU fora do catálogo: 1" in texto


def test_execucao_recusa_gravar_o_csv_dentro_do_repositorio_sem_ignorar(tmp_path):
    _gravar_csvs(tmp_path)
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git indisponível")
    with pytest.raises(SystemExit) as erro:
        ep.main(["--pasta", str(tmp_path), "--saida", str(RAIZ / "backend" / "pesos_por_engano.csv")])
    assert "público" in str(erro.value)
    assert not (RAIZ / "backend" / "pesos_por_engano.csv").exists()


def test_colunas_faltando_dao_erro_claro(tmp_path):
    _skus().drop(columns=["nome"]).to_csv(tmp_path / "skus.csv", index=False)
    _itens().to_csv(tmp_path / "itens_pedidos.csv", index=False)
    with pytest.raises(ValueError, match="faltam as colunas"):
        ep.carregar(tmp_path)
