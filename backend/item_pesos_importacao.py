"""
Importação de vários itens por CSV/XLSX na tela "Pesos dos itens" (sem migration: usa a tabela item_pesos que já existe).

Fluxo em duas etapas, SEM guardar nada no servidor entre elas:
    1) `ler_arquivo` + `validar_linhas` (sem banco) e `relatorio` (lê só o cadastro) devolvem o RELATÓRIO antes de gravar;
    2) a confirmação envia o arquivo de novo, o servidor revalida tudo e `importar` grava numa única transação.

Regras: item que já existe (sem diferença de maiúsculas nem de espaços nas pontas) é IGNORADO por padrão; com "atualizar", atualiza
nome, peso, fonte e confiança, mas NUNCA sobrescreve um item cujo peso um operador editou na tela (mesma regra da carga inicial:
`atualizado_por` diferente da carga). Itens sem peso entram na fila "sem peso" (opcional). O peso é só informativo.
Mensagens de erro citam o campo e a linha, nunca o conteúdo da célula; erros de leitura do arquivo têm texto fixo.
"""
import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Optional

import openpyxl

import item_pesos as ip

MAX_BYTES = 5 * 1024 * 1024
MAX_LINHAS = 20000
MAX_ERROS_NA_RESPOSTA = 1000
FONTE_IMPORTACAO = "importação pelo site"
COLUNAS_DO_MODELO = ("id_sku", "reference_code", "nome", "peso_kg", "fonte", "confianca")

# Cabeçalhos reconhecidos POR NOME, sem diferença de maiúsculas, acentos, espaços nem separadores. A ordem dos aliases do peso é a prioridade.
_ALIASES = {
    "id_sku": ("idsku", "sku", "codigo", "id", "codigodoitem", "coditem", "iditem", "codigoitem"),
    "reference_code": ("referencecode", "referencia", "ref", "codigodereferencia", "codigoreferencia", "codreferencia"),
    "nome": ("nome", "descricao", "produto", "nomedoitem", "descricaodoitem"),
    "peso": ("pesokg", "pesokgrevisado", "pesorevisado", "pesokgsugerido", "peso"),
    "fonte": ("fonte",),
    "confianca": ("confianca",),
    "unidades": ("unidadesvendidas", "unidades"),
}
OBRIGATORIAS = {"id_sku": "código (id_sku)", "nome": "nome"}


class ErroDeImportacao(ValueError):
    """Problema com o arquivo todo. A mensagem é fixa, em linguagem do operador, sem conteúdo do arquivo."""


@dataclass
class LoteItens:
    formato: str
    colunas: dict  # campo -> cabeçalho original reconhecido
    linhas: list = field(default_factory=list)  # [(número da linha, {campo: texto})]


@dataclass
class LinhaItem:
    numero: int
    id_sku: str
    nome: str
    reference_code: Optional[str] = None
    peso: Optional[Decimal] = None
    fonte: Optional[str] = None
    confianca: Optional[str] = None
    unidades: int = 0


# ----------------------------------------------------------------------------------------------------------
# Leitura do arquivo (CSV e XLSX)
# ----------------------------------------------------------------------------------------------------------
def _chave_cabecalho(texto) -> str:
    return ip.normalizar_cabecalho(texto).replace("_", "")


def _reconhecer(cabecalho: list) -> dict:
    posicoes = {}
    for i, c in enumerate(cabecalho):
        posicoes.setdefault(_chave_cabecalho(c), i)
    achados = {}
    for campo, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in posicoes:
                achados[campo] = posicoes[alias]
                break
    return achados


def _texto(valor) -> str:
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


def _montar(formato: str, cabecalho: list, linhas_brutas: list) -> LoteItens:
    posicoes = _reconhecer(cabecalho)
    faltam = [rotulo for campo, rotulo in OBRIGATORIAS.items() if campo not in posicoes]
    if faltam:
        raise ErroDeImportacao(
            "Faltam colunas obrigatórias no cabeçalho: " + ", ".join(faltam) + '. Use o modelo (botão "Baixar modelo") ou acrescente as colunas.'
        )
    lote = LoteItens(formato=formato, colunas={c: str(cabecalho[i]).strip() for c, i in posicoes.items()})
    for numero, celulas in linhas_brutas:
        textos = [_texto(c) for c in celulas]
        if not any(textos):
            continue
        lote.linhas.append((numero, {c: (textos[i] if i < len(textos) else "") for c, i in posicoes.items()}))
        if len(lote.linhas) > MAX_LINHAS:
            raise ErroDeImportacao(f"O arquivo tem mais de {MAX_LINHAS:,} linhas".replace(",", ".") + ". Divida em arquivos menores.")
    return lote


def _ler_csv(conteudo: bytes) -> LoteItens:
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("cp1252", errors="replace")
    melhor = None
    for delimitador in (";", ",", "\t"):
        leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=delimitador)
        try:
            linhas = [(leitor.line_num, linha) for linha in leitor]
        except csv.Error:
            raise ErroDeImportacao("Não consegui ler o CSV. Confira o arquivo ou use o modelo.") from None
        posicao = next((i for i, (_, l) in enumerate(linhas) if any(c.strip() for c in l)), None)
        if posicao is None:
            continue
        pontos = len(_reconhecer(linhas[posicao][1]))
        if melhor is None or pontos > melhor[0]:
            melhor = (pontos, linhas, posicao)
    if melhor is None:
        raise ErroDeImportacao("O arquivo está vazio. Use o modelo (botão \"Baixar modelo\").")
    _, linhas, posicao = melhor
    return _montar("csv", linhas[posicao][1], linhas[posicao + 1:])


def _ler_xlsx(conteudo: bytes) -> LoteItens:
    try:
        pasta = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception:  # corrompido ou não é .xlsx: texto fixo, sem detalhe técnico
        raise ErroDeImportacao("Não consegui ler a planilha. Confira se é um arquivo .xlsx válido ou use o modelo.") from None
    melhor = None
    try:
        for aba in pasta.worksheets:
            linhas = [(i, list(l)) for i, l in enumerate(aba.iter_rows(values_only=True), start=1)]
            for posicao, (_, celulas) in enumerate(linhas[:10]):
                pontos = len(_reconhecer([_texto(c) for c in celulas]))
                if melhor is None or pontos > melhor[0]:
                    melhor = (pontos, linhas, posicao)
    except Exception:
        raise ErroDeImportacao("Não consegui ler a planilha. Confira se é um arquivo .xlsx válido ou use o modelo.") from None
    finally:
        pasta.close()
    if melhor is None:
        raise ErroDeImportacao("A planilha está vazia. Use o modelo (botão \"Baixar modelo\").")
    _, linhas, posicao = melhor
    return _montar("xlsx", [_texto(c) for c in linhas[posicao][1]], linhas[posicao + 1:])


def ler_arquivo(conteudo: bytes, nome: str = "") -> LoteItens:
    """Lê um CSV ou XLSX (cabeçalhos por nome, variações aceitas). ErroDeImportacao com texto fixo se o arquivo não servir."""
    nome = (nome or "").lower()
    if len(conteudo) > MAX_BYTES:
        raise ErroDeImportacao("O arquivo é grande demais (máximo de 5 MB). Divida em arquivos menores.")
    if nome.endswith(".csv"):
        return _ler_csv(conteudo)
    if nome.endswith(".xlsx"):
        return _ler_xlsx(conteudo)
    if nome.endswith(".xls"):
        raise ErroDeImportacao("Planilhas .xls antigas não são aceitas: salve como .xlsx ou .csv.")
    raise ErroDeImportacao("Formato de arquivo inválido. Envie um arquivo .csv ou .xlsx.")


# ----------------------------------------------------------------------------------------------------------
# Validação linha a linha (sem banco)
# ----------------------------------------------------------------------------------------------------------
def _inteiro(texto: str) -> int:
    try:
        return max(0, int(float(texto.replace(".", "").replace(",", ".")))) if texto else 0
    except ValueError:
        return 0


def validar_linhas(lote: LoteItens) -> tuple:
    """([LinhaItem válidas], [{linha, id, motivos}]). Os motivos citam só o campo, nunca o valor da célula."""
    validas, erros, primeira = [], [], {}
    for numero, c in lote.linhas:
        motivos = []
        id_bruto = c.get("id_sku", "")
        id_sku = ""
        if not id_bruto:
            motivos.append("código vazio")
        else:
            try:
                id_sku = ip.normalizar_id_sku(id_bruto)
            except ValueError:
                motivos.append("código inválido (até 40 letras, números, ponto, hífen ou sublinhado, sem espaços)")
        nome = c.get("nome", "")
        if not nome:
            motivos.append("nome vazio")
        elif len(nome) > ip.TAMANHO_NOME:
            motivos.append(f"nome longo demais (máximo de {ip.TAMANHO_NOME} caracteres)")
        peso = None
        if c.get("peso", ""):
            try:
                peso = ip.interpretar_peso(c["peso"])
            except ValueError:
                motivos.append("peso inválido (use um número em kg, maior que 0 e até 1000)")
        confianca = None
        if c.get("confianca", ""):
            try:
                confianca = ip.normalizar_confianca(c["confianca"])
            except ValueError:
                motivos.append("confiança inválida (use alta, média ou baixa)")
        if len(c.get("reference_code", "")) > ip.TAMANHO_REFERENCIA:
            motivos.append(f"código de referência longo demais (máximo de {ip.TAMANHO_REFERENCIA})")
        if len(c.get("fonte", "")) > ip.TAMANHO_FONTE:
            motivos.append(f"fonte longa demais (máximo de {ip.TAMANHO_FONTE})")
        if id_sku:
            anterior = primeira.setdefault(id_sku.lower(), numero)
            if anterior != numero:
                motivos.append(f"código repetido no arquivo (a primeira vez está na linha {anterior})")
        if motivos:
            erros.append({"linha": numero, "id": id_sku[:40], "motivos": motivos})
            continue
        validas.append(LinhaItem(
            numero=numero, id_sku=id_sku, nome=nome, reference_code=c.get("reference_code") or None, peso=peso,
            fonte=c.get("fonte") or None, confianca=confianca, unidades=_inteiro(c.get("unidades", "")),
        ))
    return validas, erros


# ----------------------------------------------------------------------------------------------------------
# Banco: o que já existe, relatório e gravação
# ----------------------------------------------------------------------------------------------------------
SQL_TODOS = "SELECT id_sku, peso_kg, atualizado_por FROM item_pesos"
SQL_INSERIR = """
    INSERT INTO item_pesos (id_sku, reference_code, nome, peso_kg, fonte, confianca, unidades_vendidas, atualizado_em, atualizado_por)
    VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_TIMESTAMP, $8)
    ON CONFLICT (id_sku) DO NOTHING
"""
# O guarda repete a regra em SQL: peso editado por operador nunca é sobrescrito (item sem peso ou da carga inicial pode ser atualizado).
_GUARDA = "(peso_kg IS NULL OR atualizado_por IS NULL OR atualizado_por = $%d)"
SQL_ATUALIZAR_COM_PESO = (
    "UPDATE item_pesos SET nome = $2, peso_kg = $3, fonte = $4, confianca = $5, atualizado_em = CURRENT_TIMESTAMP, atualizado_por = $6 "
    "WHERE id_sku = $1 AND " + _GUARDA % 7
)
SQL_ATUALIZAR_NOME = (
    "UPDATE item_pesos SET nome = $2, atualizado_em = CURRENT_TIMESTAMP, atualizado_por = $3 WHERE id_sku = $1 AND " + _GUARDA % 4
)


def protegido(existente: dict) -> bool:
    """Peso que um operador editou na tela: atualizado_por diferente da carga inicial (e diferente de vazio) e item com peso."""
    return (
        existente.get("peso_kg") is not None
        and existente.get("atualizado_por") not in (None, "")
        and existente.get("atualizado_por") != ip.OPERADOR_CARGA_INICIAL
    )


async def ler_existentes(conn) -> dict:
    """{id_sku em minúsculas e sem espaços nas pontas: {id_sku, peso_kg, atualizado_por}} (só leitura; a tabela é pequena)."""
    return {str(r["id_sku"]).strip().lower(): dict(r) for r in await conn.fetch(SQL_TODOS)}


def relatorio(lote: LoteItens, validas: list, erros: list, existentes: Optional[dict]) -> dict:
    """Relatório para o operador conferir ANTES de gravar. `existentes` é None quando não há linha válida (o banco nem foi consultado)."""
    existentes = existentes or {}
    novos_com_peso = novos_sem_peso = atualizaveis = atualizaveis_sem_peso = preservados = 0
    for l in validas:
        ex = existentes.get(l.id_sku.lower())
        if ex is None:
            if l.peso is None:
                novos_sem_peso += 1
            else:
                novos_com_peso += 1
        elif protegido(ex):
            preservados += 1
        else:
            atualizaveis += 1
            atualizaveis_sem_peso += 1 if l.peso is None else 0
    return {
        "formato": lote.formato,
        "colunas": lote.colunas,
        "resumo": {
            "linhas": len(lote.linhas), "validas": len(validas), "invalidos": len(erros),
            "novos_com_peso": novos_com_peso, "novos_sem_peso": novos_sem_peso,
            "existentes": atualizaveis + preservados, "existentes_atualizaveis": atualizaveis, "existentes_atualizaveis_sem_peso": atualizaveis_sem_peso,
            "existentes_preservados": preservados,
            "sem_peso": sum(1 for l in validas if l.peso is None),
        },
        "erros": erros[:MAX_ERROS_NA_RESPOSTA],
        "erros_truncados": len(erros) > MAX_ERROS_NA_RESPOSTA,
    }


async def importar(conn, validas: list, atualizar_existentes: bool, incluir_sem_peso: bool, operador: str) -> dict:
    """
    Revalida contra o cadastro de agora e grava numa única transação (ou grava tudo, ou nada). Registra quem importou e quando.
    Devolve as contagens do que foi feito.
    """
    contagem = {"novos": 0, "novos_sem_peso": 0, "atualizados": 0, "preservados": 0, "ja_existentes_ignorados": 0, "sem_peso_ignorados": 0}
    novos, com_peso, so_nome = [], [], []
    async with conn.transaction():
        existentes = await ler_existentes(conn)
        for l in validas:
            ex = existentes.get(l.id_sku.lower())
            if l.peso is None and not incluir_sem_peso:
                contagem["sem_peso_ignorados"] += 1
                continue
            if ex is None:
                if l.peso is None:
                    contagem["novos_sem_peso"] += 1
                    novos.append((l.id_sku, l.reference_code, l.nome, None, l.fonte, None, l.unidades, operador))
                else:
                    contagem["novos"] += 1
                    novos.append((l.id_sku, l.reference_code, l.nome, l.peso, l.fonte or FONTE_IMPORTACAO, l.confianca or "media", l.unidades, operador))
                continue
            if not atualizar_existentes:
                contagem["ja_existentes_ignorados"] += 1
            elif protegido(ex):
                contagem["preservados"] += 1
            else:
                contagem["atualizados"] += 1
                if l.peso is None:
                    so_nome.append((ex["id_sku"], l.nome, operador, ip.OPERADOR_CARGA_INICIAL))
                else:
                    com_peso.append((ex["id_sku"], l.nome, l.peso, l.fonte or FONTE_IMPORTACAO, l.confianca or "media", operador, ip.OPERADOR_CARGA_INICIAL))
        if novos:
            await conn.executemany(SQL_INSERIR, novos)
        if com_peso:
            await conn.executemany(SQL_ATUALIZAR_COM_PESO, com_peso)
        if so_nome:
            await conn.executemany(SQL_ATUALIZAR_NOME, so_nome)
    contagem["importados"] = contagem["novos"] + contagem["novos_sem_peso"] + contagem["atualizados"]
    return contagem


# ----------------------------------------------------------------------------------------------------------
# Modelo para baixar
# ----------------------------------------------------------------------------------------------------------
_EXEMPLOS = (
    ("10001", "50001", "Arroz Branco Tipo 1 5kg", "5", "embalagem", "alta"),
    ("10002", "50002", "Creme de Leite 200g", "0,2", "", ""),
)


def gerar_modelo_csv() -> bytes:
    """Modelo em CSV (UTF-8 com BOM e ';', que o Excel em português abre direito) com 2 linhas de exemplo."""
    saida = io.StringIO(newline="")
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(COLUNAS_DO_MODELO)
    escritor.writerows(_EXEMPLOS)
    return b"\xef\xbb\xbf" + saida.getvalue().encode("utf-8")
