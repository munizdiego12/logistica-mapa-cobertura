"""
Pesos dos itens (SKUs): regras, leitura do CSV revisado e acesso à tabela item_pesos.

A tabela é criada SÓ pelo Alembic (migrations/versions/0002_item_pesos.py), nunca pelo init_db.
As funções de banco recebem uma conexão asyncpg (`conn`), para serem usadas tanto pelo app (via pool) quanto
pelo script de carga. Não importa nada de `backend.*` (o app roda com backend/ na raiz do path).

O peso é apenas informativo (decisão de produto): aqui só se guarda e se edita o peso de cada item.
"""
import csv
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

PESO_MAXIMO_KG = Decimal("1000")
PESO_SUSPEITO_ALTO_KG = Decimal("40")
PESO_SUSPEITO_BAIXO_KG = Decimal("0.002")
CONFIANCAS = ("alta", "media", "baixa")
OPERADOR_CARGA_INICIAL = "carga inicial (script)"
FONTE_MANUAL = "manual"
FONTE_PLANILHA = "planilha revisada"
LIMITE_MAXIMO_LISTA = 200

RAIZ = Path(__file__).resolve().parent.parent


def _sem_acento(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")


# ----------------------------------------------------------------------------------------------------------
# Valores
# ----------------------------------------------------------------------------------------------------------
def interpretar_peso(valor, maximo: Decimal = PESO_MAXIMO_KG) -> Optional[Decimal]:
    """
    Peso em kg a partir de número ou texto em português ("1,5", "1.5", "0,045", "2 kg", "1.234,56").
    Vazio/None = sem peso (devolve None). Levanta ValueError se não for um número, for <= 0 ou passar do máximo.
    Um único ponto é decimal ("1.000" = 1 kg): não existe item de 1.000 kg no catálogo.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        raise ValueError("peso inválido")
    if isinstance(valor, (int, float, Decimal)):
        numero = Decimal(str(valor))
    else:
        texto = str(valor).replace("\xa0", " ").strip().lower()
        if texto in ("", "-", "—"):
            return None
        texto = re.sub(r"\s*kg$", "", texto).replace(" ", "")
        if not re.fullmatch(r"[0-9.,]+", texto):
            raise ValueError(f"peso '{valor}' não é um número")
        if "," in texto and "." in texto:  # o último separador é o decimal
            if texto.rfind(",") > texto.rfind("."):
                texto = texto.replace(".", "").replace(",", ".")
            else:
                texto = texto.replace(",", "")
        elif "," in texto:
            texto = texto.replace(",", ".")
        elif texto.count(".") > 1:
            texto = texto.replace(".", "")
        try:
            numero = Decimal(texto)
        except InvalidOperation:
            raise ValueError(f"peso '{valor}' não é um número") from None
    if not numero.is_finite():
        raise ValueError("peso inválido")
    numero = numero.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if numero <= 0:
        raise ValueError("o peso deve ser maior que zero")
    if numero > maximo:
        raise ValueError(f"o peso passa de {maximo} kg")
    return numero


def normalizar_confianca(valor) -> Optional[str]:
    """'Alta', 'média', 'BAIXA' -> alta/media/baixa; vazio -> None; qualquer outra coisa levanta ValueError."""
    texto = _sem_acento(valor).strip().lower()
    if texto == "":
        return None
    if texto not in CONFIANCAS:
        raise ValueError(f"confiança '{valor}' inválida (use alta, media ou baixa)")
    return texto


def normalizar_id_sku(valor) -> str:
    texto = str(valor or "").strip()
    texto = re.sub(r"\.0+$", "", texto)  # a planilha às vezes devolve 27439.0
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", texto):
        raise ValueError("id_sku vazio ou inválido")
    return texto


def escapar_like(texto: str) -> str:
    """Escapa % _ \\ para a busca por nome (LIKE ... ESCAPE '\\')."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ----------------------------------------------------------------------------------------------------------
# CSV revisado (exportado do Google Sheets em português)
# ----------------------------------------------------------------------------------------------------------
_ALIASES = {
    "id_sku": ("id_sku", "sku", "id"),
    "reference_code": ("reference_code", "ref", "referencia", "codigo_de_referencia", "codigo_referencia"),
    "nome": ("nome", "produto", "descricao"),
    "peso": ("peso_kg", "peso_kg_revisado", "peso_revisado", "peso_kg_sugerido", "peso"),  # ordem = prioridade
    "fonte": ("fonte",),
    "confianca": ("confianca",),
    "unidades": ("unidades_vendidas", "unidades"),
}


def normalizar_cabecalho(texto) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _sem_acento(texto).lower()).strip("_")


@dataclass
class LinhaCsv:
    numero: int  # linha do arquivo (1 = cabeçalho)
    id_sku: str = ""
    reference_code: Optional[str] = None
    nome: Optional[str] = None
    peso: Optional[Decimal] = None
    fonte: Optional[str] = None
    confianca: Optional[str] = None
    unidades: int = 0
    status: str = "sem_peso"  # com_peso | sem_peso | invalido | duplicado_ignorado
    motivo: str = ""


@dataclass
class ResultadoCsv:
    linhas: list = field(default_factory=list)
    delimitador: str = ","
    codificacao: str = "utf-8"
    coluna_peso: str = ""
    avisos: list = field(default_factory=list)


def _ler_texto(caminho: Path) -> tuple:
    bruto = Path(caminho).read_bytes()
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            return bruto.decode(codificacao), ("utf-8" if codificacao == "utf-8-sig" else codificacao)
        except UnicodeDecodeError:
            continue
    raise ValueError("não consegui ler o arquivo (codificação desconhecida)")


def _indices_das_colunas(cabecalho: list) -> dict:
    normalizados = [normalizar_cabecalho(c) for c in cabecalho]
    indices = {}
    for campo, aliases in _ALIASES.items():
        for alias in aliases:  # a ordem dos aliases define a prioridade (peso_kg antes de peso_kg_sugerido)
            if alias in normalizados:
                indices[campo] = normalizados.index(alias)
                if campo == "peso":
                    indices["_nome_coluna_peso"] = cabecalho[normalizados.index(alias)].strip()
                break
    return indices


def ler_csv(caminho) -> ResultadoCsv:
    """
    Lê o CSV: aceita ';' ou ',' como separador, vírgula ou ponto como decimal, UTF-8 (com ou sem BOM) ou
    Windows-1252. Classifica cada linha (com peso, sem peso, inválida) sem gravar nada em lugar nenhum.
    """
    texto, codificacao = _ler_texto(caminho)
    primeira = next((l for l in texto.splitlines() if l.strip()), "")
    escolhido = None
    for delimitador in (";", ","):
        cabecalho = next(csv.reader([primeira], delimiter=delimitador), [])
        if "id_sku" in _indices_das_colunas(cabecalho) and "peso" in _indices_das_colunas(cabecalho):
            escolhido = delimitador
            break
    if escolhido is None:
        raise ValueError(
            "não achei as colunas id_sku e peso (peso_kg ou peso_kg_sugerido) no cabeçalho; "
            "confira se o arquivo é o CSV de pesos exportado da planilha"
        )

    resultado = ResultadoCsv(delimitador=escolhido, codificacao=codificacao)
    leitor = csv.reader(texto.splitlines(), delimiter=escolhido)
    cabecalho = next(leitor)
    indices = _indices_das_colunas(cabecalho)
    resultado.coluna_peso = indices.pop("_nome_coluna_peso", "")

    def celula(linha, campo):
        i = indices.get(campo)
        return linha[i].strip() if i is not None and i < len(linha) else ""

    posicao_por_sku = {}
    unidades_invalidas = 0
    for linha in leitor:
        if not any(c.strip() for c in linha):
            continue
        registro = LinhaCsv(numero=leitor.line_num)
        try:
            registro.id_sku = normalizar_id_sku(celula(linha, "id_sku"))
            registro.peso = interpretar_peso(celula(linha, "peso"))
            registro.confianca = normalizar_confianca(celula(linha, "confianca"))
        except ValueError as erro:
            registro.status, registro.motivo = "invalido", str(erro)
            resultado.linhas.append(registro)
            continue
        registro.reference_code = celula(linha, "reference_code")[:60] or None
        registro.nome = celula(linha, "nome") or None
        registro.fonte = celula(linha, "fonte")[:100] or None
        unidades = celula(linha, "unidades")
        if unidades:
            sem_milhar = re.sub(r"(?<=\d)\.(?=\d{3}(\D|$))", "", unidades)
            try:
                registro.unidades = max(0, int(float(sem_milhar.replace(",", "."))))
            except ValueError:
                unidades_invalidas += 1
        if registro.peso is None:
            registro.status = "sem_peso"
            registro.confianca = None
        else:
            registro.status = "com_peso"
            registro.fonte = registro.fonte or FONTE_PLANILHA

        anterior = posicao_por_sku.get(registro.id_sku)
        if anterior is not None:  # a última linha do mesmo SKU vale; a anterior é ignorada
            resultado.linhas[anterior].status = "duplicado_ignorado"
            resultado.linhas[anterior].motivo = f"id_sku repetido; vale a linha {registro.numero}"
        posicao_por_sku[registro.id_sku] = len(resultado.linhas)
        resultado.linhas.append(registro)
    if unidades_invalidas:
        resultado.avisos.append(f"{unidades_invalidas} linha(s) com unidades vendidas ilegíveis (contadas como 0)")
    return resultado


def resumir(resultado: ResultadoCsv, exemplos: int = 15) -> dict:
    """Contagens para o resumo antes de gravar."""
    por_status = {"com_peso": 0, "sem_peso": 0, "invalido": 0, "duplicado_ignorado": 0}
    for l in resultado.linhas:
        por_status[l.status] += 1
    suspeitos = [
        l for l in resultado.linhas
        if l.status == "com_peso" and not PESO_SUSPEITO_BAIXO_KG <= l.peso <= PESO_SUSPEITO_ALTO_KG
    ]
    return {
        "linhas": len(resultado.linhas),
        **por_status,
        "invalidos_exemplos": [(l.numero, l.id_sku or "?", l.motivo) for l in resultado.linhas if l.status == "invalido"][:exemplos],
        "suspeitos": [(l.numero, l.id_sku, float(l.peso), l.nome or "") for l in suspeitos][:exemplos],
        "total_suspeitos": len(suspeitos),
    }


def esta_protegido_do_git(caminho) -> bool:
    """True se o caminho está fora do repositório ou é ignorado pelo git (o repositório é público)."""
    try:
        relativo = Path(caminho).resolve().relative_to(RAIZ)
    except ValueError:
        return True
    try:
        resultado = subprocess.run(["git", "check-ignore", "-q", str(relativo)], cwd=RAIZ, capture_output=True)
    except OSError:
        return True
    return resultado.returncode in (0, 128)


# ----------------------------------------------------------------------------------------------------------
# Banco (asyncpg): consultas
# ----------------------------------------------------------------------------------------------------------
_COLUNAS = "id_sku, reference_code, nome, peso_kg, fonte, confianca, unidades_vendidas, atualizado_em, atualizado_por"

SQL_LISTAR = rf"""
    SELECT {_COLUNAS}
    FROM item_pesos
    WHERE ($1::text IS NULL OR nome ILIKE '%' || $1 || '%' ESCAPE '\' OR id_sku = $2 OR reference_code = $2)
      AND (NOT $3::boolean OR peso_kg IS NULL)
    ORDER BY unidades_vendidas DESC, id_sku
    LIMIT $4 OFFSET $5
"""
SQL_RESUMO = "SELECT COUNT(*) AS total, COUNT(peso_kg) AS com_peso FROM item_pesos"
SQL_ATUALIZAR = f"""
    UPDATE item_pesos
    SET peso_kg = $2, fonte = $3, confianca = $4, atualizado_em = now(), atualizado_por = $5
    WHERE id_sku = $1
    RETURNING {_COLUNAS}
"""
SQL_EXISTENTES = "SELECT id_sku, atualizado_por FROM item_pesos WHERE id_sku = ANY($1::text[])"
SQL_REGISTRAR_VISTO = """
    INSERT INTO item_pesos (id_sku, reference_code, nome, unidades_vendidas)
    VALUES ($1, $2, $3, $4)
    ON CONFLICT (id_sku) DO UPDATE SET
        unidades_vendidas = item_pesos.unidades_vendidas + EXCLUDED.unidades_vendidas,
        nome = COALESCE(item_pesos.nome, EXCLUDED.nome),
        reference_code = COALESCE(item_pesos.reference_code, EXCLUDED.reference_code)
"""
_UPSERT_COM_PESO = """
    INSERT INTO item_pesos (id_sku, reference_code, nome, peso_kg, fonte, confianca, unidades_vendidas, atualizado_em, atualizado_por)
    VALUES ($1, $2, $3, $4, $5, $6, $7, now(), $8)
    ON CONFLICT (id_sku) DO UPDATE SET
        reference_code = COALESCE(EXCLUDED.reference_code, item_pesos.reference_code),
        nome = COALESCE(EXCLUDED.nome, item_pesos.nome),
        peso_kg = EXCLUDED.peso_kg,
        fonte = EXCLUDED.fonte,
        confianca = EXCLUDED.confianca,
        unidades_vendidas = GREATEST(item_pesos.unidades_vendidas, EXCLUDED.unidades_vendidas),
        atualizado_em = now(),
        atualizado_por = EXCLUDED.atualizado_por
"""
# Por padrão a carga NUNCA sobrescreve um peso que um operador editou na tela (atualizado_por diferente da carga).
SQL_UPSERT_CARGA = _UPSERT_COM_PESO + "    WHERE item_pesos.atualizado_por IS NULL OR item_pesos.atualizado_por = $8\n"
SQL_UPSERT_CARGA_SOBRESCREVENDO = _UPSERT_COM_PESO
SQL_INSERIR_SEM_PESO = """
    INSERT INTO item_pesos (id_sku, reference_code, nome, unidades_vendidas)
    VALUES ($1, $2, $3, $4)
    ON CONFLICT (id_sku) DO NOTHING
"""


def _para_dict(registro) -> dict:
    d = dict(registro)
    if d.get("peso_kg") is not None:
        d["peso_kg"] = float(d["peso_kg"])
    if d.get("atualizado_em") is not None and hasattr(d["atualizado_em"], "isoformat"):
        d["atualizado_em"] = d["atualizado_em"].isoformat()
    return d


async def listar(conn, busca: Optional[str] = None, somente_sem_peso: bool = False, limite: int = 50, deslocamento: int = 0) -> dict:
    """Itens ordenados pelas unidades vendidas (mais vendidos primeiro); `somente_sem_peso` = a fila "sem peso"."""
    limite = max(1, min(int(limite), LIMITE_MAXIMO_LISTA))
    deslocamento = max(0, int(deslocamento))
    texto = (busca or "").strip()
    linhas = await conn.fetch(SQL_LISTAR, escapar_like(texto) if texto else None, texto or None, bool(somente_sem_peso), limite + 1, deslocamento)
    return {
        "itens": [_para_dict(r) for r in linhas[:limite]],
        "tem_mais": len(linhas) > limite,
        "limite": limite,
        "deslocamento": deslocamento,
    }


async def resumo(conn) -> dict:
    linha = await conn.fetchrow(SQL_RESUMO)
    total, com_peso = int(linha["total"]), int(linha["com_peso"])
    return {"total": total, "com_peso": com_peso, "sem_peso": total - com_peso}


async def atualizar_peso(conn, id_sku: str, peso, confianca, operador: str) -> Optional[dict]:
    """
    Grava o peso de um SKU e registra quem alterou e quando. peso None = tira o peso (o SKU volta para a fila).
    Devolve o item atualizado, ou None se o SKU não existe. Levanta ValueError para peso/confiança inválidos.
    """
    peso_kg = interpretar_peso(peso)
    confianca_ok = normalizar_confianca(confianca) if peso_kg is not None else None
    registro = await conn.fetchrow(
        SQL_ATUALIZAR, normalizar_id_sku(id_sku), peso_kg, FONTE_MANUAL if peso_kg is not None else None, confianca_ok, operador
    )
    return _para_dict(registro) if registro else None


async def registrar_skus_vistos(conn, itens: list) -> dict:
    """
    Faz os SKUs que apareceram em pedidos entrarem na fila "sem peso": SKU novo é inserido sem peso; SKU que já
    existe só soma as unidades (o peso e quem o alterou não mudam). `itens`: dicts com id_sku, quantidade (>= 1),
    e opcionalmente nome e reference_code. Chame uma vez por carga de pedidos (as unidades se somam).
    """
    agregados = {}
    for item in itens:
        id_sku = normalizar_id_sku(item.get("id_sku"))
        bruta = item.get("quantidade")
        quantidade = 1 if bruta is None else int(bruta)  # só a ausência vale 1: zero ou negativo é erro
        if quantidade < 1:
            raise ValueError(f"quantidade inválida para o SKU {id_sku}")
        atual = agregados.setdefault(id_sku, {"quantidade": 0, "nome": None, "reference_code": None})
        atual["quantidade"] += quantidade
        atual["nome"] = atual["nome"] or (str(item.get("nome") or "").strip() or None)
        atual["reference_code"] = atual["reference_code"] or (str(item.get("reference_code") or "").strip()[:60] or None)
    if not agregados:
        return {"novos": 0, "ja_existiam": 0}
    existentes = {r["id_sku"] for r in await conn.fetch(SQL_EXISTENTES, list(agregados))}
    async with conn.transaction():
        await conn.executemany(SQL_REGISTRAR_VISTO, [(k, v["reference_code"], v["nome"], v["quantidade"]) for k, v in agregados.items()])
    return {"novos": len(agregados) - len(existentes), "ja_existiam": len(existentes)}


# ----------------------------------------------------------------------------------------------------------
# Banco: carga inicial a partir do CSV revisado
# ----------------------------------------------------------------------------------------------------------
def separar_para_gravar(resultado: ResultadoCsv, incluir_sem_peso: bool = False) -> tuple:
    """(linhas com peso, linhas sem peso a inserir). Sem a opção, linhas sem peso são ignoradas."""
    com_peso = [l for l in resultado.linhas if l.status == "com_peso"]
    sem_peso = [l for l in resultado.linhas if l.status == "sem_peso"] if incluir_sem_peso else []
    return com_peso, sem_peso


async def prever_carga(conn, com_peso: list, sem_peso: list, sobrescrever_editados: bool = False) -> dict:
    """Só lê: quantos itens seriam novos, atualizados ou preservados (editados por operador na tela)."""
    ids = [l.id_sku for l in com_peso + sem_peso]
    existentes = {r["id_sku"]: r["atualizado_por"] for r in await conn.fetch(SQL_EXISTENTES, ids)} if ids else {}

    def editado_por_operador(id_sku):
        autor = existentes.get(id_sku)
        return autor is not None and autor != OPERADOR_CARGA_INICIAL

    novos = sum(1 for l in com_peso if l.id_sku not in existentes)
    preservados = 0 if sobrescrever_editados else sum(1 for l in com_peso if l.id_sku in existentes and editado_por_operador(l.id_sku))
    atualizados = sum(1 for l in com_peso if l.id_sku in existentes) - preservados
    return {
        "novos": novos,
        "atualizados": atualizados,
        "preservados_editados": preservados,
        "sem_peso_novos": sum(1 for l in sem_peso if l.id_sku not in existentes),
        "sem_peso_ja_existentes": sum(1 for l in sem_peso if l.id_sku in existentes),
    }


async def gravar_carga(conn, com_peso: list, sem_peso: list, sobrescrever_editados: bool = False) -> None:
    """Upsert numa única transação: ou grava tudo, ou nada (repetir é seguro)."""
    sql = SQL_UPSERT_CARGA_SOBRESCREVENDO if sobrescrever_editados else SQL_UPSERT_CARGA
    async with conn.transaction():
        if com_peso:
            await conn.executemany(
                sql,
                [(l.id_sku, l.reference_code, l.nome, l.peso, l.fonte, l.confianca, l.unidades, OPERADOR_CARGA_INICIAL) for l in com_peso],
            )
        if sem_peso:
            await conn.executemany(SQL_INSERIR_SEM_PESO, [(l.id_sku, l.reference_code, l.nome, l.unidades) for l in sem_peso])
