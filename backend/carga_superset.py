"""
Carga de lojas a partir da exportação do Superset (Etapa 6c): leitura, agrupamento por `store_id`, ligação com as lojas já
cadastradas por proximidade (até 150 m), plano de gravação, resumo e gravação. O script `scripts/carregar_lojas.py` só
chama estas funções e imprime.

Colunas reconhecidas pelo NOME do cabeçalho (o resto, inclusive `map_store_location`, que é HTML, é ignorado):
    store_name = nome de operação | store_id = código externo | store_city = cidade | store_state = Estado (por extenso,
    sem acento, ou a sigla) | store_address = endereço | store_point = "latitude;longitude" numa célula só |
    store_is_active = TRUE/FALSE (inativas são ignoradas e contadas) | retailer_name = rede (só informativa).

Regras de cada loja do arquivo, nesta ordem:
    a) o código externo já existe no cadastro: só completa o que estiver vazio;
    b) exatamente UMA loja cadastrada a até 150 m: é a MESMA loja; recebe código externo e nome de operação, sem mudar
       nome, endereço nem coordenadas;
    c) mais de uma loja a até 150 m (ou a loja próxima já tem outro código, ou duas lojas do arquivo apontam para a mesma
       loja cadastrada): ambígua, não é aplicada e vai para o resumo;
    d) senão, é nova (nome = store_name como veio); se o nome (ou o nome de operação) já existir em outra loja distante,
       não é gravada e vai para o resumo.
Nada sobrescreve o que já está preenchido (nem o que um operador editou na tela): só campos vazios são completados.
"""
import csv
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from backend.lojas import (
    OPERADOR_CARGA_INICIAL,
    _ler_texto,
    _numero_ptbr,
    chave_da_operacao,
    chave_do_nome,
    classificar_coordenadas,
    normalizar_cabecalho,
    normalizar_cidade,
    normalizar_codigo_externo,
    normalizar_endereco,
    normalizar_nome,
    normalizar_nome_operacao,
    normalizar_uf,
)

RAIO_MESMA_LOJA_M = 150.0
OBRIGATORIAS = ("store_id", "store_name", "store_point")
CAMPOS = ("store_name", "store_id", "store_city", "store_state", "store_address", "store_point", "store_is_active", "retailer_name")
_VERDADEIRO = {"true", "t", "1", "sim", "s", "yes", "y", "verdadeiro"}
_FALSO = {"false", "f", "0", "nao", "n", "no", "falso"}


# ----------------------------------------------------------------------------------------------------------
# Leitura
# ----------------------------------------------------------------------------------------------------------
@dataclass
class LojaSuperset:
    codigo_externo: str
    nome_operacao: str
    linhas: list = field(default_factory=list)  # linhas do arquivo (1 = cabeçalho)
    cidade: Optional[str] = None
    uf: Optional[str] = None
    uf_original: str = ""
    endereco: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    rede: str = ""
    conflitos: list = field(default_factory=list)  # divergências entre as linhas do mesmo store_id


@dataclass
class ResultadoSuperset:
    delimitador: str = ","
    codificacao: str = "utf-8"
    colunas: dict = field(default_factory=dict)  # campo -> cabeçalho original reconhecido
    linhas_lidas: int = 0
    linhas_inativas: int = 0
    lojas: list = field(default_factory=list)  # ativas e com coordenada válida: as que podem ser gravadas
    inativas: int = 0  # store_id distintos em que TODAS as linhas são inativas
    repetidas: int = 0  # linhas a mais do mesmo store_id (já agrupadas)
    sem_coordenada: list = field(default_factory=list)  # [(código, nome, [linhas], motivo)]
    linhas_invalidas: list = field(default_factory=list)  # [(linha, motivo)] sem store_id, sem nome, valor ilegível...
    estados_nao_reconhecidos: Counter = field(default_factory=Counter)
    redes: Counter = field(default_factory=Counter)  # rede -> lojas
    conflitos: list = field(default_factory=list)  # [(código, nome, motivo)]
    avisos: list = field(default_factory=list)


def _indices(cabecalho: list) -> dict:
    normalizados = {}
    for i, c in enumerate(cabecalho):
        normalizados.setdefault(normalizar_cabecalho(c), i)
    return {campo: normalizados[campo] for campo in CAMPOS if campo in normalizados}


def detectar(texto: str) -> Optional[tuple]:
    """(delimitador, índices, cabeçalho original) se o cabeçalho for o da exportação do Superset; senão None."""
    primeira = next((l for l in texto.splitlines() if l.strip()), "")
    for delimitador in (",", ";", "\t"):
        cabecalho = next(csv.reader([primeira], delimiter=delimitador), [])
        indices = _indices(cabecalho)
        if all(c in indices for c in OBRIGATORIAS):
            return delimitador, indices, cabecalho
    return None


def e_exportacao_superset(caminho) -> bool:
    """O arquivo tem as colunas store_id, store_name e store_point no cabeçalho?"""
    texto, _ = _ler_texto(caminho)
    return detectar(texto) is not None


def interpretar_ativo(valor) -> Optional[bool]:
    """TRUE/FALSE (ou 1/0, sim/não); vazio vale ativo; outra coisa é None (ilegível)."""
    texto = " ".join(str(valor or "").split()).lower().replace("ã", "a")
    if not texto:
        return True
    if texto in _VERDADEIRO:
        return True
    if texto in _FALSO:
        return False
    return None


def interpretar_ponto(valor) -> tuple:
    """'-23,55;-46,63' (latitude;longitude) -> (lat, lng) no Brasil. ValueError curto se faltar, for ilegível ou cair fora."""
    texto = str(valor or "").strip()
    if not texto:
        raise ValueError("sem store_point")
    partes = [p for p in texto.replace("\n", " ").split(";")]
    if len(partes) != 2:
        raise ValueError("store_point fora do formato latitude;longitude")
    try:
        lat, lng = _numero_ptbr(partes[0]), _numero_ptbr(partes[1])
    except ValueError:
        raise ValueError("store_point com número ilegível") from None
    estado = classificar_coordenadas(lat, lng)
    if estado == "trocadas":
        raise ValueError("store_point com latitude e longitude trocadas")
    if estado == "fora_do_brasil":
        raise ValueError("store_point fora do Brasil")
    return lat, lng


def distancia_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distância em linha reta (haversine), em metros."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


def ler_superset(caminho) -> ResultadoSuperset:
    """
    Lê a exportação sem gravar nada (UTF-8 com ou sem BOM, ou Windows-1252; separador vírgula, ponto e vírgula ou tab).
    Linhas inativas são ignoradas e contadas; as ativas são agrupadas por store_id (a mesma loja aparece uma vez por
    operação). Dentro do grupo vale o primeiro valor preenchido de cada campo e o primeiro ponto válido.
    """
    texto, codificacao = _ler_texto(caminho)
    achado = detectar(texto)
    if achado is None:
        raise ValueError("não achei as colunas da exportação do Superset (store_id, store_name e store_point) no cabeçalho")
    delimitador, indices, cabecalho = achado
    resultado = ResultadoSuperset(delimitador=delimitador, codificacao=codificacao)
    resultado.colunas = {c: cabecalho[i].strip() for c, i in indices.items()}
    leitor = csv.reader(texto.splitlines(), delimiter=delimitador)
    next(leitor)

    def celula(linha, campo):
        i = indices.get(campo)
        return " ".join(linha[i].split()) if i is not None and i < len(linha) else ""

    grupos = {}  # chave do código -> dict com o que veio de cada linha
    ids_inativos = set()
    for linha in leitor:
        if not any(c.strip() for c in linha):
            continue
        resultado.linhas_lidas += 1
        numero = leitor.line_num
        try:
            codigo = normalizar_codigo_externo(celula(linha, "store_id"))
        except ValueError as erro:
            resultado.linhas_invalidas.append((numero, str(erro).rstrip(".").lower()))
            continue
        if codigo is None:
            resultado.linhas_invalidas.append((numero, "sem store_id"))
            continue
        chave = codigo.lower()
        ativo = interpretar_ativo(celula(linha, "store_is_active"))
        if ativo is None:
            resultado.linhas_invalidas.append((numero, f"store_is_active não reconhecido (store_id {codigo})"))
            continue
        if not ativo:
            resultado.linhas_inativas += 1
            ids_inativos.add(chave)
            continue
        try:
            nome = normalizar_nome_operacao(celula(linha, "store_name"))
            if nome is None:
                raise ValueError("sem store_name")
        except ValueError as erro:
            resultado.linhas_invalidas.append((numero, f"{str(erro).rstrip('.').lower()} (store_id {codigo})"))
            continue
        grupo = grupos.setdefault(chave, {"codigo": codigo, "linhas": [], "nome": nome, "pontos": [], "motivos_ponto": [], "textos": []})
        grupo["linhas"].append(numero)
        try:
            grupo["pontos"].append(interpretar_ponto(celula(linha, "store_point")))
        except ValueError as erro:
            grupo["motivos_ponto"].append(str(erro))
        grupo["textos"].append({
            "nome": nome, "cidade": celula(linha, "store_city"), "estado": celula(linha, "store_state"),
            "endereco": celula(linha, "store_address"), "rede": celula(linha, "retailer_name"),
        })

    ativos = set(grupos)
    resultado.inativas = len(ids_inativos - ativos)
    resultado.repetidas = sum(len(g["linhas"]) - 1 for g in grupos.values())
    for g in grupos.values():
        primeiro = lambda campo: next((t[campo] for t in g["textos"] if t[campo]), "")  # noqa: E731
        loja = LojaSuperset(codigo_externo=g["codigo"], nome_operacao=g["nome"], linhas=g["linhas"])
        try:
            loja.cidade = normalizar_cidade(primeiro("cidade"))
            loja.endereco = normalizar_endereco(primeiro("endereco"))
        except ValueError as erro:
            resultado.linhas_invalidas.append((g["linhas"][0], f"{str(erro).rstrip('.').lower()} (store_id {g['codigo']})"))
            continue
        loja.uf_original = primeiro("estado")
        try:
            loja.uf = normalizar_uf(loja.uf_original)
        except ValueError:
            loja.uf = None
            resultado.estados_nao_reconhecidos[loja.uf_original] += 1
        loja.rede = primeiro("rede")
        if loja.rede:
            resultado.redes[loja.rede] += 1
        if len({chave_da_operacao(t["nome"]) for t in g["textos"]}) > 1:
            loja.conflitos.append("nomes diferentes entre as linhas (vale o primeiro)")
        if not g["pontos"]:
            resultado.sem_coordenada.append((g["codigo"], g["nome"], g["linhas"], g["motivos_ponto"][0] if g["motivos_ponto"] else "sem store_point"))
            continue
        loja.lat, loja.lng = g["pontos"][0]
        if any(distancia_m(loja.lat, loja.lng, la, ln) > RAIO_MESMA_LOJA_M for la, ln in g["pontos"][1:]):
            loja.conflitos.append("coordenadas diferentes (mais de 150 m) entre as linhas (vale a primeira)")
        for motivo in loja.conflitos:
            resultado.conflitos.append((loja.codigo_externo, loja.nome_operacao, motivo))
        resultado.lojas.append(loja)
    return resultado


# ----------------------------------------------------------------------------------------------------------
# Plano (sem banco): o que fazer com cada loja do arquivo diante do cadastro
# ----------------------------------------------------------------------------------------------------------
def _chave_codigo(codigo) -> str:
    return " ".join(str(codigo or "").split()).lower()


@dataclass
class Acao:
    loja: LojaSuperset
    destino: Optional[dict] = None  # loja cadastrada (a, b)
    distancia_m: Optional[float] = None
    preencher: dict = field(default_factory=dict)  # coluna -> valor, só campos que estão vazios no cadastro
    motivo: str = ""
    candidatas: list = field(default_factory=list)  # [(nome cadastrado, distância em m)] das ambíguas


@dataclass
class Plano:
    ja_cadastradas: list = field(default_factory=list)  # a) pelo código externo
    por_proximidade: list = field(default_factory=list)  # b) a mesma loja a até 150 m
    novas: list = field(default_factory=list)  # d)
    ambiguas: list = field(default_factory=list)  # c)
    nome_em_conflito: list = field(default_factory=list)  # d) nome (ou nome de operação) já usado por outra loja distante
    operacao_em_conflito: list = field(default_factory=list)  # a, b) nome de operação já é de outra loja: só esse campo fica de fora

    @property
    def a_gravar(self) -> list:
        return self.ja_cadastradas + self.por_proximidade + self.novas


def _vazio(valor) -> bool:
    return valor is None or not str(valor).strip()


def planejar(cadastradas: list, lojas: list) -> Plano:
    """
    Decide o que fazer com cada loja do arquivo. `cadastradas`: dicts com id, nome, uf, endereco, cidade, lat, lng,
    codigo_externo, nome_operacao (e, se houver, nome_operacao_chave). Função pura: não mexe no banco.
    """
    plano = Plano()
    por_codigo = {_chave_codigo(c["codigo_externo"]): c for c in cadastradas if not _vazio(c.get("codigo_externo"))}
    nomes_usados = {chave_do_nome(c["nome"]): c["id"] for c in cadastradas}
    operacoes_usadas = {}
    for c in cadastradas:
        chave = c.get("nome_operacao_chave") or (chave_da_operacao(c["nome_operacao"]) if not _vazio(c.get("nome_operacao")) else "")
        if chave:
            operacoes_usadas[chave] = c["id"]

    # 1ª passada: classifica; guarda quem reivindica cada loja cadastrada (duas do arquivo na mesma = ambíguas)
    classificadas = []
    reivindicacoes = {}
    for loja in lojas:
        cadastrada = por_codigo.get(_chave_codigo(loja.codigo_externo))
        if cadastrada is not None:
            classificadas.append(("codigo", loja, cadastrada, 0.0, []))
            continue
        proximas = sorted(
            ((distancia_m(loja.lat, loja.lng, float(c["lat"]), float(c["lng"])), c) for c in cadastradas),
            key=lambda x: x[0],
        )
        proximas = [(d, c) for d, c in proximas if d <= RAIO_MESMA_LOJA_M]
        if len(proximas) == 1:
            d, c = proximas[0]
            classificadas.append(("proxima", loja, c, d, []))
            reivindicacoes.setdefault(c["id"], []).append(loja)
        elif len(proximas) > 1:
            classificadas.append(("ambigua", loja, None, None, [(c["nome"], d) for d, c in proximas]))
        else:
            classificadas.append(("nova", loja, None, None, []))

    # 2ª passada: aplica as regras e acumula os nomes usados
    for tipo, loja, cadastrada, d, candidatas in classificadas:
        if tipo == "ambigua":
            plano.ambiguas.append(Acao(loja, motivo="mais de uma loja cadastrada a até 150 m", candidatas=candidatas))
            continue
        if tipo == "proxima":
            if len(reivindicacoes[cadastrada["id"]]) > 1:
                plano.ambiguas.append(Acao(loja, motivo="outra loja do arquivo aponta para a mesma loja cadastrada", candidatas=[(cadastrada["nome"], d)]))
                continue
            if not _vazio(cadastrada.get("codigo_externo")):  # tem outro código (o mesmo teria caído em a)
                plano.ambiguas.append(Acao(loja, motivo=f"a loja cadastrada a {d:.0f} m já tem outro código externo", candidatas=[(cadastrada["nome"], d)]))
                continue
        if tipo in ("codigo", "proxima"):
            acao = Acao(loja, destino=cadastrada, distancia_m=d)
            if tipo == "proxima":
                acao.preencher["codigo_externo"] = loja.codigo_externo
            else:  # a) completa só o que está vazio
                for coluna, valor in (("uf", loja.uf), ("cidade", loja.cidade), ("endereco", loja.endereco)):
                    if _vazio(cadastrada.get(coluna)) and valor:
                        acao.preencher[coluna] = valor
            chave_op = chave_da_operacao(loja.nome_operacao)
            if _vazio(cadastrada.get("nome_operacao")):
                dono = operacoes_usadas.get(chave_op)
                if dono is not None and dono != cadastrada["id"]:
                    acao.motivo = "nome de operação já pertence a outra loja"
                    plano.operacao_em_conflito.append(acao)
                else:
                    acao.preencher["nome_operacao"] = loja.nome_operacao
                    acao.preencher["nome_operacao_chave"] = chave_op
                    operacoes_usadas[chave_op] = cadastrada["id"]
            (plano.ja_cadastradas if tipo == "codigo" else plano.por_proximidade).append(acao)
            continue
        # nova
        nome = normalizar_nome(loja.nome_operacao)
        chave_op = chave_da_operacao(loja.nome_operacao)
        if chave_do_nome(nome) in nomes_usados:
            plano.nome_em_conflito.append(Acao(loja, motivo="já existe outra loja (distante) com esse nome"))
        elif chave_op in operacoes_usadas:
            plano.nome_em_conflito.append(Acao(loja, motivo="já existe outra loja com esse nome de operação"))
        else:
            plano.novas.append(Acao(loja))
            nomes_usados[chave_do_nome(nome)] = -1
            operacoes_usadas[chave_op] = -1
    return plano


def resumir(resultado: ResultadoSuperset, plano: Optional[Plano] = None) -> dict:
    """Contagens do resumo antes de gravar. Sem `plano` (banco não consultado), só o que dá para saber pelo arquivo."""
    resumo = {
        "linhas": resultado.linhas_lidas,
        "linhas_inativas": resultado.linhas_inativas,
        "lojas_inativas": resultado.inativas,
        "lojas_ativas": len(resultado.lojas) + len(resultado.sem_coordenada),
        "repetidas": resultado.repetidas,
        "com_coordenada": len(resultado.lojas),
        "sem_coordenada": list(resultado.sem_coordenada),
        "linhas_invalidas": list(resultado.linhas_invalidas),
        "estados_nao_reconhecidos": dict(resultado.estados_nao_reconhecidos),
        "redes": dict(resultado.redes),
        "conflitos_no_arquivo": list(resultado.conflitos),
        "plano": plano is not None,
    }
    if plano is not None:
        resumo.update({
            "ja_cadastradas": len(plano.ja_cadastradas),
            "por_proximidade": len(plano.por_proximidade),
            "novas": len(plano.novas),
            "ambiguas": len(plano.ambiguas),
            "nome_em_conflito": len(plano.nome_em_conflito),
            "operacao_em_conflito": len(plano.operacao_em_conflito),
        })
    return resumo


# ----------------------------------------------------------------------------------------------------------
# Banco (conexão asyncpg)
# ----------------------------------------------------------------------------------------------------------
async def ler_cadastradas(conn) -> list:
    """Lojas cadastradas (todas, ativas ou não) para ligar e conferir nomes. Só leitura."""
    linhas = await conn.fetch(
        "SELECT id, nome, uf, endereco, cidade, lat, lng, ativo, atualizado_por, codigo_externo, nome_operacao, nome_operacao_chave FROM lojas"
    )
    return [dict(l) for l in linhas]


async def _aplicar(conn, plano: Plano) -> None:
    for acao in plano.ja_cadastradas + plano.por_proximidade:
        if not acao.preencher:
            continue
        colunas = list(acao.preencher)
        atribuicoes = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(colunas))
        valores = [acao.preencher[c] for c in colunas]
        # Só toca em quem alterou e quando se a loja é da carga; loja editada por operador mantém o registro dele.
        if acao.destino.get("atualizado_por") in (None, OPERADOR_CARGA_INICIAL):
            await conn.execute(
                f"UPDATE lojas SET {atribuicoes}, atualizado_em = CURRENT_TIMESTAMP, atualizado_por = ${len(colunas) + 2} WHERE id = $1",
                acao.destino["id"], *valores, OPERADOR_CARGA_INICIAL,
            )
        else:
            await conn.execute(f"UPDATE lojas SET {atribuicoes} WHERE id = $1", acao.destino["id"], *valores)
    for acao in plano.novas:
        l = acao.loja
        await conn.execute(
            "INSERT INTO lojas (nome, uf, endereco, cidade, lat, lng, codigo_externo, nome_operacao, nome_operacao_chave, atualizado_por) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            normalizar_nome(l.nome_operacao), l.uf, l.endereco, l.cidade, l.lat, l.lng, l.codigo_externo, l.nome_operacao,
            chave_da_operacao(l.nome_operacao), OPERADOR_CARGA_INICIAL,
        )


async def gravar_carga(conn, lojas: list) -> dict:
    """
    Lê o cadastro, refaz o plano e grava numa única transação (ou grava tudo, ou nada). Repetir é seguro: na segunda
    vez as lojas já têm o código externo e nada novo é feito. Devolve as contagens do que foi gravado.
    """
    async with conn.transaction():
        plano = planejar(await ler_cadastradas(conn), lojas)
        await _aplicar(conn, plano)
    return {
        "novas": len(plano.novas),
        "completadas": sum(1 for a in plano.ja_cadastradas if a.preencher),
        "ligadas": len(plano.por_proximidade),
        "ambiguas": len(plano.ambiguas),
        "nome_em_conflito": len(plano.nome_em_conflito),
    }
