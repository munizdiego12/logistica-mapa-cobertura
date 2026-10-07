"""
Estudo de viabilidade do peso dos pedidos, a partir de dois CSVs do BigQuery. Só lê arquivos locais:
sem rede, sem banco, sem integrar nada.

Entradas (em data/peso/, que está no .gitignore: o repositório é público e são dados de pedidos):
    skus.csv           id_sku, nome, ref, categorias, unidades, pedidos
    itens_pedidos.csv  order_id, seller_name, id_sku, quantity_sku

Saídas:
    relatório em texto (stdout)
    data/peso/item_pesos_inicial.csv  (peso sugerido por SKU, para revisão manual; também fora do git)

Uso:
    python scripts/estudo_peso.py
    python scripts/estudo_peso.py --pasta data/peso --saida data/peso/item_pesos_inicial.csv --top 100
    python scripts/estudo_peso.py --excel      # CSV com ';' e vírgula decimal, para abrir direto no Excel em português

Regras da extração do peso a partir do nome:
    kg, g, mg, ml, L (e variações) -> kg; ml e L viram kg com densidade 1 (aproximação).
    "2x500g", "12 x 1L", "500g x 2" -> multiplicador: peso do SKU = quantidade x medida (confiança baixa).
    Dimensões (cm, m), contagens (un, rolos, folhas...) e kits nunca viram peso sozinhos.
"""
import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
PASTA_PADRAO = RAIZ / "data" / "peso"
SAIDA_PADRAO = PASTA_PADRAO / "item_pesos_inicial.csv"

COLUNAS_SKUS = ["id_sku", "nome", "ref", "categorias", "unidades", "pedidos"]
COLUNAS_ITENS = ["order_id", "seller_name", "id_sku", "quantity_sku"]
COLUNAS_CSV_SAIDA = ["id_sku", "reference_code", "nome", "peso_kg_sugerido", "fonte", "confianca", "unidades_vendidas"]

# ----------------------------------------------------------------------------------------------------------
# Extração do peso a partir do nome
# ----------------------------------------------------------------------------------------------------------
_NUM = r"(\d+(?:[.,]\d+)*)"  # 500 | 1,5 | 0.45 | 1,150 | 1.000 (a leitura do separador depende da unidade)
_UNID = r"(kgs?|g|grs?|gramas?|mg|ml|l|lts?|litros?)"
_FIM = r"(?![A-Za-zÀ-ÿ0-9])"  # a unidade não pode ser seguida de letra/número ("1 lata" não é "1 l")
_INICIO = r"(?<![\w.,])"  # o número não pode começar no meio de outro ("0,45x7,5m": o 45 não conta)

_MULT_ANTES = re.compile(rf"{_INICIO}(\d{{1,3}})\s*[x×]\s*{_NUM}\s*{_UNID}{_FIM}", re.IGNORECASE)  # 2x500g, 12 x 1L
_MULT_DEPOIS = re.compile(rf"{_INICIO}{_NUM}\s*{_UNID}\s*[x×]\s*(\d{{1,3}}){_FIM}", re.IGNORECASE)  # 500g x 2
_MEDIDA = re.compile(rf"{_INICIO}{_NUM}\s*{_UNID}{_FIM}", re.IGNORECASE)

_CONTAGEM = re.compile(
    rf"{_INICIO}(\d{{1,4}})\s*(un|und|unid|unids|unidades?|unis|uni|rolos?|folhas?|pares?|par|discos?|sach[êe]s?|"
    r"c[áa]psulas?|tabletes?|pilhas?|l[âa]minas?|pe[çc]as?|p[çc]s?|doses?|potes?|pacotes?|latas?)(?![A-Za-zÀ-ÿ])",
    re.IGNORECASE,
)
_UN_SOLTO = re.compile(r"(?<![\w])(un|und|unid|unidade)(?![\w])", re.IGNORECASE)
_DIMENSAO = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?\s*(?:cm|mm|m)(?![A-Za-zÀ-ÿ0-9])|\d\s*[x×]\s*\d", re.IGNORECASE)
_AMBIGUO = re.compile(r"\bkit\b(?!\s*kat)|\bcombo\b|\bleve\s*\d+\s*pague\s*\d+|\bpague\s*\d+|\bcx\b|\bcaixa\s+com\b|\bc/\s*\d+", re.IGNORECASE)
# Volume que é CAPACIDADE da embalagem, não conteúdo (saco de lixo 100L, copo descartável 180ml).
_CAPACIDADE = re.compile(r"\bsacos?\s+(?:\w+\s+){0,2}lixo\b|\bcopos?\b", re.IGNORECASE)
_OVOS = re.compile(r"\bovos?\b", re.IGNORECASE)
_ROLOS = re.compile(r"\brolos?\b|papel\s+higi|papel\s+toalha|toalha\s+de\s+papel", re.IGNORECASE)
_FOLHAS = re.compile(r"\bfolhas?\b", re.IGNORECASE)
_PARES = re.compile(r"\bpares?\b|\bmeias?\b", re.IGNORECASE)

_PARA_KG = {
    "kg": 1.0, "kgs": 1.0, "g": 0.001, "gr": 0.001, "grs": 0.001, "grama": 0.001, "gramas": 0.001, "mg": 1e-6,
    "ml": 0.001, "l": 1.0, "lt": 1.0, "lts": 1.0, "litro": 1.0, "litros": 1.0,  # ml/L: densidade 1
}
PESO_MAXIMO_PLAUSIVEL_KG = 40.0  # acima disso é quase certo que a medida é capacidade/dimensão, não peso
_UNIDADES_PEQUENAS = {"g", "gr", "grs", "grama", "gramas", "mg", "ml"}  # "1,150g" = mil cento e cinquenta gramas
_UNIDADES_VOLUME = {"ml", "l", "lt", "lts", "litro", "litros"}


@dataclass
class ResultadoPeso:
    peso_kg: Optional[float]  # peso unitário do SKU; None = sem medida no nome
    confianca: Optional[str]  # "alta" | "baixa" | None (sem peso)
    motivos: tuple = ()  # por que a confiança é baixa
    tags_risco: tuple = field(default_factory=tuple)  # ovos, rolos, unidades (un), folhas, pares, só dimensões, kit/leve-pague


def _numero(texto: str, unidade: str) -> float:
    """
    Lê "1,5", "0.45", "1.000" etc. Em g/ml/mg, um separador seguido de exatamente 3 dígitos é de milhar
    ("1,150g" = 1150 g); em kg/L é decimal ("1,150kg" = 1,15 kg). Em qualquer caso o último separador é o decimal.
    """
    if unidade.lower() in _UNIDADES_PEQUENAS and re.fullmatch(r"[1-9]\d{0,2}(?:[.,]\d{3})+", texto):
        return float(re.sub(r"[.,]", "", texto))
    partes = re.split(r"[.,]", texto)
    if len(partes) == 1:
        return float(partes[0])
    return float("".join(partes[:-1]) + "." + partes[-1])


def _kg(valor: str, unidade: str) -> float:
    return _numero(valor, unidade) * _PARA_KG[unidade.lower()]


def extrair_peso(nome) -> ResultadoPeso:
    """
    Peso unitário do SKU em kg a partir do nome, com a confiança:
      alta  = uma única medida clara em kg/g/ml/L;
      baixa = multiplicador (2x500g), contagem de unidades (50 un), kit/leve-pague ou várias medidas diferentes;
      sem peso (None) = nenhuma medida de peso/volume no nome.
    """
    texto = " ".join(str(nome or "").split())
    sobra = texto

    totais = []  # multiplicadores: quantidade x medida
    for regex, ordem in ((_MULT_ANTES, "antes"), (_MULT_DEPOIS, "depois")):
        for m in regex.finditer(sobra):
            if ordem == "antes":
                quantidade, valor, unidade = int(m.group(1)), m.group(2), m.group(3)
            else:
                valor, unidade, quantidade = m.group(1), m.group(2), int(m.group(3))
            totais.append(quantidade * _kg(valor, unidade))
        sobra = regex.sub(" ", sobra)  # o que já virou multiplicador não é lido de novo como medida solta

    medidas = [(_kg(m.group(1), m.group(2)), m.group(2).lower()) for m in _MEDIDA.finditer(sobra)]
    soltas = [kg for kg, _ in medidas]

    contagens = [int(m.group(1)) for m in _CONTAGEM.finditer(texto)]
    tem_contagem = any(c > 1 for c in contagens)
    ambiguo = bool(_AMBIGUO.search(texto))

    capacidade = bool(_CAPACIDADE.search(texto)) and bool(medidas) and all(u in _UNIDADES_VOLUME for _, u in medidas)

    peso, confianca, motivos = None, None, []
    if capacidade:
        pass  # o ml/L é a capacidade da embalagem: não há peso a extrair do nome
    elif totais:
        peso, confianca = totais[0], "baixa"
        motivos.append("multiplicador")
        if len(totais) > 1 or soltas:
            motivos.append("várias medidas")
    elif soltas:
        peso = max(soltas)  # com várias medidas (23g de proteína e 250ml), o conteúdo é a maior
        if len({round(v, 6) for v in soltas}) > 1:
            motivos.append("várias medidas")
        if tem_contagem:
            motivos.append("contagem de unidades")
        if ambiguo:
            motivos.append("kit/leve-pague")
        confianca = "baixa" if motivos else "alta"
    if peso is not None:
        peso = round(peso, 6)  # tira resíduos de ponto flutuante (0,44999999 -> 0,45)
    implausivel = peso is not None and not 0 < peso <= PESO_MAXIMO_PLAUSIVEL_KG
    if implausivel:  # não sugere um peso quase certamente errado: o SKU volta para a fila "sem peso"
        peso, confianca = None, None
        motivos = []

    tags = []
    if _OVOS.search(texto):
        tags.append("ovos")
    if _ROLOS.search(texto):
        tags.append("rolos")
    if tem_contagem or _UN_SOLTO.search(texto):
        tags.append("unidades (un)")
    if _FOLHAS.search(texto):
        tags.append("folhas")
    if _PARES.search(texto):
        tags.append("pares")
    if peso is None and _DIMENSAO.search(texto):
        tags.append("só dimensões")
    if capacidade:
        tags.append("capacidade (ml/L)")
    if implausivel:
        tags.append("medida implausível")
    if ambiguo:
        tags.append("kit/leve-pague")

    return ResultadoPeso(peso, confianca, tuple(motivos), tuple(tags))


# ----------------------------------------------------------------------------------------------------------
# Carga e cruzamentos
# ----------------------------------------------------------------------------------------------------------
def carregar(pasta: Path) -> tuple:
    """Lê skus.csv e itens_pedidos.csv (UTF-8), confere as colunas e tipa os números."""
    skus = pd.read_csv(pasta / "skus.csv", dtype=str, encoding="utf-8-sig")
    itens = pd.read_csv(pasta / "itens_pedidos.csv", dtype=str, encoding="utf-8-sig")
    for tabela, colunas, nome in ((skus, COLUNAS_SKUS, "skus.csv"), (itens, COLUNAS_ITENS, "itens_pedidos.csv")):
        faltando = [c for c in colunas if c not in tabela.columns]
        if faltando:
            raise ValueError(f"{nome}: faltam as colunas {faltando}")
    skus["id_sku"] = skus["id_sku"].str.strip()
    itens["id_sku"] = itens["id_sku"].str.strip()
    skus["unidades"] = pd.to_numeric(skus["unidades"], errors="coerce").fillna(0)
    skus["pedidos"] = pd.to_numeric(skus["pedidos"], errors="coerce").fillna(0)
    itens["quantity_sku"] = pd.to_numeric(itens["quantity_sku"], errors="coerce").fillna(0)
    return skus, itens


def montar_tabela_skus(skus: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por SKU com o peso extraído, a confiança, os motivos e as tags de risco."""
    resultados = [extrair_peso(n) for n in skus["nome"]]
    tabela = skus.copy()
    tabela["peso_kg"] = [r.peso_kg for r in resultados]
    tabela["confianca"] = [r.confianca for r in resultados]
    tabela["motivos"] = [", ".join(r.motivos) for r in resultados]
    tabela["tags"] = [list(r.tags_risco) for r in resultados]
    return tabela


def cobertura(tabela: pd.DataFrame, itens: pd.DataFrame) -> dict:
    """Cobertura por SKU, por unidades vendidas e por linhas de itens, separando alta e baixa confiança."""
    def partes(mascara_alta, mascara_baixa, mascara_sem, peso):
        total = peso.sum()
        return {
            "total": float(total),
            "alta": float(peso[mascara_alta].sum()), "baixa": float(peso[mascara_baixa].sum()), "sem": float(peso[mascara_sem].sum()),
        }

    alta, baixa, sem = tabela["confianca"] == "alta", tabela["confianca"] == "baixa", tabela["peso_kg"].isna()
    por_sku = partes(alta, baixa, sem, pd.Series(1, index=tabela.index))
    por_unidades = partes(alta, baixa, sem, tabela["unidades"])
    conf = tabela.set_index("id_sku")["confianca"]
    linhas = itens["id_sku"].map(conf)
    por_linhas = {
        "total": float(len(itens)), "alta": float((linhas == "alta").sum()), "baixa": float((linhas == "baixa").sum()),
        "sem": float(linhas.isna().sum()),
    }
    return {"skus": por_sku, "unidades": por_unidades, "linhas": por_linhas}


def top_sem_peso(tabela: pd.DataFrame, n: int = 100) -> pd.DataFrame:
    """Os `n` SKUs mais vendidos (em unidades) sem peso extraível, para correção manual."""
    sem = tabela[tabela["peso_kg"].isna()].sort_values(["unidades", "pedidos"], ascending=False)
    return sem.head(n)


def riscos(tabela: pd.DataFrame) -> dict:
    """Entre os SKUs sem peso: unidades por tag de risco e por categoria (os ids de categoria vêm sem nome)."""
    sem = tabela[tabela["peso_kg"].isna()]
    total_unidades = float(sem["unidades"].sum())
    por_tag = {}
    for tag in ("ovos", "rolos", "unidades (un)", "folhas", "pares", "só dimensões", "capacidade (ml/L)", "medida implausível", "kit/leve-pague"):
        marcados = sem[sem["tags"].map(lambda t, tag=tag: tag in t)]
        por_tag[tag] = {"skus": len(marcados), "unidades": float(marcados["unidades"].sum())}
    sem_tag = sem[sem["tags"].map(len) == 0]
    por_tag["(nenhuma das tags)"] = {"skus": len(sem_tag), "unidades": float(sem_tag["unidades"].sum())}

    topo = sem["categorias"].fillna("").str.strip("/").str.split("/").str[0]
    por_topo = sem.assign(topo=topo).groupby("topo")["unidades"].agg(["sum", "size"]).sort_values("sum", ascending=False)
    por_caminho = sem.groupby("categorias")["unidades"].agg(["sum", "size"]).sort_values("sum", ascending=False)
    return {"total_unidades": total_unidades, "por_tag": por_tag, "por_topo": por_topo.head(8), "por_caminho": por_caminho.head(8)}


def pesos_pedidos(itens: pd.DataFrame, tabela: pd.DataFrame, so_alta: bool = False) -> pd.DataFrame:
    """
    Peso estimado por pedido (soma de quantidade x peso unitário dos itens com peso) e se está completo:
    "completo" quando TODOS os itens têm peso; "incompleto" quando algum não tem (o peso é então só um piso).
    `so_alta` considera apenas pesos de confiança alta.
    """
    unitario = tabela.set_index("id_sku")["peso_kg"].copy()
    if so_alta:
        unitario[tabela.set_index("id_sku")["confianca"] != "alta"] = np.nan
    peso_unit = itens["id_sku"].map(unitario)
    base = itens.assign(peso_item=itens["quantity_sku"] * peso_unit, sem_peso=peso_unit.isna(), unidades_sem_peso=np.where(peso_unit.isna(), itens["quantity_sku"], 0))
    pedidos = base.groupby("order_id").agg(
        loja=("seller_name", "first"), lojas_distintas=("seller_name", "nunique"), itens=("id_sku", "size"),
        unidades=("quantity_sku", "sum"), itens_sem_peso=("sem_peso", "sum"), unidades_sem_peso=("unidades_sem_peso", "sum"),
        peso_kg=("peso_item", "sum"),
    ).reset_index()
    pedidos["completo"] = pedidos["itens_sem_peso"] == 0
    return pedidos


def decis(valores: pd.Series) -> dict:
    """Mínimo, decis (P10..P90) e máximo."""
    v = valores.dropna().to_numpy(dtype=float)
    if len(v) == 0:
        return {}
    out = {"min": float(v.min())}
    out.update({f"P{p}": float(np.percentile(v, p)) for p in range(10, 100, 10)})
    out["max"] = float(v.max())
    return out


def por_loja(pedidos: pd.DataFrame) -> pd.DataFrame:
    """Por loja: pedidos, % completos e estatísticas do peso dos pedidos completos."""
    linhas = []
    for loja, g in pedidos.groupby("loja"):
        completos = g[g["completo"]]
        linhas.append({
            "loja": loja, "pedidos": len(g), "completos": len(completos),
            "pct_completos": 100.0 * len(completos) / len(g),
            "peso_mediano_kg": float(completos["peso_kg"].median()) if len(completos) else np.nan,
            "peso_p90_kg": float(completos["peso_kg"].quantile(0.9)) if len(completos) else np.nan,
            "peso_total_completos_kg": float(completos["peso_kg"].sum()),
        })
    return pd.DataFrame(linhas).sort_values("pedidos", ascending=False).reset_index(drop=True)


def _posicao_maxima_por_pedido(itens: pd.DataFrame, tabela: pd.DataFrame, ordenar_por: str) -> pd.Series:
    """
    Para cada pedido, a maior posição (na fila de correção) entre os seus itens sem peso; -1 se já está completo.
    A fila ordena os SKUs sem peso por `ordenar_por` ("unidades" ou "pedidos"), do maior para o menor.
    """
    desempate = "pedidos" if ordenar_por == "unidades" else "unidades"
    fila = tabela[tabela["peso_kg"].isna()].sort_values([ordenar_por, desempate], ascending=False)
    posicao = {sku: i for i, sku in enumerate(fila["id_sku"])}
    por_item = itens["id_sku"].map(posicao)
    return por_item.groupby(itens["order_id"]).max().fillna(-1)


def simular_correcao(itens: pd.DataFrame, tabela: pd.DataFrame, ordenar_por: str = "unidades", ns=(0, 25, 50, 100, 200, 300, 400, None)) -> list:
    """% de pedidos completos se os N SKUs sem peso da fila (mais vendidos por `ordenar_por`) ganharem peso à mão."""
    maximas = _posicao_maxima_por_pedido(itens, tabela, ordenar_por)
    total, sem_peso = len(maximas), int(tabela["peso_kg"].isna().sum())
    linhas = []
    for n in ns:
        n_efetivo = sem_peso if n is None else min(n, sem_peso)
        completos = int((maximas < n_efetivo).sum())
        linhas.append({"n": n_efetivo, "completos": completos, "pct": 100.0 * completos / total if total else 0.0})
    return linhas


def skus_para_atingir(itens: pd.DataFrame, tabela: pd.DataFrame, meta: float, ordenar_por: str = "unidades") -> int:
    """Menor quantidade de SKUs da fila que precisa ganhar peso para `meta` (0 a 1) dos pedidos ficarem completos."""
    maximas = np.sort(_posicao_maxima_por_pedido(itens, tabela, ordenar_por).to_numpy())
    if len(maximas) == 0:
        return 0
    k = int(np.ceil(meta * len(maximas)))
    return int(maximas[k - 1]) + 1 if maximas[k - 1] >= 0 else 0


def montar_csv_inicial(tabela: pd.DataFrame) -> pd.DataFrame:
    """CSV para revisão manual: ordenado por unidades vendidas (decrescente), peso e confiança em branco quando não extraído."""
    saida = pd.DataFrame({
        "id_sku": tabela["id_sku"], "reference_code": tabela["ref"], "nome": tabela["nome"],
        "peso_kg_sugerido": tabela["peso_kg"].map(lambda v: "" if pd.isna(v) else f"{v:.4f}".rstrip("0").rstrip(".")),
        "fonte": np.where(tabela["peso_kg"].notna(), "nome", ""),
        "confianca": tabela["confianca"].fillna(""),
        "unidades_vendidas": tabela["unidades"].astype(int),
    })
    return saida.sort_values("unidades_vendidas", ascending=False, kind="stable")[COLUNAS_CSV_SAIDA].reset_index(drop=True)


def escrever_csv(tabela: pd.DataFrame, caminho: Path, excel: bool = False) -> pd.DataFrame:
    """
    Grava o CSV inicial em UTF-8 com BOM. Padrão: vírgula como separador de colunas e ponto decimal (para carregar
    no banco depois). Com `excel`: ponto e vírgula e vírgula decimal, porque o Excel em português lê "1.5" como data.
    """
    saida = montar_csv_inicial(tabela)
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    if excel:
        saida = saida.assign(peso_kg_sugerido=saida["peso_kg_sugerido"].str.replace(".", ",", regex=False))
    saida.to_csv(caminho, index=False, encoding="utf-8-sig", sep=";" if excel else ",")
    return saida


def esta_protegido_do_git(caminho: Path) -> bool:
    """True se o caminho está fora do repositório ou é ignorado pelo git (o repositório é público)."""
    try:
        relativo = Path(caminho).resolve().relative_to(RAIZ)
    except ValueError:
        return True
    try:
        resultado = subprocess.run(["git", "check-ignore", "-q", str(relativo)], cwd=RAIZ, capture_output=True)
    except OSError:
        return True  # sem git não há o que versionar por engano
    return resultado.returncode in (0, 128)  # 0 = ignorado; 128 = não é um repositório git


# ----------------------------------------------------------------------------------------------------------
# Relatório
# ----------------------------------------------------------------------------------------------------------
def _n(valor) -> str:
    return f"{int(round(valor)):,}".replace(",", ".")


def _f(valor, casas=1) -> str:
    if valor is None or pd.isna(valor):
        return "-"
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(parte, total) -> str:
    return f"{100.0 * parte / total:.1f}%".replace(".", ",") if total else "-"


def _linha_cobertura(rotulo: str, c: dict, unidade: str) -> list:
    return [
        f"  {rotulo} ({unidade}): total {_n(c['total'])}",
        f"    com peso (alta + baixa): {_n(c['alta'] + c['baixa'])} ({_pct(c['alta'] + c['baixa'], c['total'])})"
        f" | alta: {_n(c['alta'])} ({_pct(c['alta'], c['total'])}) | baixa: {_n(c['baixa'])} ({_pct(c['baixa'], c['total'])})",
        f"    sem medida no nome: {_n(c['sem'])} ({_pct(c['sem'], c['total'])})",
    ]


def _linhas_decis(rotulo: str, d: dict) -> list:
    if not d:
        return [f"  {rotulo}: sem dados"]
    return [f"  {rotulo}: " + " | ".join(f"{k} {_f(v)}" for k, v in d.items())]


def gerar_relatorio(skus: pd.DataFrame, itens: pd.DataFrame, tabela: pd.DataFrame, top: int = 100) -> str:
    L = []
    cob = cobertura(tabela, itens)

    L += ["=" * 100, "ESTUDO DE VIABILIDADE DO PESO DOS PEDIDOS (extraído do nome do SKU)", "=" * 100, ""]
    L += [
        "1. DADOS",
        f"  SKUs: {_n(len(skus))} | linhas de itens: {_n(len(itens))} | pedidos: {_n(itens['order_id'].nunique())} | "
        f"lojas: {itens['seller_name'].nunique()} | unidades vendidas: {_n(skus['unidades'].sum())}",
    ]
    soma_itens = itens.groupby("id_sku")["quantity_sku"].sum()
    comparado = skus.set_index("id_sku")["unidades"].reindex(soma_itens.index)
    divergentes = int(((comparado - soma_itens).abs() > 1e-9).sum() + comparado.isna().sum())
    sem_catalogo = int((~itens["id_sku"].isin(skus["id_sku"])).sum())
    L += [
        f"  Conferência: SKUs cuja soma de quantity_sku difere de 'unidades' do skus.csv: {divergentes} | "
        f"linhas de itens com SKU fora do catálogo: {sem_catalogo} | ids de SKU repetidos no catálogo: {int(skus['id_sku'].duplicated().sum())}",
        "  Regra: kg, g, mg, ml e L (ml/L -> kg com densidade 1); 2x500g, 12 x 1L e 500g x 2 = multiplicador (confiança baixa);",
        "  contagens (un, rolos, folhas), dimensões (cm, m) e kits nunca viram peso sozinhos.",
        "",
        "2. COBERTURA DO PESO",
    ]
    L += _linha_cobertura("Por SKU", cob["skus"], "SKUs")
    L += _linha_cobertura("Por UNIDADES vendidas", cob["unidades"], "unidades")
    L += _linha_cobertura("Por linhas de itens de pedido", cob["linhas"], "linhas")
    L += [""]

    L += [f"3. OS {top} SKUs MAIS VENDIDOS SEM PESO EXTRAÍVEL (para corrigir à mão)", "   # | id_sku | unidades | pedidos | risco | nome"]
    for pos, (_, r) in enumerate(top_sem_peso(tabela, top).iterrows(), start=1):
        tag = r["tags"][0] if r["tags"] else "-"
        L.append(f"  {pos:>3} | {r['id_sku']:>6} | {_n(r['unidades']):>8} | {_n(r['pedidos']):>7} | {tag:<14} | {str(r['nome'])[:75]}")
    top_unidades = float(top_sem_peso(tabela, top)["unidades"].sum())
    ris = riscos(tabela)
    L += [
        f"  Esses {top} SKUs somam {_n(top_unidades)} unidades = {_pct(top_unidades, ris['total_unidades'])} das unidades sem peso "
        f"e {_pct(top_unidades, cob['unidades']['total'])} de todas as unidades vendidas.",
        "",
        "   Categorias de risco entre os SKUs SEM peso (um SKU pode ter mais de uma tag):",
        "     tag                  | SKUs | unidades | % das unidades sem peso",
    ]
    for tag, v in ris["por_tag"].items():
        L.append(f"     {tag:<20} | {_n(v['skus']):>4} | {_n(v['unidades']):>8} | {_pct(v['unidades'], ris['total_unidades'])}")
    L += ["", "   Categorias (ids; o CSV não traz nomes) com mais unidades sem peso — nível 1 | caminho completo:"]
    for topo, r in ris["por_topo"].iterrows():
        L.append(f"     /{topo}/ : {_n(r['sum'])} unidades em {_n(r['size'])} SKUs")
    for caminho, r in ris["por_caminho"].iterrows():
        L.append(f"     {caminho} : {_n(r['sum'])} unidades em {_n(r['size'])} SKUs")
    L.append("")

    todos = pesos_pedidos(itens, tabela)
    so_alta = pesos_pedidos(itens, tabela, so_alta=True)
    completos = todos[todos["completo"]]
    L += ["4. PESO ESTIMADO POR PEDIDO (quantidade x peso unitário; \"completo\" = todos os itens têm peso)"]
    L += [
        f"  Pedidos completos (pesos de confiança alta + baixa): {_n(len(completos))} de {_n(len(todos))} ({_pct(len(completos), len(todos))})",
        f"  Pedidos completos só com confiança ALTA: {_n(so_alta['completo'].sum())} de {_n(len(so_alta))} ({_pct(so_alta['completo'].sum(), len(so_alta))})",
        f"  Pedidos incompletos: {_n((~todos['completo']).sum())} | itens sem peso por pedido incompleto (mediana): "
        f"{_f(todos.loc[~todos['completo'], 'itens_sem_peso'].median(), 1)} de {_f(todos.loc[~todos['completo'], 'itens'].median(), 0)} itens",
        f"  Unidades sem peso dentro dos pedidos incompletos: {_pct(todos['unidades_sem_peso'].sum(), todos['unidades'].sum())} das unidades de todos os pedidos",
    ]
    L += ["", "  Decis do peso (kg):"]
    L += _linhas_decis("completos       ", decis(completos["peso_kg"]))
    L += _linhas_decis("incompletos (piso)", decis(todos.loc[~todos["completo"], "peso_kg"]))
    pesados = completos[completos["peso_kg"] > 1000]
    L += [f"  Pedidos completos acima de 1.000 kg: {len(pesados)} (maior: {_f(completos['peso_kg'].max() if len(completos) else np.nan, 0)} kg)"]
    multiplas = int((todos["lojas_distintas"] > 1).sum())
    if multiplas:
        L += [f"  ATENÇÃO: {multiplas} pedido(s) com mais de uma loja; a loja usada é a do primeiro item."]

    L += ["", "  QUANTO A CONFERÊNCIA MANUAL MELHORA ISSO (% de pedidos completos se os N SKUs sem peso mais vendidos ganharem peso):",
          "     N SKUs corrigidos | fila por UNIDADES vendidas (a ordem do CSV) | fila por PEDIDOS afetados"]
    por_unidades = simular_correcao(itens, tabela, "unidades")
    por_pedidos = simular_correcao(itens, tabela, "pedidos")
    for a, b in zip(por_unidades, por_pedidos):
        L.append(f"     {_n(a['n']):>17} | {_n(a['completos']):>6} pedidos = {_f(a['pct']):>5}%{'':<18} | {_n(b['completos']):>6} pedidos = {_f(b['pct']):>5}%")
    for meta in (0.8, 0.9, 0.95):
        L.append(
            f"     Para {int(meta * 100)}% de pedidos completos: conferir {_n(skus_para_atingir(itens, tabela, meta, 'unidades'))} SKUs"
            f" (fila por unidades) ou {_n(skus_para_atingir(itens, tabela, meta, 'pedidos'))} SKUs (fila por pedidos afetados)"
        )
    L += ["  (os SKUs de confiança baixa, com peso sugerido incerto, também pedem conferência e não entram nessa conta)"]

    L += ["", "  Por loja (pesos só dos pedidos completos):", "     loja                          | pedidos | completos | % compl. | mediana kg | P90 kg | total kg"]
    for _, r in por_loja(todos).iterrows():
        L.append(
            f"     {str(r['loja'])[:30]:<30}| {_n(r['pedidos']):>7} | {_n(r['completos']):>9} | {_f(r['pct_completos']):>7}% | "
            f"{_f(r['peso_mediano_kg']):>10} | {_f(r['peso_p90_kg']):>6} | {_f(r['peso_total_completos_kg'], 0):>8}"
        )

    L += [
        "",
        "5. LIMITES DESTE ESTUDO",
        "  - ml/L viram kg com densidade 1 (óleo ~0,92; leite ~1,03; desinfetante ~1): erro pequeno, mas existe.",
        "  - Peso líquido (o do rótulo) e não bruto: a embalagem e o palete não entram.",
        "  - Confiança baixa (multiplicador, contagem, kit) pede conferência; o CSV inicial já vem ordenado para isso.",
        "  - Pedidos incompletos mostram só um piso do peso: o real é maior.",
    ]
    return "\n".join(L)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Estudo de viabilidade do peso dos pedidos (só lê arquivos locais).")
    parser.add_argument("--pasta", default=str(PASTA_PADRAO), help="pasta com skus.csv e itens_pedidos.csv (padrão: data/peso)")
    parser.add_argument("--saida", default=str(SAIDA_PADRAO), help="CSV inicial de pesos (padrão: data/peso/item_pesos_inicial.csv)")
    parser.add_argument("--top", type=int, default=100, help="quantos SKUs sem peso listar (padrão: 100)")
    parser.add_argument("--excel", action="store_true", help="CSV com ';' e vírgula decimal, para abrir direto no Excel em português")
    args = parser.parse_args(argv)

    saida = Path(args.saida)
    if not esta_protegido_do_git(saida):
        sys.exit(
            f"ERRO: {saida} está dentro do repositório e não é ignorado pelo git (o repositório é público). "
            "Use um caminho em data/peso/ ou fora do projeto."
        )
    pasta = Path(args.pasta)
    if not esta_protegido_do_git(pasta / "skus.csv"):
        print(f"AVISO: {pasta} está no repositório e não é ignorada pelo git: não faça commit desses arquivos.", file=sys.stderr)

    skus, itens = carregar(pasta)
    tabela = montar_tabela_skus(skus)
    print(gerar_relatorio(skus, itens, tabela, args.top))
    escrever_csv(tabela, saida, excel=args.excel)
    print(f"\nCSV inicial para revisão: {saida} ({len(tabela)} SKUs, ordenado por unidades vendidas; fora do git)")


if __name__ == "__main__":
    main()
