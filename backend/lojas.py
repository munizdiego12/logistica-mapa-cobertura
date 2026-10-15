"""
Lojas (Etapa 6a): cadastro com coordenadas fixas, validações e leitura do CSV de importação.

A tabela é criada SÓ pelo Alembic (migrations/versions/0007_lojas.py). As funções de banco recebem uma conexão asyncpg
(`conn`), como frota.py e item_pesos.py. A filial já faz parte do nome da loja (ex.: "Atacadão Guarujá"): não existe
coluna filial. Loja não é apagada: é desativada. As capacidades de peso e de volume são só informativas.

O CSV (exportado do Google Sheets em português ou do Google My Maps) só é lido aqui; quem grava é o script
scripts/carregar_lojas.py, com resumo antes e confirmação digitada.
"""
import csv
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

LAT_MIN, LAT_MAX = -34.0, 6.0
LNG_MIN, LNG_MAX = -74.0, -34.0
TAMANHO_NOME = 120
TAMANHO_ENDERECO = 250
OPERADOR_CARGA_INICIAL = "carga inicial (script)"

UFS = (
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ",
    "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
)
NOMES_DOS_ESTADOS = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA", "CEARA": "CE", "DISTRITO FEDERAL": "DF",
    "ESPIRITO SANTO": "ES", "GOIAS": "GO", "MARANHAO": "MA", "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS",
    "MINAS GERAIS": "MG", "PARA": "PA", "PARAIBA": "PB", "PARANA": "PR", "PERNAMBUCO": "PE", "PIAUI": "PI",
    "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO", "RORAIMA": "RR",
    "SANTA CATARINA": "SC", "SAO PAULO": "SP", "SERGIPE": "SE", "TOCANTINS": "TO",
}

MSG_NOME_VAZIO = "Informe o nome da loja."
MSG_NOME_REPETIDO = "Já existe uma loja com esse nome."
MSG_NAO_ENCONTRADA = "Loja não encontrada."
MSG_INATIVA = "Essa loja está desativada. Ative-a na tela \"Lojas\" ou escolha outra."
MSG_COORDENADAS_TROCADAS = (
    "A latitude e a longitude parecem estar trocadas. No Brasil a latitude fica entre -34 e 6 e a longitude entre -74 e -34: "
    "troque os dois valores."
)
MSG_FORA_DO_BRASIL = (
    "A latitude e a longitude estão fora do Brasil (latitude entre -34 e 6 e longitude entre -74 e -34). Confira os valores."
)

HORARIOS_PADRAO = {
    "manha": (time(8, 0), time(13, 0)),
    "tarde": (time(13, 0), time(18, 0)),
    "noite": (time(18, 0), time(21, 0)),
}


def _sem_acento(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")


def normalizar_cabecalho(texto) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _sem_acento(texto).lower()).strip("_")


def chave_do_nome(nome) -> str:
    """Chave de comparação do nome (sem diferença de maiúsculas nem de espaços), a mesma regra do índice único."""
    return " ".join(str(nome or "").split()).lower()


# ----------------------------------------------------------------------------------------------------------
# Valores
# ----------------------------------------------------------------------------------------------------------
def normalizar_nome(valor) -> str:
    nome = " ".join(str(valor or "").split())
    if not nome:
        raise ValueError(MSG_NOME_VAZIO)
    if len(nome) > TAMANHO_NOME:
        raise ValueError(f"O nome da loja pode ter até {TAMANHO_NOME} letras.")
    return nome


def normalizar_uf(valor, obrigatorio: bool = False) -> Optional[str]:
    """'SP', 'sp' ou 'São Paulo' -> 'SP'. Vazio devolve None (ou erro, se obrigatório). Qualquer outra coisa é erro."""
    texto = " ".join(_sem_acento(valor).upper().split())
    if not texto:
        if obrigatorio:
            raise ValueError("Informe o Estado da loja (ex.: SP).")
        return None
    uf = texto if texto in UFS else NOMES_DOS_ESTADOS.get(texto)
    if uf is None:
        raise ValueError("Estado inválido. Use a sigla (ex.: SP) ou o nome do Estado.")
    return uf


def normalizar_endereco(valor) -> Optional[str]:
    endereco = " ".join(str(valor or "").split())
    if not endereco:
        return None
    if len(endereco) > TAMANHO_ENDERECO:
        raise ValueError(f"O endereço pode ter até {TAMANHO_ENDERECO} letras.")
    return endereco


def _numero_ptbr(valor) -> float:
    """Número com vírgula ou ponto decimal ("-23,5614", "-23.5614", "1.234,5"). ValueError se não for número."""
    if isinstance(valor, bool):
        raise ValueError("não é número")
    if isinstance(valor, (int, float, Decimal)):
        numero = float(valor)
    else:
        texto = str(valor).replace("\xa0", " ").replace("−", "-").strip().replace(" ", "")
        if not re.fullmatch(r"-?[0-9.,]+", texto):
            raise ValueError("não é número")
        if "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".") if texto.rfind(",") > texto.rfind(".") else texto.replace(",", "")
        elif "," in texto:
            texto = texto.replace(",", ".")
        elif texto.count(".") > 1:
            raise ValueError("não é número")
        if not re.fullmatch(r"-?\d+(\.\d+)?", texto):
            raise ValueError("não é número")
        numero = float(texto)
    if numero != numero or numero in (float("inf"), float("-inf")):
        raise ValueError("não é número")
    return numero


def interpretar_coordenada(valor, nome: str) -> float:
    """Latitude ou longitude (vírgula decimal aceita). `nome` = 'latitude' ou 'longitude' (para a mensagem)."""
    try:
        return _numero_ptbr(valor)
    except ValueError:
        raise ValueError(f"A {nome} precisa ser um número, por exemplo -23,5614.") from None


def classificar_coordenadas(lat: float, lng: float) -> str:
    """'ok' (no Brasil), 'trocadas' (só ficam no Brasil se forem trocadas entre si) ou 'fora_do_brasil'."""
    if LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX:
        return "ok"
    if LAT_MIN <= lng <= LAT_MAX and LNG_MIN <= lat <= LNG_MAX:
        return "trocadas"
    return "fora_do_brasil"


def validar_coordenadas(lat, lng) -> tuple:
    """(lat, lng) em float, ou ValueError em linguagem do operador (fora do Brasil, trocadas, ilegíveis)."""
    latitude = interpretar_coordenada(lat, "latitude")
    longitude = interpretar_coordenada(lng, "longitude")
    estado = classificar_coordenadas(latitude, longitude)
    if estado == "trocadas":
        raise ValueError(MSG_COORDENADAS_TROCADAS)
    if estado == "fora_do_brasil":
        raise ValueError(MSG_FORA_DO_BRASIL)
    return latitude, longitude


def interpretar_capacidade(valor, rotulo: str) -> Optional[Decimal]:
    """Capacidade (peso ou volume), opcional e só informativa. Vazio = sem capacidade; zero, negativo ou texto = erro."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        numero = Decimal(str(_numero_ptbr(valor)))
    except (ValueError, InvalidOperation):
        raise ValueError(f"A capacidade de {rotulo} precisa ser um número maior que zero (ou deixe em branco).") from None
    if numero <= 0:
        raise ValueError(f"A capacidade de {rotulo} precisa ser maior que zero (ou deixe em branco).")
    if numero > Decimal("999999999"):
        raise ValueError(f"A capacidade de {rotulo} está alta demais. Confira o valor.")
    return numero.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def interpretar_hora(valor, rotulo: str) -> time:
    """'08:00', '8:30' ou '8' -> time. ValueError em linguagem do operador."""
    if isinstance(valor, time):
        return valor.replace(second=0, microsecond=0)
    texto = str(valor or "").strip()
    achou = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(?::\d{2})?", texto)
    if not achou:
        raise ValueError(f"O horário de {rotulo} precisa estar no formato 08:00.")
    hora, minuto = int(achou.group(1)), int(achou.group(2) or 0)
    if hora > 23 or minuto > 59:
        raise ValueError(f"O horário de {rotulo} precisa estar no formato 08:00.")
    return time(hora, minuto)


def montar_janelas(dados: dict) -> dict:
    """
    Janelas de entrega: manhã e tarde sempre (padrão 08-13 e 13-18, se em branco); noite (padrão 18-21) só se
    `usa_noite` for verdadeiro, senão fica sem janela. O início tem que ser antes do fim.
    """
    janelas = {}
    for turno, rotulo in (("manha", "manhã"), ("tarde", "tarde"), ("noite", "noite")):
        if turno == "noite" and dados.get("usa_noite", True) is False:
            janelas["janela_noite_inicio"] = janelas["janela_noite_fim"] = None
            continue
        padrao_inicio, padrao_fim = HORARIOS_PADRAO[turno]
        bruto_inicio, bruto_fim = dados.get(f"janela_{turno}_inicio"), dados.get(f"janela_{turno}_fim")
        inicio = padrao_inicio if bruto_inicio in (None, "") else interpretar_hora(bruto_inicio, f"início da {rotulo}")
        fim = padrao_fim if bruto_fim in (None, "") else interpretar_hora(bruto_fim, f"fim da {rotulo}")
        if inicio >= fim:
            raise ValueError(f"Na janela da {rotulo}, o início precisa ser antes do fim.")
        janelas[f"janela_{turno}_inicio"], janelas[f"janela_{turno}_fim"] = inicio, fim
    return janelas


def validar_loja(dados: dict) -> dict:
    """Valida e normaliza os dados de uma loja (criar ou editar). ValueError em linguagem do operador."""
    campos = {
        "nome": normalizar_nome(dados.get("nome")),
        "uf": normalizar_uf(dados.get("uf")),
        "endereco": normalizar_endereco(dados.get("endereco")),
        "ativo": bool(dados.get("ativo", True)),
        "capacidade_peso": interpretar_capacidade(dados.get("capacidade_peso"), "peso"),
        "capacidade_volume": interpretar_capacidade(dados.get("capacidade_volume"), "volume"),
    }
    campos["lat"], campos["lng"] = validar_coordenadas(dados.get("lat"), dados.get("lng"))
    campos.update(montar_janelas(dados))
    return campos


# ----------------------------------------------------------------------------------------------------------
# Banco (conexão asyncpg)
# ----------------------------------------------------------------------------------------------------------
_COLUNAS = (
    "id, nome, uf, endereco, lat, lng, ativo, capacidade_peso, capacidade_volume, "
    "janela_manha_inicio, janela_manha_fim, janela_tarde_inicio, janela_tarde_fim, janela_noite_inicio, janela_noite_fim, "
    "atualizado_em, atualizado_por"
)
_CAMPOS_GRAVAVEIS = (
    "nome", "uf", "endereco", "lat", "lng", "ativo", "capacidade_peso", "capacidade_volume",
    "janela_manha_inicio", "janela_manha_fim", "janela_tarde_inicio", "janela_tarde_fim", "janela_noite_inicio", "janela_noite_fim",
)


def _hora_texto(valor) -> Optional[str]:
    return None if valor is None else str(valor)[:5]


def para_dict(registro) -> dict:
    d = dict(registro)
    for chave in ("lat", "lng"):
        d[chave] = float(d[chave])
    for chave in ("capacidade_peso", "capacidade_volume"):
        d[chave] = None if d[chave] is None else float(d[chave])
    for chave in [c for c in d if c.startswith("janela_")]:
        d[chave] = _hora_texto(d[chave])
    d["ativo"] = bool(d["ativo"])
    d["usa_noite"] = d.get("janela_noite_inicio") is not None
    return d


async def listar(conn, incluir_inativas: bool = True) -> list:
    onde = "" if incluir_inativas else "WHERE ativo"
    linhas = await conn.fetch(f"SELECT {_COLUNAS} FROM lojas {onde} ORDER BY ativo DESC, lower(nome), id")
    return [para_dict(l) for l in linhas]


async def obter(conn, id_loja: int) -> Optional[dict]:
    linha = await conn.fetchrow(f"SELECT {_COLUNAS} FROM lojas WHERE id = $1", int(id_loja))
    return None if linha is None else para_dict(linha)


async def obter_ativa(conn, id_loja) -> dict:
    """A loja pedida, que precisa existir e estar ativa (para ser hub). ValueError em linguagem do operador."""
    try:
        loja = await obter(conn, int(id_loja))
    except (TypeError, ValueError):
        raise ValueError(MSG_NAO_ENCONTRADA) from None
    if loja is None:
        raise ValueError(MSG_NAO_ENCONTRADA)
    if not loja["ativo"]:
        raise ValueError(MSG_INATIVA)
    return loja


async def _nome_ja_existe(conn, nome: str, ignorar_id: Optional[int] = None) -> bool:
    achou = await conn.fetchval(
        "SELECT id FROM lojas WHERE lower(btrim(nome)) = lower($1) AND ($2::integer IS NULL OR id <> $2)", nome, ignorar_id,
    )
    return achou is not None


def _e_violacao_de_unicidade(erro: Exception) -> bool:
    return type(erro).__name__ == "UniqueViolationError" or "UNIQUE" in str(erro).upper()


async def criar(conn, dados: dict, rotulo_operador: str) -> dict:
    campos = validar_loja(dados)
    if await _nome_ja_existe(conn, campos["nome"]):
        raise ValueError(MSG_NOME_REPETIDO)
    colunas = ", ".join(_CAMPOS_GRAVAVEIS)
    marcadores = ", ".join(f"${i + 1}" for i in range(len(_CAMPOS_GRAVAVEIS) + 1))
    try:
        linha = await conn.fetchrow(
            f"INSERT INTO lojas ({colunas}, atualizado_por) VALUES ({marcadores}) RETURNING {_COLUNAS}",
            *[campos[c] for c in _CAMPOS_GRAVAVEIS], rotulo_operador,
        )
    except Exception as erro:  # dois cadastros do mesmo nome ao mesmo tempo
        if _e_violacao_de_unicidade(erro):
            raise ValueError(MSG_NOME_REPETIDO) from None
        raise
    return para_dict(linha)


async def atualizar(conn, id_loja: int, dados: dict, rotulo_operador: str) -> Optional[dict]:
    """Edita a loja inteira (inclusive ativar/desativar). None se a loja não existe. Nunca apaga."""
    campos = validar_loja(dados)
    if await conn.fetchval("SELECT id FROM lojas WHERE id = $1", int(id_loja)) is None:
        return None
    if await _nome_ja_existe(conn, campos["nome"], int(id_loja)):
        raise ValueError(MSG_NOME_REPETIDO)
    atribuicoes = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(_CAMPOS_GRAVAVEIS))
    n = len(_CAMPOS_GRAVAVEIS)
    try:
        linha = await conn.fetchrow(
            f"UPDATE lojas SET {atribuicoes}, atualizado_em = CURRENT_TIMESTAMP, atualizado_por = ${n + 2} WHERE id = $1 RETURNING {_COLUNAS}",
            int(id_loja), *[campos[c] for c in _CAMPOS_GRAVAVEIS], rotulo_operador,
        )
    except Exception as erro:
        if _e_violacao_de_unicidade(erro):
            raise ValueError(MSG_NOME_REPETIDO) from None
        raise
    return None if linha is None else para_dict(linha)


def texto_do_hover(loja: dict) -> list:
    """Linhas do hover do marcador: nome, endereço e UF, uma informação por linha e só o que existir."""
    return [t for t in (loja.get("nome"), loja.get("endereco"), loja.get("uf")) if t]


# ----------------------------------------------------------------------------------------------------------
# CSV de importação (Google Sheets em português ou Google My Maps)
# ----------------------------------------------------------------------------------------------------------
@dataclass
class LinhaLoja:
    numero: int  # linha do arquivo (1 = cabeçalho)
    nome: str = ""
    uf: Optional[str] = None
    endereco: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    status: str = "valida"  # valida | suspeita | invalida | duplicada_ignorada
    motivo: str = ""
    sem_endereco: bool = False
    sem_uf: bool = False
    suspeita: Optional[str] = None  # trocadas | fora_do_brasil


@dataclass
class ResultadoCsvLojas:
    linhas: list = field(default_factory=list)
    delimitador: str = ","
    codificacao: str = "utf-8"
    formato: str = "colunas"  # colunas | my_maps
    avisos: list = field(default_factory=list)


_ALIASES = {
    "nome": ("nome", "loja", "nome_da_loja", "name"),
    "estado": ("estado", "uf"),
    "endereco": ("endereco", "logradouro"),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lng", "lon", "long"),
    "wkt": ("wkt",),
    "descricao": ("description", "descricao"),
}


def _ler_texto(caminho: Path) -> tuple:
    dados = Path(caminho).read_bytes()
    try:
        return dados.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return dados.decode("cp1252", errors="replace"), "windows-1252"


def _indices(cabecalho: list) -> dict:
    normalizados = {normalizar_cabecalho(c): i for i, c in enumerate(cabecalho)}
    achados = {}
    for campo, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normalizados:
                achados[campo] = normalizados[alias]
                break
    return achados


def _formato(indices: dict) -> Optional[str]:
    if "wkt" in indices and "nome" in indices:
        return "my_maps"
    if {"nome", "latitude", "longitude"} <= set(indices):
        return "colunas"
    return None


_RE_PONTO = re.compile(r"POINT\s*Z?\s*\(\s*(-?[0-9.,]+)\s+(-?[0-9.,]+)(?:\s+-?[0-9.,]+)?\s*\)", re.IGNORECASE)


def interpretar_wkt(texto) -> tuple:
    """'POINT (-46.63 -23.55)' -> (latitude, longitude). No WKT a ordem é LONGITUDE e depois LATITUDE."""
    achou = _RE_PONTO.search(str(texto or ""))
    if not achou:
        raise ValueError("a coluna WKT não tem um ponto no formato POINT (longitude latitude)")
    lng = interpretar_coordenada(achou.group(1), "longitude")
    lat = interpretar_coordenada(achou.group(2), "latitude")
    return lat, lng


def ler_csv_lojas(caminho) -> ResultadoCsvLojas:
    """
    Lê o CSV de lojas sem gravar nada: UTF-8 (com ou sem BOM) ou Windows-1252; separador ';' ou ','; células entre aspas;
    vírgula ou ponto decimal; colunas Nome, Estado, Endereço, Latitude e Longitude (Endereço pode ficar em branco) ou o
    formato do Google My Maps (WKT, name, description). Classifica cada linha (válida, suspeita, inválida, duplicada).
    """
    texto, codificacao = _ler_texto(caminho)
    primeira = next((l for l in texto.splitlines() if l.strip()), "")
    escolhido, formato, indices = None, None, {}
    for delimitador in (";", ","):
        cabecalho = next(csv.reader([primeira], delimiter=delimitador), [])
        candidatos = _indices(cabecalho)
        achado = _formato(candidatos)
        if achado:
            escolhido, formato, indices = delimitador, achado, candidatos
            break
    if escolhido is None:
        raise ValueError(
            "não achei as colunas de lojas no cabeçalho: use Nome, Estado, Endereço, Latitude e Longitude "
            "(ou o formato do Google My Maps: WKT, name, description)"
        )

    resultado = ResultadoCsvLojas(delimitador=escolhido, codificacao=codificacao, formato=formato)
    leitor = csv.reader(texto.splitlines(), delimiter=escolhido)
    next(leitor)

    def celula(linha, campo):
        i = indices.get(campo)
        return linha[i].strip() if i is not None and i < len(linha) else ""

    for linha in leitor:
        if not any(c.strip() for c in linha):
            continue
        registro = LinhaLoja(numero=leitor.line_num)
        resultado.linhas.append(registro)
        try:
            registro.nome = normalizar_nome(celula(linha, "nome"))
        except ValueError as erro:
            registro.status, registro.motivo = "invalida", str(erro).rstrip(".").lower()
            continue
        try:
            registro.endereco = normalizar_endereco(celula(linha, "descricao" if formato == "my_maps" else "endereco"))
        except ValueError as erro:
            registro.status, registro.motivo = "invalida", str(erro).rstrip(".").lower()
            continue
        registro.sem_endereco = registro.endereco is None
        try:
            if formato == "my_maps":
                registro.lat, registro.lng = interpretar_wkt(celula(linha, "wkt"))
                registro.uf = normalizar_uf(celula(linha, "estado")) if "estado" in indices else None
            else:
                registro.uf = normalizar_uf(celula(linha, "estado"), obrigatorio=True)
                registro.lat = interpretar_coordenada(celula(linha, "latitude"), "latitude")
                registro.lng = interpretar_coordenada(celula(linha, "longitude"), "longitude")
        except ValueError as erro:
            registro.status, registro.motivo = "invalida", str(erro).rstrip(".")
            registro.lat = registro.lng = None
            continue
        registro.sem_uf = registro.uf is None
        estado = classificar_coordenadas(registro.lat, registro.lng)
        if estado != "ok":
            registro.status, registro.suspeita = "suspeita", estado
            registro.motivo = (
                f"latitude e longitude parecem trocadas (o certo seria latitude {registro.lng:g} e longitude {registro.lat:g})"
                if estado == "trocadas" else "coordenadas fora do Brasil"
            )

    # Nome repetido: a última linha vale; as anteriores são ignoradas (só entre as linhas que têm nome).
    ultima_por_nome = {}
    for posicao, registro in enumerate(resultado.linhas):
        if registro.nome and registro.status != "invalida":
            anterior = ultima_por_nome.get(chave_do_nome(registro.nome))
            if anterior is not None:
                resultado.linhas[anterior].status = "duplicada_ignorada"
                resultado.linhas[anterior].motivo = f"nome repetido; vale a linha {registro.numero}"
            ultima_por_nome[chave_do_nome(registro.nome)] = posicao
    return resultado


def resumir(resultado: ResultadoCsvLojas, exemplos: int = 10) -> dict:
    """Contagens do resumo antes de gravar: válidas, sem endereço, sem Estado, duplicadas e com coordenada suspeita."""
    linhas = resultado.linhas
    validas = [l for l in linhas if l.status == "valida"]
    suspeitas = [l for l in linhas if l.status == "suspeita"]
    return {
        "linhas": len(linhas),
        "validas": len(validas),
        "sem_endereco": sum(1 for l in validas if l.sem_endereco),
        "sem_uf": sum(1 for l in validas if l.sem_uf),
        "duplicadas": sum(1 for l in linhas if l.status == "duplicada_ignorada"),
        "suspeitas": len(suspeitas),
        "trocadas": [l for l in suspeitas if l.suspeita == "trocadas"],
        "fora_do_brasil": [l for l in suspeitas if l.suspeita == "fora_do_brasil"],
        "invalidas": [l for l in linhas if l.status == "invalida"],
        "exemplos": exemplos,
    }


def para_gravar(resultado: ResultadoCsvLojas) -> list:
    """Linhas que podem ser gravadas: só as válidas (suspeitas, inválidas e duplicadas ficam de fora)."""
    return [l for l in resultado.linhas if l.status == "valida"]


async def prever_carga(conn, linhas: list, sobrescrever_editados: bool = False) -> dict:
    """Quantas lojas seriam criadas, atualizadas ou deixadas como estão (editadas na tela) — sem gravar nada."""
    novas = atualizaveis = protegidas = 0
    for l in linhas:
        existente = await conn.fetchrow("SELECT id, atualizado_por FROM lojas WHERE lower(btrim(nome)) = lower($1)", l.nome)
        if existente is None:
            novas += 1
        elif sobrescrever_editados or existente["atualizado_por"] == OPERADOR_CARGA_INICIAL:
            atualizaveis += 1
        else:
            protegidas += 1
    return {"novas": novas, "atualizadas": atualizaveis, "protegidas": protegidas}


async def gravar_carga(conn, linhas: list, sobrescrever_editados: bool = False) -> dict:
    """
    Upsert por nome numa única transação (ou grava tudo, ou nada; repetir é seguro). Loja que um operador editou na tela
    NÃO é sobrescrita (a menos de sobrescrever_editados). Em loja existente, endereço e Estado em branco no CSV não
    apagam o que já está cadastrado.
    """
    novas = atualizadas = protegidas = 0
    async with conn.transaction():
        for l in linhas:
            existente = await conn.fetchrow("SELECT id, atualizado_por FROM lojas WHERE lower(btrim(nome)) = lower($1)", l.nome)
            if existente is None:
                await conn.fetchrow(
                    "INSERT INTO lojas (nome, uf, endereco, lat, lng, atualizado_por) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                    l.nome, l.uf, l.endereco, l.lat, l.lng, OPERADOR_CARGA_INICIAL,
                )
                novas += 1
            elif sobrescrever_editados or existente["atualizado_por"] == OPERADOR_CARGA_INICIAL:
                await conn.fetchrow(
                    "UPDATE lojas SET uf = COALESCE($2, uf), endereco = COALESCE($3, endereco), lat = $4, lng = $5, "
                    "atualizado_em = CURRENT_TIMESTAMP, atualizado_por = $6 WHERE id = $1 RETURNING id",
                    existente["id"], l.uf, l.endereco, l.lat, l.lng, OPERADOR_CARGA_INICIAL,
                )
                atualizadas += 1
            else:
                protegidas += 1
    return {"novas": novas, "atualizadas": atualizadas, "protegidas": protegidas}
