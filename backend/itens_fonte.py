"""
Fonte de itens dos pedidos (subetapa 3 do peso): interface única para trazer, de qualquer origem, as linhas "pedido, SKU, quantidade" (e, opcional, a
descrição do produto) que ligam os itens aos pedidos do lote, a validação linha a linha e o modelo para baixar.

Camadas (o mesmo desenho de `pedidos_fonte.py`):
    1) uma FONTE lê a origem e devolve um `LoteItensBruto` (linhas com os campos padrão, ainda como texto): hoje só `FonteArquivoItens` (CSV/XLSX enviado
       pelo operador). Google Sheets, Superset e BigQuery (Etapa 15) entram como novas classes com o método `ler()`, registradas em `FONTES`, e reaproveitam a validação;
    2) `validar_itens` valida e padroniza cada linha e devolve o RELATÓRIO (válidas, erros, avisos) e os itens válidos, para o operador conferir ANTES de aceitar.

Nada é gravado nem guardado aqui: o arquivo de itens vive só na resposta e na memória da tela. Informativo: o peso nunca bloqueia nada.
Privacidade: ids de pedido, SKUs e descrições NUNCA vão para log nem para mensagem de erro; os motivos citam só o NOME do campo e o número da linha; erros de leitura usam
textos fixos. (O relatório que volta para a tela do operador pode mostrar os ids e códigos, como a lista de pedidos já faz.)
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional, Protocol

import openpyxl

import item_pesos as ip

MAX_BYTES = 5 * 1024 * 1024
MAX_LINHAS = 20000
MAX_ERROS_NA_RESPOSTA = 1000
MAX_AVISOS_NA_RESPOSTA = 1000
MAX_PEDIDOS_FORA_NA_RESPOSTA = 50
MAX_SKUS_NA_RESPOSTA = 200
MAX_IDS_DO_LOTE = 20000
QUANTIDADE_MAXIMA = Decimal("100000")
TAMANHO_ID_PEDIDO = 60
TAMANHO_DESCRICAO = ip.TAMANHO_NOME  # 300: o mesmo limite do nome do item no cadastro de pesos

CAMPOS = ("id_pedido", "sku", "quantidade", "descricao")
OBRIGATORIOS = {"id_pedido": "id_pedido", "sku": "sku", "quantidade": "quantidade"}

# Cabeçalhos reconhecidos POR NOME, sem diferença de maiúsculas, acentos, espaços nem separadores ("Número do pedido" = "numero_do_pedido").
_ALIASES = {
    "id_pedido": ("idpedido", "iddopedido", "pedido", "id", "numeropedido", "numerodopedido", "npedido", "codigopedido", "codigodopedido", "order", "orderid"),
    "sku": ("sku", "idsku", "skuid", "codigo", "codigoitem", "codigodoitem", "coditem", "iditem", "item"),
    "quantidade": ("quantidade", "qtd", "qtde", "quantity", "quantitysku", "quantidadesku", "unidades", "qty"),
    "descricao": ("descricao", "nome", "produto", "nomedoitem", "descricaodoitem", "nomeproduto", "nomedoproduto", "descricaodoproduto"),
}

MODELO_COLUNAS = ("id_pedido", "sku", "quantidade", "descricao")
_EXEMPLOS = (("1001", "10001", "2", "Arroz Branco Tipo 1 5kg"), ("1001", "10002", "1,5", "Creme de Leite 200g"))


class ErroDeItens(ValueError):
    """Problema com o arquivo todo (formato, tamanho, colunas). A mensagem é fixa, em linguagem do operador, sem conteúdo do arquivo."""


# ----------------------------------------------------------------------------------------------------------
# Interface única
# ----------------------------------------------------------------------------------------------------------
@dataclass
class LinhaItemBruta:
    numero: int  # linha na origem (1 = cabeçalho)
    campos: dict  # campo padrão -> texto (campos que a origem não tem ficam ausentes)


@dataclass
class LoteItensBruto:
    origem: str  # "arquivo" (depois: "sheets", "superset", "bigquery")
    formato: str  # "csv", "xlsx"...
    colunas: dict  # campo padrão -> nome do cabeçalho na origem
    linhas: list = field(default_factory=list)


class FonteItens(Protocol):
    """Contrato de toda fonte de itens: `ler()` devolve o lote já com os nomes de campo padrão."""

    def ler(self) -> LoteItensBruto: ...


def _chave(texto) -> str:
    return ip.normalizar_cabecalho(texto).replace("_", "")


def _reconhecer(cabecalho: list) -> dict:
    """campo padrão -> posição da coluna, pelo nome do cabeçalho (o primeiro que casar)."""
    posicoes = {}
    for i, c in enumerate(cabecalho):
        posicoes.setdefault(_chave(c), i)
    achados = {}
    for campo, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in posicoes:
                achados[campo] = posicoes[alias]
                break
    return achados


def _pontos(cabecalho: list) -> int:
    """Quantas colunas OBRIGATÓRIAS o cabeçalho reconhece (escolhe o delimitador e a linha do cabeçalho)."""
    achados = _reconhecer(cabecalho)
    return sum(1 for campo in OBRIGATORIOS if campo in achados) * 10 + len(achados)


def _texto(valor) -> str:
    """Célula como texto limpo: números inteiros sem '.0', datas em ISO."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, float):
        return str(int(valor)) if valor.is_integer() else str(valor)
    if isinstance(valor, datetime):
        return valor.isoformat(sep=" ")
    if isinstance(valor, (date, time)):
        return valor.isoformat()
    return " ".join(str(valor).split())


def _montar_lote(formato: str, cabecalho: list, linhas_brutas: list) -> LoteItensBruto:
    posicoes = _reconhecer(cabecalho)
    faltam = [rotulo for campo, rotulo in OBRIGATORIOS.items() if campo not in posicoes]
    if faltam:
        raise ErroDeItens(
            "Faltam colunas obrigatórias no cabeçalho: " + ", ".join(faltam) + '. Use o modelo (botão "Baixar modelo") ou acrescente as colunas.'
        )
    lote = LoteItensBruto(origem="arquivo", formato=formato, colunas={c: str(cabecalho[i]).strip() for c, i in posicoes.items()})
    for numero, celulas in linhas_brutas:
        textos = [_texto(c) for c in celulas]
        if not any(textos):
            continue
        lote.linhas.append(LinhaItemBruta(numero, {c: (textos[i] if i < len(textos) else "") for c, i in posicoes.items()}))
        if len(lote.linhas) > MAX_LINHAS:
            raise ErroDeItens(f"O arquivo tem mais de {MAX_LINHAS:,} linhas".replace(",", ".") + ". Divida em arquivos menores.")
    return lote


def _ler_csv(conteudo: bytes) -> LoteItensBruto:
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("cp1252", errors="replace")
    melhor = None
    for delimitador in (";", ",", "\t"):
        leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=delimitador)
        try:
            linhas = [(leitor.line_num, linha) for linha in leitor]
        except csv.Error:  # célula gigante, aspas quebradas...: texto fixo, nunca o conteúdo
            raise ErroDeItens("Não consegui ler o CSV. Confira o arquivo ou use o modelo.") from None
        posicao = next((i for i, (_, l) in enumerate(linhas) if any(c.strip() for c in l)), None)
        if posicao is None:
            continue
        pontos = _pontos(linhas[posicao][1])
        if melhor is None or pontos > melhor[0]:
            melhor = (pontos, linhas, posicao)
    if melhor is None:
        raise ErroDeItens('O arquivo está vazio. Use o modelo (botão "Baixar modelo").')
    _, linhas, posicao = melhor
    return _montar_lote("csv", linhas[posicao][1], linhas[posicao + 1:])


def _ler_xlsx(conteudo: bytes) -> LoteItensBruto:
    try:
        pasta = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception:  # corrompido ou não é .xlsx: texto fixo, sem detalhe técnico
        raise ErroDeItens("Não consegui ler a planilha. Confira se é um arquivo .xlsx válido ou use o modelo.") from None
    melhor = None
    try:
        for aba in pasta.worksheets:
            linhas = [(i, list(l)) for i, l in enumerate(aba.iter_rows(values_only=True), start=1)]
            for posicao, (_, celulas) in enumerate(linhas[:10]):  # o cabeçalho pode ter títulos acima
                pontos = _pontos([_texto(c) for c in celulas])
                if melhor is None or pontos > melhor[0]:
                    melhor = (pontos, linhas, posicao)
    except Exception:
        raise ErroDeItens("Não consegui ler a planilha. Confira se é um arquivo .xlsx válido ou use o modelo.") from None
    finally:
        pasta.close()
    if melhor is None:
        raise ErroDeItens('A planilha está vazia. Use o modelo (botão "Baixar modelo").')
    _, linhas, posicao = melhor
    return _montar_lote("xlsx", [_texto(c) for c in linhas[posicao][1]], linhas[posicao + 1:])


class FonteArquivoItens:
    """CSV ou XLSX enviado pelo operador (o modelo ou variações dos cabeçalhos)."""

    def __init__(self, conteudo: bytes, nome: str = ""):
        self.conteudo = conteudo
        self.nome = (nome or "").lower()

    def ler(self) -> LoteItensBruto:
        if len(self.conteudo) > MAX_BYTES:
            raise ErroDeItens("O arquivo é grande demais (máximo de 5 MB). Divida em arquivos menores.")
        if self.nome.endswith(".csv"):
            return _ler_csv(self.conteudo)
        if self.nome.endswith(".xlsx"):
            return _ler_xlsx(self.conteudo)
        if self.nome.endswith(".xls"):
            raise ErroDeItens("Planilhas .xls antigas não são aceitas: salve como .xlsx ou .csv.")
        raise ErroDeItens("Formato de arquivo inválido. Envie um arquivo .csv ou .xlsx.")


FONTES = {"arquivo": FonteArquivoItens}  # Etapa 15: "sheets", "superset", "bigquery"


# ----------------------------------------------------------------------------------------------------------
# Valores
# ----------------------------------------------------------------------------------------------------------
_RE_MILHAR_SUSPEITO = re.compile(r"^\d+\.\d{3}$")


def normalizar_id_pedido(texto) -> str:
    """Id do pedido como texto limpo (a planilha às vezes devolve 123.0)."""
    return re.sub(r"\.0+$", "", " ".join(str(texto or "").split()))


def interpretar_quantidade(texto: str) -> tuple:
    """
    (quantidade como Decimal, aviso ou None). Número maior que zero até 100.000, com vírgula ou ponto decimal ("2", "1,5", "0.5"); um único ponto é decimal ("1.000" = 1),
    por isso "1.000" e parecidos geram AVISO (a linha vale). ValueError com mensagem FIXA (sem o valor) se vazia, texto, zero, negativa ou acima do limite.
    """
    limpo = str(texto or "").replace("\xa0", " ").strip()
    if not limpo:
        raise ValueError("quantidade vazia")
    if not re.fullmatch(r"[0-9.,]+", limpo):
        raise ValueError("quantidade inválida (use um número maior que zero, até 100.000)")
    try:
        valor = ip.interpretar_peso(limpo, QUANTIDADE_MAXIMA)
    except ValueError as erro:
        # a mensagem original cita o valor digitado: não é repassada
        if "passa de" in str(erro):
            raise ValueError("quantidade acima do limite (100.000)") from None
        raise ValueError("quantidade inválida (use um número maior que zero, até 100.000)") from None
    aviso = None
    if _RE_MILHAR_SUSPEITO.match(limpo):
        aviso = f"quantidade lida como decimal ({limpo.replace('.', ',')}); se for milhar, o arquivo deve usar o número sem ponto"
    return valor, aviso


# ----------------------------------------------------------------------------------------------------------
# Validação linha a linha (sem banco)
# ----------------------------------------------------------------------------------------------------------
@dataclass
class ResultadoItens:
    formato: str
    colunas: dict
    linhas_lidas: int
    itens: list  # [{"id_pedido", "sku", "quantidade" (Decimal), "descricao" (ou None), "linhas": [n...]}], já somados
    erros: list = field(default_factory=list)  # [{"linha", "id_pedido", "motivos"}]
    avisos: list = field(default_factory=list)  # [{"linha", "motivo"}]
    pedidos_fora_do_lote: list = field(default_factory=list)  # ids, sem repetir
    linhas_fora_do_lote: int = 0


def _numero_para_json(q: Decimal):
    q = q.normalize()
    return int(q) if q == q.to_integral_value() else float(q)


def validar_itens(bruto: LoteItensBruto, ids_do_lote: Optional[list] = None) -> ResultadoItens:
    """
    Valida o lote de itens. `ids_do_lote`: ids dos pedidos do lote da tela (só ids); com eles, linha de pedido que não está no lote é listada e IGNORADA
    (sem a lista, não confere). Mesmo pedido + mesmo SKU em mais de uma linha: as quantidades são SOMADAS, com aviso. Descrição: a primeira de cada SKU vale.
    """
    no_lote = None if ids_do_lote is None else {normalizar_id_pedido(i) for i in ids_do_lote}
    resultado = ResultadoItens(formato=bruto.formato, colunas=bruto.colunas, linhas_lidas=len(bruto.linhas), itens=[])
    por_chave = {}
    descricao_do_sku = {}
    fora = {}
    for linha in bruto.linhas:
        c, numero, motivos = linha.campos, linha.numero, []
        id_pedido = normalizar_id_pedido(c.get("id_pedido", ""))
        if not id_pedido:
            motivos.append("id_pedido vazio")
        elif len(id_pedido) > TAMANHO_ID_PEDIDO:
            motivos.append(f"id_pedido longo demais (máximo de {TAMANHO_ID_PEDIDO} caracteres)")
        sku = ""
        bruto_sku = c.get("sku", "")
        if not bruto_sku:
            motivos.append("sku vazio")
        else:
            try:
                sku = ip.normalizar_id_sku(bruto_sku)
            except ValueError:
                motivos.append("sku inválido (até 40 letras, números, ponto, hífen ou sublinhado, sem espaços)")
        quantidade, aviso_qtd = None, None
        try:
            quantidade, aviso_qtd = interpretar_quantidade(c.get("quantidade", ""))
        except ValueError as erro:
            motivos.append(str(erro))
        if motivos:
            resultado.erros.append({"linha": numero, "id_pedido": id_pedido[:TAMANHO_ID_PEDIDO], "motivos": motivos})
            continue
        if no_lote is not None and id_pedido not in no_lote:
            fora.setdefault(id_pedido, 0)
            fora[id_pedido] += 1
            resultado.linhas_fora_do_lote += 1
            continue
        if aviso_qtd:
            resultado.avisos.append({"linha": numero, "motivo": aviso_qtd})
        descricao = c.get("descricao", "").strip()
        if descricao and len(descricao) > TAMANHO_DESCRICAO:
            descricao = descricao[:TAMANHO_DESCRICAO]
            resultado.avisos.append({"linha": numero, "motivo": f"descrição cortada em {TAMANHO_DESCRICAO} caracteres"})
        if descricao:
            descricao_do_sku.setdefault(sku, descricao)  # descrições diferentes para o mesmo SKU: vale a primeira, sem erro
        chave = (id_pedido, sku)
        existente = por_chave.get(chave)
        if existente is None:
            por_chave[chave] = {"id_pedido": id_pedido, "sku": sku, "quantidade": quantidade, "linhas": [numero]}
        else:
            existente["quantidade"] += quantidade
            existente["linhas"].append(numero)
    for item in por_chave.values():
        item["descricao"] = descricao_do_sku.get(item["sku"])
        if len(item["linhas"]) > 1:
            linhas = item["linhas"]
            lista = ", ".join(str(n) for n in linhas[:-1]) + f" e {linhas[-1]}"
            resultado.avisos.append({"linha": linhas[0], "motivo": f"linha repetida (mesmo pedido e sku nas linhas {lista}): as quantidades foram somadas"})
        resultado.itens.append(item)
    resultado.avisos.sort(key=lambda a: a["linha"])
    resultado.pedidos_fora_do_lote = list(fora)
    return resultado


def relatorio(resultado: ResultadoItens, pesos: Optional[dict] = None) -> dict:
    """
    Relatório para o operador conferir ANTES de aceitar (e os itens válidos, que ficam só na memória da tela). `pesos`: {sku: {"peso_kg", "confianca"}} dos SKUs que
    existem no cadastro (None quando não há item válido: o banco nem foi consultado). SKU que não está em `pesos` é novo; com `peso_kg` nulo, existe sem peso.
    """
    pesos = pesos or {}
    descricao = {}
    for item in resultado.itens:
        descricao.setdefault(item["sku"], item["descricao"])
    novos = [s for s in descricao if s not in pesos]
    sem_peso = [s for s in descricao if s in pesos and pesos[s].get("peso_kg") is None]
    pedidos = {item["id_pedido"] for item in resultado.itens}

    def listar(skus):
        return [{"sku": s, "descricao": descricao[s]} for s in skus[:MAX_SKUS_NA_RESPOSTA]]

    avisos = list(resultado.avisos)
    if novos:
        avisos.append({"linha": None, "motivo": f"{len(novos)} sku(s) não estão no cadastro de pesos: entram na fila \"sem peso\" ao aceitar"})
    if sem_peso:
        avisos.append({"linha": None, "motivo": f"{len(sem_peso)} sku(s) existem sem peso: entram na fila \"sem peso\" ao aceitar"})
    return {
        "formato": resultado.formato,
        "colunas": resultado.colunas,
        "resumo": {
            "linhas": resultado.linhas_lidas, "validas": sum(len(i["linhas"]) for i in resultado.itens), "invalidas": len(resultado.erros),
            "fora_do_lote": resultado.linhas_fora_do_lote, "pedidos_com_itens": len(pedidos), "skus_distintos": len(descricao),
            "skus_novos": len(novos), "skus_sem_peso": len(sem_peso),
        },
        "erros": resultado.erros[:MAX_ERROS_NA_RESPOSTA],
        "erros_truncados": len(resultado.erros) > MAX_ERROS_NA_RESPOSTA,
        "avisos": avisos[:MAX_AVISOS_NA_RESPOSTA],
        "avisos_truncados": len(avisos) > MAX_AVISOS_NA_RESPOSTA,
        "pedidos_fora_do_lote": resultado.pedidos_fora_do_lote[:MAX_PEDIDOS_FORA_NA_RESPOSTA],
        "total_pedidos_fora_do_lote": len(resultado.pedidos_fora_do_lote),
        "skus_novos": listar(novos),
        "skus_sem_peso": listar(sem_peso),
        "itens": [
            {"id_pedido": i["id_pedido"], "sku": i["sku"], "quantidade": _numero_para_json(i["quantidade"]), "descricao": i["descricao"]}
            for i in resultado.itens
        ],
        "pesos": pesos,
    }


# ----------------------------------------------------------------------------------------------------------
# Modelo para baixar
# ----------------------------------------------------------------------------------------------------------
def gerar_modelo_csv() -> bytes:
    """Modelo em CSV (UTF-8 com BOM e ';', que o Excel em português abre direito): id_pedido, sku, quantidade e a descricao opcional, com 2 exemplos."""
    saida = io.StringIO(newline="")
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(MODELO_COLUNAS)
    escritor.writerows(_EXEMPLOS)
    return b"\xef\xbb\xbf" + saida.getvalue().encode("utf-8")
