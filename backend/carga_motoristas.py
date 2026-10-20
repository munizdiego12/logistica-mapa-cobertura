"""
Carga de motoristas a partir de um CSV (Etapa 6b): leitura, classificação das linhas, conferência das lojas, resumo e
gravação. O script `scripts/carregar_motoristas.py` só chama estas funções e imprime.

Regras:
    - a chave do upsert é SEMPRE o código do motorista; linha sem código é recusada e contada; nomes repetidos são aceitos
      desde que o código seja diferente; código repetido no arquivo é avisado (vale a última linha);
    - telefone é dado pessoal: o número só existe em memória até gravar (nunca vai para o resumo, para mensagem de erro nem
      para o `repr` da linha); linha com telefone inválido é RECUSADA e o resumo lista o CÓDIGO dela (nunca o número);
    - nunca sobrescreve um motorista que um operador editou na tela (--sobrescrever-editados muda isso); motorista que já
      existe não é reativado; os vínculos com lojas só são acrescentados, nunca removidos.
"""
import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from backend import frota
from backend.casamento_lojas import chave_da_loja  # noqa: F401 (o casamento mora em casamento_lojas, compartilhado com os pedidos)
from backend.lojas import OPERADOR_CARGA_INICIAL, _chave_do_cabecalho, _ler_texto, _sem_acento, chave_da_operacao

TIPO_PASSEIO = "Carro de passeio"
TIPO_UTILITARIO = "Fiorino/Utilitário"

# Cabeçalhos reconhecidos POR NOME (a ordem não importa), sem diferença de maiúsculas, acentos, espaços ou separadores.
_ALIASES = {
    "codigo": ("codigo", "cod", "id", "codmotorista", "codigomotorista", "codigodomotorista", "idmotorista"),
    "nome": ("nome", "nomemotorista", "motorista", "nomedomotorista", "name"),
    "tipo": ("tipodeveiculo", "tipoveiculo", "tipo", "veiculo", "modal"),
    "lojas": ("lojas", "loja", "lojasdomotorista", "lojasatendidas"),
    "diaria": ("diaria", "diariadomotorista", "valor", "valorrota", "valordiaria"),
    "telefone": ("telefone", "numero", "celular", "fone", "tel", "whatsapp"),
}
ROTULOS_DAS_COLUNAS = {
    "codigo": "Código", "nome": "Nome", "tipo": "Tipo de veículo", "lojas": "Lojas", "diaria": "Diária", "telefone": "Telefone",
}

MSG_SEM_CODIGO = "sem código (o código é a chave da carga)"


@dataclass
class LinhaMotorista:
    numero: int
    codigo: str = ""  # já normalizado (sem acentos nem espaços, maiúsculas)
    nome: str = ""
    tipo: Optional[str] = None  # nome oficial do tipo de veículo
    tipo_original: str = ""
    lojas_nomes: list = field(default_factory=list)
    lojas_ids: list = field(default_factory=list)
    lojas_nao_encontradas: list = field(default_factory=list)
    lojas_ambiguas: list = field(default_factory=list)  # nome que casa com mais de uma loja: o vínculo não é gravado
    lojas_por_apelido: list = field(default_factory=list)  # nomes da planilha ligados pela tabela de apelidos
    lojas_por_operacao: list = field(default_factory=list)  # nomes da planilha ligados pelo nome de operação ou código externo da loja
    valor: Optional[Decimal] = None
    telefone: Optional[str] = field(default=None, repr=False)  # só dígitos; nunca impresso
    status: str = "valida"  # valida | invalida | duplicada_ignorada
    problemas: list = field(default_factory=list)  # sem_codigo | nome | codigo | tipo | diaria | telefone
    motivos: list = field(default_factory=list)

    @property
    def tem_telefone(self) -> bool:
        return bool(self.telefone)

    @property
    def identificacao(self) -> str:
        """Como achar a linha na planilha, sem dado pessoal: o código; sem código, o número da linha."""
        return self.codigo or f"linha {self.numero}"

    def _recusar(self, problema: str, motivo: str) -> None:
        self.status = "invalida"
        self.problemas.append(problema)
        self.motivos.append(motivo)


@dataclass
class ResultadoCsvMotoristas:
    delimitador: str
    codificacao: str
    colunas: dict = field(default_factory=dict)  # campo -> cabeçalho original reconhecido
    linhas: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    lojas_conferidas: bool = False
    apelidos_invalidos: list = field(default_factory=list)  # [(nome na planilha, nome da loja, motivo)]


def reconhecer_tipo(valor) -> Optional[str]:
    """'Passeio', 'Carro de passeio', 'Utilitário', 'Fiorino', 'Fiorino/Utilitário'... -> nome oficial; None se não reconhece."""
    chave = "".join(c for c in _sem_acento(valor).lower() if c.isalnum())
    if not chave:
        return None
    tem_utilitario = "fiorino" in chave or "utilitario" in chave
    tem_passeio = "passeio" in chave or chave in ("carro", "carros", "carrodepasseio")
    if tem_utilitario == tem_passeio:  # os dois ou nenhum: não dá para decidir
        return None
    return TIPO_UTILITARIO if tem_utilitario else TIPO_PASSEIO


def _chave_simples(texto) -> str:
    return " ".join(_sem_acento(texto).lower().split())


def separar_lojas(texto) -> list:
    """'Atacadão A; Atacadão B | Atacadão C' -> nomes, sem repetir (mesma chave) e sem vazios."""
    nomes, vistos = [], set()
    for pedaco in str(texto or "").replace("|", ";").split(";"):
        nome = " ".join(pedaco.split())
        if nome and chave_da_loja(nome) not in vistos:
            vistos.add(chave_da_loja(nome))
            nomes.append(nome)
    return nomes


def _indices(cabecalho: list) -> dict:
    normalizados = {}
    for i, c in enumerate(cabecalho):
        normalizados.setdefault(_chave_do_cabecalho(c), i)
    achados = {}
    for campo, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in normalizados:
                achados[campo] = normalizados[alias]
                break
    return achados


def ler_csv_motoristas(caminho) -> ResultadoCsvMotoristas:
    """
    Lê o CSV sem gravar nada (UTF-8 com ou sem BOM, ou Windows-1252; separador ';' ou ','; vírgula ou ponto decimal na
    diária). Colunas: Código, Nome, Tipo de veículo (obrigatórias) e Lojas, Diária, Telefone (opcionais). Classifica cada
    linha e marca os códigos repetidos (vale a última linha).
    """
    texto, codificacao = _ler_texto(caminho)
    primeira = next((l for l in texto.splitlines() if l.strip()), "")
    escolhido, indices, cabecalho_original = None, {}, []
    for delimitador in (";", ","):
        cabecalho = next(csv.reader([primeira], delimiter=delimitador), [])
        candidatos = _indices(cabecalho)
        if "nome" in candidatos:
            escolhido, indices, cabecalho_original = delimitador, candidatos, cabecalho
            break
    if escolhido is None:
        raise ValueError("não achei a coluna do nome no cabeçalho: use Nome (ou Nome Motorista, Motorista), além de Código e Tipo de veículo")
    faltam = [rotulo for campo, rotulo in (("codigo", "Código (ou Codigo, ID)"), ("tipo", "Tipo de veículo (ou Veículo, Tipo)")) if campo not in indices]
    if faltam:
        raise ValueError(
            "faltam colunas obrigatórias no cabeçalho: " + "; ".join(faltam)
            + ". O código é a chave da carga e o tipo de veículo define a diária base; acrescente as colunas na planilha"
        )

    resultado = ResultadoCsvMotoristas(delimitador=escolhido, codificacao=codificacao)
    resultado.colunas = {campo: cabecalho_original[i].strip() for campo, i in indices.items()}
    leitor = csv.reader(texto.splitlines(), delimiter=escolhido)
    next(leitor)

    def celula(linha, campo):
        i = indices.get(campo)
        return linha[i].strip() if i is not None and i < len(linha) else ""

    for linha in leitor:
        if not any(c.strip() for c in linha):
            continue
        reg = LinhaMotorista(numero=leitor.line_num)
        resultado.linhas.append(reg)
        try:
            reg.codigo = frota.normalizar_codigo(celula(linha, "codigo"))
            if not reg.codigo:
                reg._recusar("sem_codigo", MSG_SEM_CODIGO)
        except ValueError as erro:
            reg._recusar("codigo", str(erro).rstrip(".").lower())
        try:
            reg.nome = frota.normalizar_nome_motorista(celula(linha, "nome"))
        except ValueError as erro:
            reg._recusar("nome", str(erro).rstrip(".").lower())
        reg.tipo_original = celula(linha, "tipo")
        reg.tipo = reconhecer_tipo(reg.tipo_original)
        if reg.tipo is None:
            reg._recusar("tipo", "tipo de veículo não reconhecido" if reg.tipo_original else "tipo de veículo em branco")
        reg.lojas_nomes = separar_lojas(celula(linha, "lojas")) if "lojas" in indices else []
        try:
            reg.valor = frota.interpretar_valor_proprio(celula(linha, "diaria")) if "diaria" in indices else None
        except ValueError as erro:
            reg._recusar("diaria", str(erro).rstrip(".").lower())
        try:
            reg.telefone = frota.normalizar_telefone(celula(linha, "telefone")) if "telefone" in indices else None
        except ValueError as erro:
            reg.telefone = None
            # motivo curto e fixo: nem a mensagem de exemplo da tela (que traz um número) vai para o resumo
            reg._recusar("telefone", "telefone sem DDD" if str(erro) == frota.MSG_TELEFONE_SEM_DDD else "telefone inválido")

    # Código repetido: a última linha válida vale; as anteriores são ignoradas.
    ultima = {}
    for posicao, reg in enumerate(resultado.linhas):
        if reg.status == "valida":
            anterior = ultima.get(frota.chave_do_codigo(reg.codigo))
            if anterior is not None:
                resultado.linhas[anterior].status = "duplicada_ignorada"
                resultado.linhas[anterior].motivos.append(f"código repetido; vale a linha {reg.numero}")
            ultima[frota.chave_do_codigo(reg.codigo)] = posicao
    return resultado


PALAVRAS_SEM_VALOR = {"de", "da", "do", "das", "dos", "e"}


def ler_apelidos(caminho) -> dict:
    """
    Lê o CSV de apelidos (colunas nome_na_planilha e nome_da_loja; as outras são ignoradas). Devolve
    {chave do nome na planilha: nome da loja}; linhas com nome_da_loja vazio são ignoradas (o motorista fica sem vínculo).
    """
    texto, _ = _ler_texto(caminho)
    linhas = list(csv.reader(texto.splitlines(), delimiter=";" if texto.splitlines()[:1] and texto.splitlines()[0].count(";") > texto.splitlines()[0].count(",") else ","))
    if not linhas:
        raise ValueError("o arquivo de apelidos está vazio")
    cabecalho = {_chave_do_cabecalho(c): i for i, c in enumerate(linhas[0])}
    if "nomenaplanilha" not in cabecalho or "nomedaloja" not in cabecalho:
        raise ValueError("o arquivo de apelidos precisa das colunas nome_na_planilha e nome_da_loja")
    a, b = cabecalho["nomenaplanilha"], cabecalho["nomedaloja"]
    apelidos = {}
    for linha in linhas[1:]:
        planilha = linha[a].strip() if a < len(linha) else ""
        loja = linha[b].strip() if b < len(linha) else ""
        if planilha and loja:
            apelidos[chave_da_loja(planilha)] = (planilha, loja)
    return apelidos


def _por_chave(lojas_cadastradas: list) -> dict:
    por_chave = {}
    for l in lojas_cadastradas:
        por_chave.setdefault(chave_da_loja(l["nome"]), []).append(l)
    return por_chave


def validar_apelidos(apelidos: dict, lojas_cadastradas: list) -> tuple:
    """({chave do nome na planilha: id da loja}, [(nome na planilha, nome da loja, motivo)]): a loja precisa existir, estar ativa e ser única."""
    por_chave = _por_chave(lojas_cadastradas)
    validos, invalidos = {}, []
    for chave, (planilha, loja) in (apelidos or {}).items():
        candidatas = por_chave.get(chave_da_loja(loja), [])
        ativas = [l for l in candidatas if l.get("ativo", True)]
        if len(ativas) == 1:
            validos[chave] = int(ativas[0]["id"])
        elif len(ativas) > 1:
            invalidos.append((planilha, loja, "o nome da loja casa com mais de uma loja"))
        elif candidatas:
            invalidos.append((planilha, loja, "loja desativada"))
        else:
            invalidos.append((planilha, loja, "loja inexistente"))
    return validos, invalidos


def _por_operacao(lojas_cadastradas: list) -> dict:
    """{chave (sem maiúsculas, acentos nem espaços): lojas} pelo nome de operação e pelo código externo."""
    por_chave = {}
    for l in lojas_cadastradas:
        for valor in (l.get("nome_operacao"), l.get("codigo_externo")):
            chave = chave_da_operacao(valor)
            if chave and l not in por_chave.setdefault(chave, []):
                por_chave[chave].append(l)
    return por_chave


def conferir_lojas(resultado: ResultadoCsvMotoristas, lojas_cadastradas: list, apelidos: Optional[dict] = None) -> None:
    """
    Casa os nomes de loja de cada linha com as lojas cadastradas, nesta ordem: 1) nome de operação e código externo
    (sem diferença de maiúsculas, acentos nem espaços); 2) nome da loja (chave normalizada: siglas de rede, Av = Avenida,
    sem hífen nem apóstrofo); 3) apelidos válidos (nome na planilha -> loja), só para o que os passos anteriores não
    resolveram. Nome que casa com mais de uma loja ativa em um passo é AMBÍGUO nesse passo (um apelido válido ainda pode
    resolver) e não vira vínculo; loja só desativada conta como não achada.
    """
    por_chave = _por_chave(lojas_cadastradas)
    por_operacao = _por_operacao(lojas_cadastradas)
    validos, resultado.apelidos_invalidos = validar_apelidos(apelidos, lojas_cadastradas)
    resultado.lojas_conferidas = True
    for reg in resultado.linhas:
        reg.lojas_ids, reg.lojas_nao_encontradas, reg.lojas_ambiguas = [], [], []
        reg.lojas_por_apelido, reg.lojas_por_operacao = [], []

        def ligar(id_loja):
            if int(id_loja) not in reg.lojas_ids:
                reg.lojas_ids.append(int(id_loja))

        for nome in reg.lojas_nomes:
            # 1) nome de operação ou código externo
            candidatas_op = por_operacao.get(chave_da_operacao(nome), [])
            ativas_op = [l for l in candidatas_op if l.get("ativo", True)]
            if len(ativas_op) == 1:
                ligar(ativas_op[0]["id"])
                reg.lojas_por_operacao.append(nome)
                continue
            # 2) nome da loja (com as siglas de rede)
            chave = chave_da_loja(nome)
            candidatas = por_chave.get(chave, [])
            ativas = [l for l in candidatas if l.get("ativo", True)]
            if len(ativas_op) > 1 or len(ativas) > 1:
                ambigua = True
            elif len(ativas) == 1:
                ligar(ativas[0]["id"])
                continue
            else:
                ambigua = False
            # 3) apelidos
            if chave in validos:
                ligar(validos[chave])
                reg.lojas_por_apelido.append(nome)
            elif ambigua:
                reg.lojas_ambiguas.append(nome)
            elif candidatas or candidatas_op:
                reg.lojas_nao_encontradas.append(f"{nome} (desativada)")
            else:
                reg.lojas_nao_encontradas.append(nome)


def _sem_sufixo(nome: str) -> str:
    return nome[: -len(" (desativada)")] if nome.endswith(" (desativada)") else nome


def sugerir_lojas(nome: str, lojas_cadastradas: list, maximo: int = 3) -> list:
    """Até `maximo` lojas ativas parecidas com o nome, pelas palavras em comum (sem artigos); sem palavra em comum, nenhuma."""
    palavras = {p for p in chave_da_loja(nome).split() if p not in PALAVRAS_SEM_VALOR and len(p) > 1}
    pontuadas = []
    for l in lojas_cadastradas:
        if not l.get("ativo", True):
            continue
        comum = len(palavras & {p for p in chave_da_loja(l["nome"]).split() if p not in PALAVRAS_SEM_VALOR})
        # "atacadao" (ou outra sigla de rede) sozinho não diz nada: precisa de pelo menos uma palavra a mais em comum
        especificas = len((palavras - {"atacadao", "sams", "club", "carrefour"}) & set(chave_da_loja(l["nome"]).split()))
        if comum > 0 and especificas > 0:
            pontuadas.append((-comum, -especificas, l["nome"]))
    return [nome_loja for _, _, nome_loja in sorted(pontuadas)[:maximo]]


def exportar_apelidos(caminho, resultado: ResultadoCsvMotoristas, lojas_cadastradas: list) -> int:
    """
    Escreve o modelo de apelidos (UTF-8, vírgula) só com os nomes de loja não encontrados ou ambíguos: nome_na_planilha,
    motoristas (quantidade), sugestoes (até 3 lojas parecidas, separadas por " | ") e nome_da_loja (vazia, para preencher).
    Não contém dado pessoal. Recusa sobrescrever um arquivo que já existe (ele pode já estar preenchido). Devolve quantas linhas.
    """
    caminho = Path(caminho)
    if caminho.exists():
        raise ValueError(f"{caminho} já existe: escolha outro nome para não perder o que já foi preenchido")
    contagem = Counter()
    for l in resultado.linhas:
        if l.status == "valida":
            for n in l.lojas_nao_encontradas:
                contagem[_sem_sufixo(n)] += 1
            for n in l.lojas_ambiguas:
                contagem[n] += 1
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["nome_na_planilha", "motoristas", "sugestoes", "nome_da_loja"])
        for nome, quantas in sorted(contagem.items(), key=lambda x: (-x[1], x[0])):
            escritor.writerow([nome, quantas, " | ".join(sugerir_lojas(nome, lojas_cadastradas)), ""])
    return len(contagem)


def resumir(resultado: ResultadoCsvMotoristas, exemplos: int = 10) -> dict:
    """Contagens do resumo antes de gravar. Telefone só em contagens; as linhas recusadas por telefone saem pelo CÓDIGO."""
    linhas = resultado.linhas
    validas = [l for l in linhas if l.status == "valida"]
    por_codigo = {}
    for l in linhas:
        if l.codigo:
            por_codigo.setdefault(frota.chave_do_codigo(l.codigo), []).append(l.numero)
    return {
        "linhas": len(linhas),
        "validas": len(validas),
        "sem_codigo": [l for l in linhas if "sem_codigo" in l.problemas],
        "tipos_nao_reconhecidos": Counter(l.tipo_original or "(em branco)" for l in linhas if "tipo" in l.problemas),
        "lojas_conferidas": resultado.lojas_conferidas,
        "lojas_nao_encontradas": Counter(n for l in validas for n in l.lojas_nao_encontradas),
        "lojas_ambiguas": Counter(n for l in validas for n in l.lojas_ambiguas),
        "apelidos_invalidos": list(resultado.apelidos_invalidos),
        "ligados_por_apelido": sum(1 for l in validas if l.lojas_por_apelido),
        "ligados_por_operacao": sum(1 for l in validas if l.lojas_por_operacao),
        "sem_algum_vinculo": sum(1 for l in validas if l.lojas_nao_encontradas or l.lojas_ambiguas),
        "repetidos": [(l.codigo, por_codigo[frota.chave_do_codigo(l.codigo)]) for l in linhas if l.status == "duplicada_ignorada"],
        "invalidas": [l for l in linhas if l.status == "invalida"],
        "com_telefone": sum(1 for l in validas if l.tem_telefone),
        "sem_telefone": sum(1 for l in validas if not l.tem_telefone),
        "telefone_invalido": [l for l in linhas if "telefone" in l.problemas],
        "com_valor": sum(1 for l in validas if l.valor is not None),
        "com_lojas": sum(1 for l in validas if l.lojas_nomes),
        "nomes_repetidos": sum(1 for q in Counter(_chave_simples(l.nome) for l in validas).values() if q > 1),
        "exemplos": exemplos,
    }


def para_gravar(resultado: ResultadoCsvMotoristas) -> list:
    """Só as linhas válidas (inválidas e repetidas ficam de fora)."""
    return [l for l in resultado.linhas if l.status == "valida"]


async def ler_lojas(conn) -> list:
    """Lojas cadastradas (id, nome, nome de operação, código externo, ativo) para conferir os nomes da planilha. Só leitura."""
    linhas = await conn.fetch("SELECT id, nome, nome_operacao, codigo_externo, ativo FROM lojas")
    return [
        {"id": int(l["id"]), "nome": l["nome"], "nome_operacao": l["nome_operacao"], "codigo_externo": l["codigo_externo"], "ativo": bool(l["ativo"])}
        for l in linhas
    ]


async def _existente(conn, codigo: str):
    return await conn.fetchrow("SELECT id, atualizado_por FROM motoristas WHERE lower(btrim(codigo)) = lower($1)", codigo)


def _pode_atualizar(existente, sobrescrever_editados: bool) -> bool:
    return sobrescrever_editados or existente["atualizado_por"] == OPERADOR_CARGA_INICIAL


async def prever_carga(conn, linhas: list, sobrescrever_editados: bool = False) -> dict:
    """Quantos motoristas seriam criados, atualizados ou deixados como estão (editados na tela), sem gravar nada."""
    novos = atualizaveis = protegidos = 0
    for l in linhas:
        existente = await _existente(conn, l.codigo)
        if existente is None:
            novos += 1
        elif _pode_atualizar(existente, sobrescrever_editados):
            atualizaveis += 1
        else:
            protegidos += 1
    return {"novos": novos, "atualizados": atualizaveis, "protegidos": protegidos}


async def _acrescentar_vinculos(conn, id_motorista: int, ids_lojas: list) -> int:
    ja = {int(r["loja_id"]) for r in await conn.fetch("SELECT loja_id FROM motorista_lojas WHERE motorista_id = $1", id_motorista)}
    novos = [i for i in ids_lojas if i not in ja]
    for id_loja in novos:
        await conn.execute(
            "INSERT INTO motorista_lojas (motorista_id, loja_id, atualizado_por) VALUES ($1, $2, $3)",
            id_motorista, id_loja, OPERADOR_CARGA_INICIAL,
        )
    return len(novos)


async def gravar_carga(conn, linhas: list, sobrescrever_editados: bool = False) -> dict:
    """
    Upsert por código numa única transação (ou grava tudo, ou nada; repetir é seguro). Motorista que um operador editou na
    tela NÃO é sobrescrito; motorista existente não é reativado; telefone/diária em branco no CSV não apagam o que já está
    cadastrado; vínculos com lojas só são acrescentados.
    """
    novos = atualizados = protegidos = vinculos = 0
    async with conn.transaction():
        for l in linhas:
            existente = await _existente(conn, l.codigo)
            if existente is None:
                criado = await conn.fetchrow(
                    "INSERT INTO motoristas (codigo, nome, tipo_veiculo, valor_rota, telefone, ativo, atualizado_por) "
                    "VALUES ($1, $2, $3, $4, $5, TRUE, $6) RETURNING id",
                    l.codigo, l.nome, l.tipo, l.valor, l.telefone, OPERADOR_CARGA_INICIAL,
                )
                novos += 1
                vinculos += await _acrescentar_vinculos(conn, int(criado["id"]), l.lojas_ids)
            elif _pode_atualizar(existente, sobrescrever_editados):
                await conn.fetchrow(
                    "UPDATE motoristas SET nome = $2, tipo_veiculo = $3, valor_rota = COALESCE($4, valor_rota), "
                    "telefone = COALESCE($5, telefone), atualizado_em = CURRENT_TIMESTAMP, atualizado_por = $6 WHERE id = $1 RETURNING id",
                    existente["id"], l.nome, l.tipo, l.valor, l.telefone, OPERADOR_CARGA_INICIAL,
                )
                atualizados += 1
                vinculos += await _acrescentar_vinculos(conn, int(existente["id"]), l.lojas_ids)
            else:
                protegidos += 1
    return {"novos": novos, "atualizados": atualizados, "protegidos": protegidos, "vinculos": vinculos}
