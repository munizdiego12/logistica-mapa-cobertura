"""
Regras da cobertura por raio (Etapa 2b, passo 3): classificação Total/Parcial, formatação do bairro e
junção das duas fontes (prefixos do CNEFE e faixas manuais).

Módulo puro (sem banco nem rede): o SQL fica em database.py e as decisões ficam aqui, para serem testadas.
Não importa nada de `backend.*` porque o app roda com o diretório backend/ na raiz do path.
"""
import math
import re

FONTE_CNEFE = "IBGE, CNEFE 2022"
ATRIBUICAO_CNEFE = f"Fonte: {FONTE_CNEFE}"

LEGENDA_COBERTURA = (
    "Cobertura — Total: pelo menos 90% dos endereços do prefixo de CEP ficam dentro do raio; "
    "Parcial: parte relevante do prefixo pode ficar fora do raio (inclui faixas cadastradas "
    "manualmente, sem medida de dispersão)."
)

TOTAL = "Total"
PARCIAL = "Parcial"

PRECISAO_PREFIXO = "prefixo"
PRECISAO_FAIXA = "faixa"

# Acima desse prazo em km o SLA passa de 1 para 2 dias (mesmo corte no backend e no CSV do frontend).
LIMITE_PRAZO_1_DIA_KM = 12.0
# Abaixo desse percentual a localidade mais frequente do prefixo não representa o prefixo.
LIMITE_LOCALIDADE_REPRESENTATIVA_PCT = 50.0

_PREPOSICOES = {"da", "das", "de", "do", "dos", "e", "em", "na", "nas", "no", "nos"}
_NUMERO_ROMANO = re.compile(r"^(?=[IVXLCDM]{2,6}$)M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def formatar_titulo(texto) -> str:
    """'ZONA CIVICO ADMINISTRATIVA' -> 'Zona Civico Administrativa'; da/de/do... em minúsculas; romanos mantidos."""
    palavras = []
    for i, palavra in enumerate(str(texto or "").split()):
        if _NUMERO_ROMANO.match(palavra):
            palavras.append(palavra)
        elif i > 0 and palavra.lower() in _PREPOSICOES:
            palavras.append(palavra.lower())
        else:
            palavras.append("-".join(parte.capitalize() for parte in palavra.split("-")))
    return " ".join(palavras)


def caixa_do_raio(lat: float, lon: float, raio_km: float) -> tuple:
    """(lat_min, lat_max, lon_min, lon_max) de uma caixa que contém o círculo: filtro barato antes da distância."""
    delta_lat = raio_km / 111.32
    delta_lon = raio_km / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    return lat - delta_lat, lat + delta_lat, lon - delta_lon, lon + delta_lon


def classificar_cobertura(distancia_km: float, dispersao_km: float, raio_km: float) -> str:
    """Total se o círculo de 90% dos endereços do prefixo cabe no raio (distância + dispersão <= raio); senão Parcial."""
    return TOTAL if distancia_km + dispersao_km <= raio_km else PARCIAL


def _faixa_cep(cep_inicial, cep_final) -> tuple:
    ini, fim = str(cep_inicial).zfill(8), str(cep_final).zfill(8)
    return ini, fim, f"{ini[:5]}-{ini[5:]} a {fim[:5]}-{fim[5:]}"


def _dias_sla(distancia_km: float) -> int:
    return 1 if distancia_km <= LIMITE_PRAZO_1_DIA_KM else 2


def montar_ponto_prefixo(linha: dict, raio_km: float) -> dict:
    """Ponto de cobertura a partir de uma linha de cep_prefixos (já com cidade e distancia_km)."""
    prefixo = str(linha["prefixo"]).zfill(5)
    distancia = float(linha["distancia_km"])
    dispersao = float(linha["dispersao_km"])
    bairro = formatar_titulo(linha.get("localidade")) or ""
    pct = linha.get("localidade_pct")
    aproximado = bool(bairro) and (pct is None or float(pct) < LIMITE_LOCALIDADE_REPRESENTATIVA_PCT)
    if aproximado:
        bairro = f"{bairro} e outros"  # a localidade escolhida não representa a maioria dos endereços do prefixo
    cep_ini, cep_fim, faixa = _faixa_cep(prefixo + "000", prefixo + "999")
    return {
        "ibge": linha.get("cod_municipio"),
        "uf": linha["uf"],
        "cidade": linha.get("cidade") or "",
        "bairro": bairro,
        "bairro_aproximado": aproximado,
        "cep_inicial": cep_ini,
        "cep_final": cep_fim,
        "faixa_completa": faixa,
        "distancia_km": round(distancia, 2),
        "dispersao_km": round(dispersao, 2),
        "n_enderecos": int(linha.get("n_enderecos") or 0),
        "dias_sla": _dias_sla(distancia),
        "lat": float(linha["lat"]),
        "lon": float(linha["lon"]),
        "cobertura": classificar_cobertura(distancia, dispersao, raio_km),
        "precisao": PRECISAO_PREFIXO,
    }


def marcar_ponto_faixa(ponto: dict) -> dict:
    """Linha de ceps_reais (faixa manual): sem dispersão não dá para garantir Total, então é sempre Parcial."""
    return {**ponto, "cobertura": PARCIAL, "precisao": PRECISAO_FAIXA, "bairro_aproximado": False}


def combinar_cobertura(prefixos: list, faixas: list, ufs_com_prefixos, raio_km: float) -> list:
    """
    Junta as duas fontes ordenando por distância. As faixas manuais só entram para UFs que ainda
    não têm nenhum prefixo carregado (evita contar a mesma região duas vezes e mantém, por exemplo,
    o Entorno do DF em GO enquanto GO não for carregado).
    """
    ufs = set(ufs_com_prefixos)
    pontos = [montar_ponto_prefixo(p, raio_km) for p in prefixos]
    pontos += [marcar_ponto_faixa(f) for f in faixas if f.get("uf") not in ufs]
    pontos.sort(key=lambda p: p["distancia_km"])
    return pontos


def resumir_cobertura(pontos: list) -> dict:
    """Contagens para o painel e a exportação, e se algum ponto veio do CNEFE (exige a atribuição)."""
    total = sum(1 for p in pontos if p.get("cobertura") == TOTAL)
    parcial = sum(1 for p in pontos if p.get("cobertura") == PARCIAL)
    return {
        "total": total,
        "parcial": parcial,
        "usa_cnefe": any(p.get("precisao") == PRECISAO_PREFIXO for p in pontos),
    }
