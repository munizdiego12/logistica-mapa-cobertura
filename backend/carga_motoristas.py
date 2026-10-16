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
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

from backend import frota
from backend.lojas import OPERADOR_CARGA_INICIAL, _chave_do_cabecalho, _ler_texto, _sem_acento

TIPO_PASSEIO = "Carro de passeio"
TIPO_UTILITARIO = "Fiorino/Utilitário"

# Cabeçalhos reconhecidos POR NOME (a ordem não importa), sem diferença de maiúsculas, acentos, espaços ou separadores.
_ALIASES = {
    "codigo": ("codigo", "cod", "codmotorista", "codigomotorista", "codigodomotorista", "idmotorista"),
    "nome": ("nome", "motorista", "nomedomotorista", "name"),
    "tipo": ("tipodeveiculo", "tipoveiculo", "tipo", "veiculo", "modal"),
    "lojas": ("lojas", "loja", "lojasdomotorista", "lojasatendidas"),
    "diaria": ("diaria", "diariadomotorista", "valor", "valorrota", "valordiaria"),
    "telefone": ("telefone", "celular", "fone", "tel", "whatsapp"),
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


def chave_da_loja(nome) -> str:
    """Nome da loja sem acentos, em minúsculas e com espaços simples (o casamento com as lojas cadastradas)."""
    return " ".join(_sem_acento(nome).lower().split())


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
        if {"nome", "tipo"} <= set(candidatos):
            escolhido, indices, cabecalho_original = delimitador, candidatos, cabecalho
            break
    if escolhido is None:
        raise ValueError("não achei as colunas de motoristas no cabeçalho: use Código, Nome e Tipo de veículo (e, se quiser, Lojas, Diária e Telefone)")
    if "codigo" not in indices:
        raise ValueError("não achei a coluna Código no cabeçalho: o código é a chave da carga e é obrigatório")

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


def conferir_lojas(resultado: ResultadoCsvMotoristas, lojas_cadastradas: list) -> None:
    """Casa os nomes de loja de cada linha com as lojas cadastradas (nome normalizado). Loja desativada conta como não achada."""
    por_chave = {}
    for l in lojas_cadastradas:
        por_chave.setdefault(chave_da_loja(l["nome"]), l)
    resultado.lojas_conferidas = True
    for reg in resultado.linhas:
        reg.lojas_ids, reg.lojas_nao_encontradas = [], []
        for nome in reg.lojas_nomes:
            loja = por_chave.get(chave_da_loja(nome))
            if loja is None:
                reg.lojas_nao_encontradas.append(nome)
            elif not loja.get("ativo", True):
                reg.lojas_nao_encontradas.append(f"{nome} (desativada)")
            elif int(loja["id"]) not in reg.lojas_ids:
                reg.lojas_ids.append(int(loja["id"]))


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
        "repetidos": [(l.codigo, por_codigo[frota.chave_do_codigo(l.codigo)]) for l in linhas if l.status == "duplicada_ignorada"],
        "invalidas": [l for l in linhas if l.status == "invalida"],
        "com_telefone": sum(1 for l in validas if l.tem_telefone),
        "sem_telefone": sum(1 for l in validas if not l.tem_telefone),
        "telefone_invalido": [l for l in linhas if "telefone" in l.problemas],
        "com_valor": sum(1 for l in validas if l.valor is not None),
        "com_lojas": sum(1 for l in validas if l.lojas_nomes),
        "nomes_repetidos": sum(1 for q in Counter(chave_da_loja(l.nome) for l in validas).values() if q > 1),
        "exemplos": exemplos,
    }


def para_gravar(resultado: ResultadoCsvMotoristas) -> list:
    """Só as linhas válidas (inválidas e repetidas ficam de fora)."""
    return [l for l in resultado.linhas if l.status == "valida"]


async def ler_lojas(conn) -> list:
    """Lojas cadastradas (id, nome, ativo) para conferir os nomes da planilha. Só leitura."""
    linhas = await conn.fetch("SELECT id, nome, ativo FROM lojas")
    return [{"id": int(l["id"]), "nome": l["nome"], "ativo": bool(l["ativo"])} for l in linhas]


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
