"""
Casamento do nome de uma loja (escrito por um operador, numa planilha) com as lojas cadastradas.

Usado pela carga de motoristas (`chave_da_loja`) e pelos pedidos (Etapa 7, coluna `loja`). Só stdlib, sem acesso a banco, para ser
importado tanto pelo app (que roda com backend/ no path) quanto pelos scripts (que rodam com a raiz do repositório no path).

Ordem do casamento (a mesma da carga de motoristas, sem a tabela de apelidos):
    1) nome de operação e código externo da loja (sem diferença de maiúsculas, acentos nem espaços);
    2) nome da loja, com as siglas de rede no início (ATC = Atacadão, SAMS = Sam's Club, CRFO = Carrefour), "Av" = "Avenida",
       sem acentos, hífens, apóstrofos nem pontuação.
Nome que casa com mais de uma loja ativa é ambíguo; loja só desativada conta como desativada.
"""
import re
import unicodedata
from typing import Optional

try:
    from lojas import chave_da_operacao
except ImportError:  # chamado pelos scripts (a raiz do repositório no path)
    from backend.lojas import chave_da_operacao

_ABREVIACOES = {"av": "avenida"}
# Siglas de rede só valem como PRIMEIRA palavra do nome (sem diferença de maiúsculas): ATC = Atacadão, SAMS = Sam's Club, CRFO = Carrefour.
_SIGLAS_DE_REDE = {"atc": ["atacadao"], "sams": ["sams", "club"], "crfo": ["carrefour"]}


def _sem_acento(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode("ascii")


def chave_da_loja(nome) -> str:
    """
    Chave de comparação do nome da loja: sem acentos, minúsculas, sem hífens, apóstrofos nem pontuação, espaços simples;
    siglas de rede no início valem o nome inteiro (ATC = Atacadão, SAMS/SAMs = Sam's Club, CRFO = Carrefour) e "Av" vale
    "Avenida" ("ATC Av das Torres" casa com "Atacadão Avenida das Torres"; "SAMS Campinas" com "Sam's Club Campinas").
    """
    texto = re.sub(r"['’`]", "", _sem_acento(nome).lower())
    palavras = re.sub(r"[^a-z0-9]+", " ", texto).split()
    if palavras and palavras[0] in _SIGLAS_DE_REDE:
        expandido = list(_SIGLAS_DE_REDE[palavras[0]])
        if expandido[-1] == "club" and palavras[1:2] == ["club"]:  # "Sams Club Campinas": o "club" já veio escrito
            expandido = expandido[:-1]
        palavras = expandido + palavras[1:]
    return " ".join(_ABREVIACOES.get(p, p) for p in palavras)


def casar_loja(nome, lojas_cadastradas: list) -> tuple:
    """
    (situação, loja): situação 'ok' (loja = o dict cadastrado), 'ambigua', 'desativada' ou 'nao_encontrada' (loja = None).
    `lojas_cadastradas`: dicts com id, nome, ativo e, se houver, nome_operacao e codigo_externo.
    """
    chave_op = chave_da_operacao(nome)
    chave_nome = chave_da_loja(nome)
    por_operacao, por_nome = [], []
    for loja in lojas_cadastradas:
        if chave_op and chave_op in (chave_da_operacao(loja.get("nome_operacao")), chave_da_operacao(loja.get("codigo_externo"))):
            por_operacao.append(loja)
        if chave_nome and chave_nome == chave_da_loja(loja.get("nome")):
            por_nome.append(loja)
    ativas_op = [l for l in por_operacao if l.get("ativo", True)]
    if len(ativas_op) == 1:
        return "ok", ativas_op[0]
    ativas = [l for l in por_nome if l.get("ativo", True)]
    if len(ativas_op) > 1 or len(ativas) > 1:
        return "ambigua", None
    if len(ativas) == 1:
        return "ok", ativas[0]
    if por_nome or por_operacao:
        return "desativada", None
    return "nao_encontrada", None
