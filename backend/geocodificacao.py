"""
Conferência da geocodificação (funções puras, sem rede nem banco).

O endereço do pedido é procurado com até 5 candidatos e o escolhido precisa ser coerente com o próprio pedido:
mesma UF e cidade e, quando há CEP, perto do ponto esperado para aquele CEP (centro do prefixo de 5 dígitos do
CNEFE/IBGE, com a dispersão dele, ou a coordenada do CEP vinda da consulta de CEP). O que não passa vira
localização aproximada (centro do CEP ou do bairro), nunca VALIDO.
"""
import math
import time

from cnefe import LAT_MIN, LAT_MAX, LON_MIN, LON_MAX
from ibge import normalizar_nome

# Versão da chave do cache de geocodificação: as linhas gravadas antes desta conferência (sem o prefixo) deixam de
# ser lidas, sem apagar nada do banco.
CHAVE_VERSAO = "v2|"

VALIDO = "VALIDO"
APROXIMADO = "ALERTA_APROXIMADO"
ERRO = "ERRO_CEP_INVALIDO"

# Aproximado e erro ficam só na memória do processo, por pouco tempo (tenta de novo depois).
TTL_NAO_VALIDO_S = 3600

# Tolerância em volta do centro do prefixo do CEP: 1,25 x o raio que contém 90% dos endereços do prefixo,
# no mínimo 1,5 km e no máximo 15 km.
FATOR_DISPERSAO = 1.25
LIMITE_MINIMO_KM = 1.5
LIMITE_MAXIMO_KM = 15.0
# Só com a coordenada do CEP de 8 dígitos (prefixo fora da base do IBGE).
LIMITE_CEP_COMPLETO_KM = 2.0
# Pedido sem CEP: distância máxima do centro do bairro informado.
LIMITE_BAIRRO_KM = 3.0

_CAMPOS_CIDADE = ("city", "town", "municipality", "village", "county")
_CAMPOS_BAIRRO = ("suburb", "neighbourhood", "quarter", "city_district", "residential", "hamlet")


def distancia_km(a: tuple, b: tuple) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def limite_km(dispersao_km) -> float:
    try:
        dispersao = float(dispersao_km or 0)
    except (TypeError, ValueError):
        dispersao = 0.0
    return min(LIMITE_MAXIMO_KM, max(LIMITE_MINIMO_KM, FATOR_DISPERSAO * dispersao))


def dentro_do_brasil(lat, lon) -> bool:
    return lat is not None and lon is not None and LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX


def coordenada(candidato: dict):
    """(lat, lon) do candidato, ou None se faltar ou estiver fora do Brasil."""
    try:
        lat, lon = float(candidato["lat"]), float(candidato["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    return (lat, lon) if dentro_do_brasil(lat, lon) else None


def _endereco(candidato: dict) -> dict:
    endereco = candidato.get("address")
    return endereco if isinstance(endereco, dict) else {}


def uf_do_candidato(candidato: dict) -> str:
    """UF pelo código ISO do estado (BR-SP -> SP); vazio se o resultado não trouxer."""
    iso = str(_endereco(candidato).get("ISO3166-2-lvl4") or "")
    return iso[3:].upper() if iso.upper().startswith("BR-") else ""


def cidades_do_candidato(candidato: dict) -> set:
    endereco = _endereco(candidato)
    return {normalizar_nome(endereco[c]) for c in _CAMPOS_CIDADE if endereco.get(c)}


def bairros_do_candidato(candidato: dict) -> set:
    endereco = _endereco(candidato)
    return {normalizar_nome(endereco[c]) for c in _CAMPOS_BAIRRO if endereco.get(c)}


def coerente_com_local(candidato: dict, cidade: str, uf: str) -> bool:
    """Descarta candidato de outra UF ou de outra cidade. Sem a informação no resultado, não descarta por isso."""
    uf_candidato = uf_do_candidato(candidato)
    if uf and uf_candidato and uf_candidato != str(uf).strip().upper():
        return False
    cidade_norm = normalizar_nome(cidade)
    cidades = cidades_do_candidato(candidato)
    if cidade_norm and cidades and cidade_norm not in cidades:
        return False
    return coordenada(candidato) is not None


def escolher_por_referencia(candidatos: list, cidade: str, uf: str, referencia: tuple, limite: float):
    """Com CEP: entre os coerentes a até `limite` km da referência, o mais próximo (não o primeiro). None se nenhum."""
    melhores = []
    for c in candidatos or []:
        if not coerente_com_local(c, cidade, uf):
            continue
        ponto = coordenada(c)
        d = distancia_km(ponto, referencia)
        if d <= limite:
            melhores.append((d, ponto))
    return min(melhores)[1] if melhores else None


def _numero_norm(numero) -> str:
    return "".join(ch for ch in str(numero or "") if ch.isalnum()).upper()


def escolher_sem_cep(candidatos: list, cidade: str, uf: str, bairro: str, numero: str):
    """
    Sem CEP. Devolve (ponto, duvidosos): ponto = coordenada VALIDA (bairro igual ou, sem bairro, número da porta igual),
    ou None; duvidosos = coordenadas coerentes com a cidade que não puderam ser confirmadas.
    """
    coerentes = [c for c in candidatos or [] if coerente_com_local(c, cidade, uf)]
    bairro_norm = normalizar_nome(bairro)
    numero_norm = _numero_norm(numero)
    for c in coerentes:
        if bairro_norm:
            if bairro_norm in bairros_do_candidato(c):
                return coordenada(c), []
        elif numero_norm and _numero_norm(_endereco(c).get("house_number")) == numero_norm:
            return coordenada(c), []
    return None, [coordenada(c) for c in coerentes]


def mais_proximo(pontos: list, referencia: tuple, limite: float):
    perto = [(distancia_km(p, referencia), p) for p in pontos if p]
    perto = [x for x in perto if x[0] <= limite]
    return min(perto)[1] if perto else None


class CacheComValidade:
    """Cache em memória: VALIDO sem prazo (o processo reinicia a cada publicação); o resto expira em TTL_NAO_VALIDO_S."""

    def __init__(self, relogio=time.monotonic):
        self._itens = {}
        self._relogio = relogio

    def get(self, chave):
        item = self._itens.get(chave)
        if item is None:
            return None
        resultado, expira_em = item
        if expira_em is not None and self._relogio() >= expira_em:
            del self._itens[chave]
            return None
        return resultado

    def set(self, chave, resultado):
        expira_em = None if resultado[6] == VALIDO else self._relogio() + TTL_NAO_VALIDO_S
        self._itens[chave] = (resultado, expira_em)

    def __contains__(self, chave):
        return self.get(chave) is not None

    def clear(self):
        self._itens.clear()
