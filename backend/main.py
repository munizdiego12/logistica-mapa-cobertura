import io
import json
import logging
import math
import time
import asyncio
import uuid
from datetime import date
from typing import List, Optional, Dict, Any, Union

import httpx
import requests
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

import database
import cobertura
import item_pesos
import item_pesos_importacao
import itens_fonte
import frota
import lojas
import matriz
import pedidos_fonte
import roteirizacao
import rotas_realizadas
import setores as modulo_setores
from logistica.costs import calcular_custo_rota
from database import get_db, Operador, init_db
from config import OPERATOR_INVITE_CODE, HISTORICO_DIAS, JOBS_TTL_HORAS, JOBS_MAX
from auth import (
    gerar_hash_senha,
    verificar_senha_hash,
    criar_token_acesso,
    obter_operador_atual
)

app = FastAPI(title="Zubale Routing Core - Dynamic National Engine")

# O httpx registra a URL de cada chamada (com o endereço do pedido na busca) quando o nível é INFO: mantém em WARNING.
for _nome_log in ("httpx", "httpcore"):
    logging.getLogger(_nome_log).setLevel(logging.WARNING)

# Respostas a partir de ~1 KB saem compactadas (a cobertura de milhares de faixas cai de ~1,2 MB para ~60 KB). Fica ANTES do CORS
# na pilha, então o CORS continua sendo a camada de fora e os cabeçalhos dele seguem em todas as respostas.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def _on_startup():
    await database.init_db()

# Teto de pedidos por viagem de cada tipo de veículo (agrupamento atual; o valor base da rota vem do cadastro de tipos).
MODAIS_PADRAO_DEFAULT = {
    'Carro de passeio': {'capacidade': 5},
    'Fiorino/Utilitário': {'capacidade': 12},
}

CORES_ROTAS = [
    '#3B82F6', '#10B981', '#F59E0B', '#EF4444', 
    '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16',
    '#F97316', '#14B8A6', '#6366F1', '#D946EF'
]

def haversine_distance(coord1: tuple, coord2: tuple) -> float:
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

_GEOCODE_CACHE_MEMORIA: Dict[str, tuple] = {}

# Controla o rate-limit do Nominatim (1 req/s) de forma assíncrona e SEGURA
# mesmo quando várias geocodificações rodam "em paralelo" (asyncio.gather).
_nominatim_lock = asyncio.Lock()
_nominatim_ultima_chamada = 0.0

# BrasilAPI não exige 1 req/s, então aqui só limitamos concorrência (não velocidade).
_brasilapi_semaforo = asyncio.Semaphore(8)


def _chave_cache(rua, numero, bairro, cep, cidade, uf):
    return "|".join([str(x or "").strip().lower() for x in [rua, numero, bairro, cep, cidade, uf]])


async def _respeitar_rate_limit_nominatim():
    global _nominatim_ultima_chamada
    async with _nominatim_lock:
        agora = time.monotonic()
        espera = 1.05 - (agora - _nominatim_ultima_chamada)
        if espera > 0:
            await asyncio.sleep(espera)
        _nominatim_ultima_chamada = time.monotonic()


async def geocode_async(client: httpx.AsyncClient, rua: str = "", numero: str = "",
                         bairro: str = "", cep: str = "", cidade: str = "", uf: str = ""):
    """
    Versão assíncrona da geocodificação. Ordem de prioridade:
    1) Cache em memória (instantâneo, válido durante a execução do processo)
    2) Cache Postgres (instantâneo, sobrevive a reinícios do servidor)
    3) Endereço completo via Nominatim (preciso, mas limitado a 1 req/s)
    4) CEP via BrasilAPI (aproximado, mas pode rodar em paralelo)
    5) Bairro/cidade via Nominatim (último recurso, aproximado por região)

    Retorna sempre uma tupla de 7 posições:
        (lat, lon, cidade, uf, cep, bairro, status)
    onde 'status' é um de:
        VALIDO             -> coordenada de rua/CEP exata
        ALERTA_APROXIMADO  -> só foi possível localizar bairro/cidade (sem precisão de rua)
        ERRO_CEP_INVALIDO  -> não foi possível localizar o endereço em nenhuma fonte;
                              nesse caso lat/lon vêm como None (NUNCA mais retorna uma
                              coordenada fixa "chumbada" para mascarar o erro).
    """
    clean_cep = ''.join(filter(str.isdigit, str(cep or "")))
    chave = _chave_cache(rua, numero, bairro, cep, cidade, uf)

    if chave in _GEOCODE_CACHE_MEMORIA:
        return _GEOCODE_CACHE_MEMORIA[chave]

    cache_db = await database.cache_get(chave)
    if cache_db:
        _GEOCODE_CACHE_MEMORIA[chave] = cache_db
        return cache_db

    resultado = None
    headers = {'User-Agent': 'ZubaleRoutingCore/6.1 (contato@zubale.com)'}

    # 1) Descobre Cidade e UF oficiais via ViaCEP caso não estejam preenchidos
    cidade_resolvida = cidade
    uf_resolvida = uf

    if clean_cep and (not cidade_resolvida or not uf_resolvida):
        try:
            res_viacep = await client.get(f"https://viacep.com.br/ws/{clean_cep}/json/", timeout=3)
            if res_viacep.status_code == 200:
                dados_cep = res_viacep.json()
                if "erro" not in dados_cep:
                    cidade_resolvida = dados_cep.get("localidade") or cidade_resolvida
                    uf_resolvida = dados_cep.get("uf") or uf_resolvida
                    bairro = bairro or dados_cep.get("bairro")
        except Exception:
            pass

    # 2) Endereço completo com Cidade/UF garantidos via Nominatim -> match de rua exata
    if rua and numero:
        partes = [f"{rua}, {numero}", bairro, cidade_resolvida, uf_resolvida, "Brasil"]
        query = ", ".join([p for p in partes if p])
        try:
            await _respeitar_rate_limit_nominatim()
            res = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"format": "json", "q": query, "limit": 1},
                headers=headers, timeout=4,
            )
            data = res.json()
            if data:
                resultado = (float(data[0]['lat']), float(data[0]['lon']),
                             cidade_resolvida or "Centro", uf_resolvida or "BR", clean_cep, bairro,
                             "VALIDO")
        except Exception:
            pass

    # 3) CEP via BrasilAPI v2 (fallback se o Nominatim não achar o número exato)
    #    Quando a BrasilAPI devolve coordenadas, elas já são no nível do CEP/logradouro
    #    (precisão suficiente para tratar como VALIDO).
    if resultado is None and len(clean_cep) == 8:
        async with _brasilapi_semaforo:
            try:
                r = await client.get(f"https://brasilapi.com.br/api/cep/v2/{clean_cep}", timeout=3)
                if r.status_code == 200:
                    data = r.json()
                    loc = data.get("location", {}).get("coordinates", {})
                    lat, lon = loc.get("latitude"), loc.get("longitude")
                    if lat and lon:
                        resultado = (float(lat), float(lon), data.get("city", cidade_resolvida),
                                     data.get("state", uf_resolvida), clean_cep, data.get("neighborhood", bairro),
                                     "VALIDO")
            except Exception:
                pass

    # 4) Fallback: bairro/cidade via Nominatim (não localizou a rua/CEP exato,
    #    então isso é uma aproximação por região, não a posição real do endereço)
    if resultado is None:
        query = ", ".join([p for p in [bairro, cidade_resolvida, uf_resolvida, "Brasil"] if p])
        if query:
            try:
                await _respeitar_rate_limit_nominatim()
                res = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"format": "json", "q": query, "limit": 1},
                    headers=headers, timeout=4,
                )
                data = res.json()
                if data:
                    resultado = (float(data[0]['lat']), float(data[0]['lon']),
                                 cidade_resolvida or "Centro", uf_resolvida or "BR", clean_cep, bairro,
                                 "ALERTA_APROXIMADO")
            except Exception:
                pass

    # 5) Nenhuma fonte conseguiu localizar o endereço/CEP: sinaliza erro explícito
    #    em vez de inventar uma coordenada (era aqui que caía no centro de SP).
    if resultado is None:
        resultado = (None, None, cidade_resolvida, uf_resolvida, clean_cep, bairro,
                     "ERRO_CEP_INVALIDO")

    _GEOCODE_CACHE_MEMORIA[chave] = resultado
    await database.cache_set(chave, resultado)
    return resultado


async def geocodificar_lote(pedidos_raw: List[Dict[str, Any]]) -> Dict[str, tuple]:
    """
    Geocodifica uma lista de pedidos de forma otimizada:
    - Deduplica endereços idênticos (ex: 2 pedidos no mesmo prédio geocodificam 1x só).
    - Roda em paralelo o que der (BrasilAPI, cache), respeitando o rate-limit do Nominatim.
    Retorna um dicionário {chave_do_endereco: (lat, lon, cidade, uf, cep, bairro, status)}.
    """
    enderecos_unicos = {}
    for p in pedidos_raw:
        rua = p.get("Endereco") or p.get("rua") or ""
        num = str(p.get("Numero") or p.get("numero") or "")
        bairro = p.get("Bairro") or p.get("bairro") or ""
        cep = p.get("CEP") or p.get("cep") or ""
        cidade = p.get("Cidade") or p.get("cidade") or ""
        uf = p.get("UF") or p.get("uf") or ""
        chave = _chave_cache(rua, numero=num, bairro=bairro, cep=cep, cidade=cidade, uf=uf)
        enderecos_unicos[chave] = (rua, num, bairro, cep, cidade, uf)

    resultados: Dict[str, tuple] = {}
    async with httpx.AsyncClient() as client:
        tarefas = [
            geocode_async(client, rua, num, bairro, cep, cidade, uf)
            for chave, (rua, num, bairro, cep, cidade, uf) in enderecos_unicos.items()
        ]
        respostas = await asyncio.gather(*tarefas)
        for chave, resposta in zip(enderecos_unicos.keys(), respostas):
            resultados[chave] = resposta

    return resultados


def geocode_rapido(rua: str = "", numero: str = "", bairro: str = "", cep: str = "", cidade: str = "", uf: str = ""):
    """
    Wrapper SÍNCRONO mantido para compatibilidade com endpoints não convertidos
    (ex: /api/cobertura-ceps, que geocodifica só 1 endereço por vez).
    """
    async def _run():
        async with httpx.AsyncClient() as client:
            return await geocode_async(client, rua, numero, bairro, cep, cidade, uf)
    return asyncio.run(_run())

RAIO_MINIMO_KM = 1.0
RAIO_MAXIMO_KM = 200.0
MSG_RAIO_INVALIDO = "O raio precisa ficar entre 1 e 200 km."
DISTANCIA_MAXIMA_CIDADE_DA_LOJA_KM = 10.0


class RaioCepRequest(BaseModel):
    # Com loja_id o hub é a coordenada cadastrada da loja (sem geocodificar); sem ele ("Outro endereço") vale o endereço.
    loja_id: Optional[int] = None
    origem_rua: Optional[str] = ""
    origem_num: Optional[str] = ""
    origem_cep: Optional[str] = ""
    origem_bairro: Optional[str] = ""
    origem_cidade: Optional[str] = ""
    origem_uf: Optional[str] = ""
    raio_km: Optional[float] = 30.0

logger_cobertura = logging.getLogger("zubale.cobertura")


async def _buscar_cobertura(lat: float, lon: float, raio_km: float, medidas: Optional[dict] = None):
    """
    Cobertura por raio: prefixos de CEP do CNEFE (cep_prefixos). Falha do banco vira erro 503 explícito:
    lista vazia só significa "sem dados para essa região", nunca "deu erro".
    """
    inicio_sql = time.perf_counter()
    try:
        prefixos = await database.consultar_prefixos_por_raio(lat, lon, raio_km)
        if medidas is not None:
            medidas["sql_ms"] = (time.perf_counter() - inicio_sql) * 1000
    except Exception as e:
        if medidas is not None:
            medidas["sql_ms"] = (time.perf_counter() - inicio_sql) * 1000
        print(f"[cobertura] Falha ao consultar a base de CEPs: {e!r}")
        raise HTTPException(
            status_code=503,
            detail=(
                "Não foi possível consultar a cobertura de CEPs agora. Tente novamente em instantes; "
                "se o problema continuar, avise o administrador do sistema."
            ),
        )
    return cobertura.montar_cobertura(prefixos, raio_km)

def _registrar_tempo_da_cobertura(req: "RaioCepRequest", medidas: dict, inicio: float, resultado: str, faixas: int = 0):
    """
    Uma linha no log do servidor com o tempo total do endpoint e o da consulta SQL, em milissegundos, e a quantidade de faixas.
    Só números e o modo (loja ou endereço): nada de nome, endereço, CEP, e-mail do operador nem string de conexão.
    """
    total_ms = (time.perf_counter() - inicio) * 1000
    sql_ms = medidas.get("sql_ms")
    logger_cobertura.info(
        "[cobertura] resultado=%s total_ms=%d sql_ms=%s faixas=%d modo=%s raio_km=%s",
        resultado, round(total_ms), "n/d" if sql_ms is None else str(round(sql_ms)), faixas,
        "loja" if req.loja_id is not None else "endereco", req.raio_km if req.raio_km is not None else 30.0,
    )


@app.post("/api/cobertura-ceps", dependencies=[Depends(obter_operador_atual)])
async def gerar_cobertura_ceps_instantanea(req: RaioCepRequest):
    inicio = time.perf_counter()
    medidas: dict = {}
    try:
        resposta = await _gerar_cobertura_ceps(req, medidas)
    except HTTPException as erro:
        _registrar_tempo_da_cobertura(req, medidas, inicio, f"erro_{erro.status_code}")
        raise
    except Exception:
        _registrar_tempo_da_cobertura(req, medidas, inicio, "erro_inesperado")
        raise
    _registrar_tempo_da_cobertura(req, medidas, inicio, "ok", int(resposta.get("total_pontos", 0)))
    return resposta


async def _gerar_cobertura_ceps(req: RaioCepRequest, medidas: dict):
    raio_max = req.raio_km if req.raio_km is not None else 30.0
    if not (RAIO_MINIMO_KM <= raio_max <= RAIO_MAXIMO_KM):
        raise HTTPException(status_code=422, detail=MSG_RAIO_INVALIDO)

    if req.loja_id is not None:
        return await _cobertura_da_loja(req.loja_id, raio_max, medidas)

    if not (req.origem_rua or req.origem_cep):
        raise HTTPException(status_code=422, detail="Escolha uma loja ou informe o endereço do hub.")
    async with httpx.AsyncClient() as client:
        lat, lon, cidade, uf, clean_cep, bairro, status_hub = await geocode_async(
            client, req.origem_rua or "", req.origem_num or "", req.origem_bairro or "", req.origem_cep or "", req.origem_cidade or "", req.origem_uf or ""
        )

    # Sem coordenada real da loja/hub não há como calcular raio nenhum — em vez de
    # cair num fallback silencioso, avisamos o operador explicitamente (Etapa 2).
    if status_hub == "ERRO_CEP_INVALIDO" or lat is None or lon is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Não foi possível localizar o endereço ou o CEP informado para a loja. "
                "Verifique o CEP e o endereço digitados."
            ),
        )

    clean_cep = str(clean_cep or "").replace("-", "").strip().zfill(8)
    # Código IBGE real do município da loja (tabela ibge_municipios); None se não achar, nunca um valor fixo.
    ibge_base = await database.buscar_ibge_municipio(uf, cidade)

    # Cobertura real dentro do raio (prefixos do CNEFE). Sem dados reais para a região devolvemos
    # lista vazia com um aviso explícito em vez de inventar CEPs.
    pontos_cobertos = await _buscar_cobertura(lat, lon, raio_max, medidas)
    resumo = cobertura.resumir_cobertura(pontos_cobertos)

    aviso = None
    if not pontos_cobertos:
        aviso = (
            "Ainda não temos CEPs cadastrados para essa região. Confira o endereço da loja "
            "ou peça ao administrador do sistema para incluir a região."
        )

    return {
        "hub": {
            "lat": lat, "lon": lon, "cidade": cidade, "uf": uf, "cep": clean_cep,
            "ibge": ibge_base, "endereco": f"{req.origem_rua}, {req.origem_num}",
            "status": status_hub,
        },
        "raio_limite_km": raio_max,
        "total_pontos": len(pontos_cobertos),
        "pontos_cobertos": pontos_cobertos,
        "resumo_cobertura": resumo,
        "legenda_cobertura": cobertura.LEGENDA_COBERTURA,
        "fonte": cobertura.ATRIBUICAO_CNEFE if pontos_cobertos else None,
        "aviso": aviso,
    }

async def _cobertura_da_loja(loja_id: int, raio_max: float, medidas: Optional[dict] = None):
    """Cobertura pela coordenada CADASTRADA da loja (sem geocodificar o endereço)."""
    loja = await _com_conexao_lojas(lambda c: lojas.obter_ativa(c, loja_id))
    lat, lon = loja["lat"], loja["lng"]
    pontos_cobertos = await _buscar_cobertura(lat, lon, raio_max, medidas)
    resumo = cobertura.resumir_cobertura(pontos_cobertos)
    # Código IBGE do hub: primeiro pela cidade + UF cadastradas na loja (busca sem acento e sem diferença de maiúsculas na
    # lista de municípios do IBGE). Sem cidade, sem UF ou cidade não encontrada, vale o prefixo de CEP mais próximo
    # (a menos de 10 km, dado real do CNEFE) e o operador é avisado; se nem isso houver, fica vazio (nunca inventado).
    proximo = next((p for p in pontos_cobertos if p["distancia_km"] <= DISTANCIA_MAXIMA_CIDADE_DA_LOJA_KM), None)
    ibge_hub, cidade_hub, aviso_ibge = None, loja.get("cidade") or "", None
    if loja.get("cidade") and loja.get("uf"):
        ibge_hub = await database.buscar_ibge_municipio(loja["uf"], loja["cidade"])
        if ibge_hub is None:
            aviso_ibge = f"Não achei a cidade \"{loja['cidade']}\" ({loja['uf']}) na lista de municípios do IBGE. "
    elif loja.get("cidade"):
        aviso_ibge = "A loja está sem Estado cadastrado, então não dá para achar a cidade na lista de municípios do IBGE. "
    else:
        aviso_ibge = "A loja está sem cidade cadastrada. "
    if ibge_hub is None:
        if proximo is not None:
            ibge_hub = proximo["ibge"]
            cidade_hub = cidade_hub or proximo["cidade"]
            aviso_ibge += "O código IBGE foi tirado do CEP mais próximo da loja. Confira ou cadastre a cidade na tela \"Lojas\"."
        else:
            aviso_ibge += "Também não há CEP cadastrado por perto, então o código IBGE ficou em branco. Cadastre a cidade na tela \"Lojas\"."
    else:
        aviso_ibge = None
    aviso = None
    if not pontos_cobertos:
        aviso = (
            "Ainda não temos CEPs cadastrados para essa região. Confira a localização da loja "
            "ou peça ao administrador do sistema para incluir a região."
        )
    return {
        "hub": {
            "lat": lat, "lon": lon, "cidade": cidade_hub, "uf": loja["uf"] or (proximo["uf"] if proximo else ""),
            "cep": "", "ibge": ibge_hub, "aviso_ibge": aviso_ibge,
            "endereco": f"{loja['nome']} - {loja['endereco']}" if loja["endereco"] else loja["nome"],
            "status": "VALIDO", "loja_id": loja["id"], "nome": loja["nome"],
        },
        "raio_limite_km": raio_max,
        "total_pontos": len(pontos_cobertos),
        "pontos_cobertos": pontos_cobertos,
        "resumo_cobertura": resumo,
        "legenda_cobertura": cobertura.LEGENDA_COBERTURA,
        "fonte": cobertura.ATRIBUICAO_CNEFE if pontos_cobertos else None,
        "aviso": aviso,
        "aviso_ibge": aviso_ibge,
    }


class ExportarXlsxRequest(BaseModel):
    hub: Dict[str, Any]
    pontos_cobertos: List[Dict[str, Any]]

@app.post("/api/exportar-tabela-frete-xlsx", dependencies=[Depends(obter_operador_atual)])
def exportar_tabela_frete_xlsx(req: ExportarXlsxRequest):
    wb = openpyxl.Workbook()
    
    # Aba 1: Prazos e Preços
    ws1 = wb.active
    ws1.title = "Prazos e preços"
    
    header_l1 = [None]*8 + ["Faixa Peso (Kg)", "De / Até", "De / Até", "De / Até", "De / Até", "De / Até"]
    header_l2 = ["Faixa Destino", None, None, None, None, None, None, "Prazo entrega", 0.000001, 10.000001, 20.000001, 30.000001, 50.000001, 70.000001, "Excedente", None, "Taxa", None, None, "Advalorem", None, None, None, None, "ADEME", None, None, "GRIS", None, None, None, None, None, "TRT", None, None, "TDA", None, None, None, None, None, None, None, "Taxa Fluvial", None, None, "EMEX", None, None, None, None, "Pedágio", None, None, None, None, "Restrição de Dimensões Máximas (Centímetros)", None, "Restrição de Dimensões (Centímetros)", None, "ICMS", None]
    header_l3 = [
        "Código IBGE", "Descrição (Município ou distrito)", "UF", "Cidade", "Faixa de precificação", "CEP Inicial", "CEP Final", "Dias",
        10, 20, 30, 50, 70, 100, "Taxa Excedente x KG", "Excedente fixo (R$)", "Coleta (R$)", "Despacho (R$)", "Entrega (R$)",
        "ADV1 (%)", "Base cálculo para ADV2 (R$)", "ADV2 (%)", "Mínimo (R$)", "Máximo (R$)",
        "% Percentual", "Mínimo (R$)", "Máximo (R$)", "Base cálculo para GRIS1 (R$)", "GRIS1 (%)", "Base cálculo para GRIS2 (R$)", "GRIS2 (%)", "Mínimo (R$)", "Máximo (R$)",
        "% Percentual", "Mínimo (R$)", "Máximo (R$)", "% Percentual", "Mínimo (R$)", "Máximo (R$)",
        "Balsa (R$)", "Suframa Valor (R$)", "TAS (R$)", "SEC CAT (R$)", "DAT (R$)",
        "% Percentual", "Mínimo (R$)", "Máximo (R$)", "% Percentual NF", "Valor por fração 100Kg (R$)", "Valor fixo (R$)", "Mínimo (R$)", "Máximo (R$)",
        "Valor (R$)", "Fração KG", "Mínimo (R$)", "Máximo (R$)", "Fator de Cubagem",
        "Altura Máxima", "Largura Máxima", "Comprimento Máximo", "Soma Máxima", "% Percentual da rota", "ICMS sobre o pedágio",
        "Cobertura"  # sempre a última coluna: não desloca nenhuma coluna do modelo da transportadora
    ]
    
    ws1.append(header_l1)
    ws1.append(header_l2)
    ws1.append(header_l3)
    
    for p in req.pontos_cobertos:
        ibge = p.get("ibge") or req.hub.get("ibge")  # vazio se desconhecido, em vez de um código inventado
        uf = p.get("uf") or req.hub.get("uf") or "SP"
        cidade = p.get("cidade") or req.hub.get("cidade") or "Município"
        bairro = p.get("bairro") or ""
        cep_ini = str(p.get("cep_inicial", "00000000")).zfill(8)
        cep_fim = str(p.get("cep_final", "99999999")).zfill(8)
        dias = p.get("dias_sla") or (1 if p.get("distancia_km", 0) <= cobertura.LIMITE_PRAZO_1_DIA_KM else 2)
        dist = p.get("distancia_km", 0)
        
        linha = [
            ibge, bairro, uf, cidade, f"Raio {dist} km", cep_ini, cep_fim, dias,
            1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0,
            0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0, 0, 0,
            0, 100, 0, 0, 250,
            0, 0, 0, 0, 0, 0,
            p.get("cobertura") or ""
        ]
        ws1.append(linha)

    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    
    for col_idx in range(1, len(header_l3) + 1):
        cell = ws1.cell(row=3, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws2 = wb.create_sheet(title="TZR e TDE")
    ws2.append(["CNPJ", "TZR", "TDE"])
    ws2.append(["00.000.000/0000-00", 0, 0])

    # Legenda e atribuição ficam numa aba própria (não abaixo dos dados) para que um importador da
    # transportadora não leia essas linhas como faixas de CEP.
    ws3 = wb.create_sheet(title="Cobertura e fonte")
    ws3.append([cobertura.LEGENDA_COBERTURA])
    if req.pontos_cobertos:
        ws3.append([cobertura.ATRIBUICAO_CNEFE])
    ws3.column_dimensions["A"].width = 140
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    headers_resp = {
        'Content-Disposition': 'attachment; filename="tabela_frete_completa.xlsx"'
    }
    return StreamingResponse(
        output,
        headers=headers_resp,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

async def get_osrm_route_async(client: httpx.AsyncClient, pontos):
    if len(pontos) < 2:
        return 0, 0, []

    coords_str = ";".join([f"{lon},{lat}" for lat, lon in pontos])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"

    try:
        res = await client.get(url, timeout=6)
        data = res.json()
        if data.get("code") == "Ok":
            route = data["routes"][0]
            dist_km = round(route["distance"] / 1000, 2)
            tempo_min = round(route["duration"] / 60)
            geometria = [[coord[1], coord[0]] for coord in route["geometry"]["coordinates"]]
            return dist_km, tempo_min, geometria
    except Exception:
        pass

    dist_total = 0
    geometria = []
    for i in range(len(pontos) - 1):
        lat1, lon1 = pontos[i]
        lat2, lon2 = pontos[i + 1]
        dist_total += math.sqrt((lat2 - lat1) ** 2 + (lon2 - lon1) ** 2) * 111 * 1.3
        geometria.extend([[lat1, lon1], [lat2, lon2]])

    dist_km = round(dist_total, 2)
    tempo_min = round((dist_km / 22.0) * 60)
    return dist_km, tempo_min, geometria

async def obter_matriz(cliente, pontos):
    """Matriz de distâncias e tempos (OSRM `table`, com reserva em linha reta e aviso). Os testes trocam esta função."""
    return await matriz.obter_matriz(cliente, pontos)


class MotoristaItem(BaseModel):
    """Motorista ativo do cadastro, com o valor base por rota do tipo de veículo dele."""
    id: int
    motorista: str
    modal: str  # nome do tipo de veículo
    custo_rota: float = 0.0  # valor base do tipo de veículo
    valor_motorista: Optional[float] = None  # valor próprio do motorista (None = usa o valor base)

class ModalConfigItem(BaseModel):
    capacidade: int

class OtimizarRequest(BaseModel):
    # Com loja_id o hub é a coordenada cadastrada da loja (sem geocodificar) e o loja_hub gravado é o nome dela.
    loja_id: Optional[int] = None
    origem_rua: Optional[str] = ""
    origem_num: Optional[str] = ""
    origem_bairro: Optional[str] = ""
    origem_cep: Optional[str] = ""
    modais_config: Optional[Dict[str, ModalConfigItem]] = None
    # Valor por rota informado pelo operador, por tipo de veículo ({"Carro de passeio": "130,50"}). Ausente ou vazio:
    # vale o valor base do tipo. Vale para todas as rotas daquele tipo nesta execução.
    valores_por_rota: Optional[Dict[str, Optional[Union[float, str]]]] = None
    # Ids dos motoristas escolhidos no painel (só os marcados entram na roteirização; precisam estar ativos).
    motorista_ids: Optional[List[Any]] = None
    # Turno escolhido MANUALMENTE pelo operador (manha, tarde ou noite): obrigatório, nunca inferido do relógio.
    turno: Optional[str] = None
    # Minutos parados em cada entrega (padrão 10), somados ao tempo de deslocamento.
    tempo_por_parada_min: Optional[Union[int, float, str]] = None
    # Número de viagens por motorista ({"id": 2}); nulo/ausente = automático (recomendado). O teto de pedidos do tipo de veículo não vale para o
    # motorista com número definido (rota personalizada): o resultado só avisa quando a viagem passa do teto.
    viagens_por_motorista: Optional[Dict[str, Optional[Union[int, float, str]]]] = None
    pedidos: List[Dict[str, Any]]

@app.get("/api/modais", dependencies=[Depends(obter_operador_atual)])
def get_modais():
    return MODAIS_PADRAO_DEFAULT

MSG_ARQUIVO_ILEGIVEL = "Não consegui ler o arquivo. Confira se é um .csv ou .xlsx válido ou use o modelo padrão."


@app.post("/api/pedidos/validar", dependencies=[Depends(obter_operador_atual)])
async def validar_pedidos(file: UploadFile = File(...)):
    """
    Lê o CSV/XLSX de pedidos (modelo padrão, modelo antigo ou variações de cabeçalho) e devolve o RELATÓRIO de validação linha a
    linha (válidas, erros, avisos) para o operador conferir antes de aceitar o lote. Nada é guardado: o lote é temporário.
    Cliente e endereço nunca vão para log nem para mensagem de erro.
    """
    try:
        conteudo = await file.read(pedidos_fonte.MAX_BYTES + 1)
        bruto = pedidos_fonte.FonteArquivo(conteudo, file.filename or "").ler()
        cadastradas = await _com_conexao_lojas(lambda c: lojas.listar(c)) if bruto.tem_lojas else None
        return pedidos_fonte.validar_lote(bruto, cadastradas).para_dict()
    except pedidos_fonte.ErroDeArquivo as erro:
        raise HTTPException(status_code=400, detail=str(erro))
    except HTTPException:
        raise
    except Exception as erro:  # só a classe: a mensagem do erro pode trazer um pedaço do arquivo
        print(f"[pedidos] Falha ao ler o arquivo de pedidos: {type(erro).__name__}")
        raise HTTPException(status_code=400, detail=MSG_ARQUIVO_ILEGIVEL)


@app.post("/api/upload", dependencies=[Depends(obter_operador_atual)])
async def upload_planilha(file: UploadFile = File(...)):
    """Nome antigo de /api/pedidos/validar (mesma resposta, mais o campo `total` com as linhas válidas)."""
    relatorio = await validar_pedidos(file)
    relatorio["total"] = len(relatorio["pedidos"])
    return relatorio

# ==========================================================================
# SISTEMA DE JOB COM PROGRESSO
# Como geocodificar pode levar segundos, a otimização roda em segundo plano
# e o frontend consulta o andamento em /api/otimizar/status/{job_id}.
# ==========================================================================
# Os resultados ficam na memória até "Confirmar rotas". Para a memória do servidor não crescer
# sem fim, os jobs terminados saem depois de JOBS_TTL_HORAS do término e, passando de JOBS_MAX,
# saem primeiro os terminados mais antigos. Job em andamento nunca é removido.
JOBS: Dict[str, Dict[str, Any]] = {}
logger_jobs = logging.getLogger("zubale.jobs")


def _limpar_jobs(agora: Optional[float] = None, ttl_horas: Optional[float] = None, maximo: Optional[int] = None) -> int:
    """Limpeza preguiçosa dos jobs terminados (ao criar um job e ao consultar o status). Nunca levanta erro; devolve quantos removeu."""
    try:
        agora = time.time() if agora is None else agora
        ttl_s = (JOBS_TTL_HORAS if ttl_horas is None else ttl_horas) * 3600
        maximo = JOBS_MAX if maximo is None else maximo
        terminados = []
        for job_id, job in list(JOBS.items()):
            if job.get("status") == "em_andamento":
                continue
            if job.get("terminado_em") is None:  # job terminado sem horário (ex.: gravado por fora): conta a partir de agora
                job["terminado_em"] = agora
            terminados.append((job["terminado_em"], job_id))
        remover = {job_id for terminado_em, job_id in terminados if agora - terminado_em >= ttl_s}
        excesso = len(JOBS) - len(remover) - maximo
        if excesso > 0:
            restantes = sorted(t for t in terminados if t[1] not in remover)
            remover.update(job_id for _, job_id in restantes[:excesso])
        for job_id in remover:
            JOBS.pop(job_id, None)
        if remover:  # só contagens: nada de id de pedido, endereço ou cliente
            logger_jobs.info("Limpeza de resultados de roteirização: %d removidos, %d restantes", len(remover), len(JOBS))
        return len(remover)
    except Exception as erro:
        logger_jobs.warning("Falha na limpeza de resultados de roteirização: %s", type(erro).__name__)
        return 0


def _novo_job() -> str:
    _limpar_jobs(maximo=max(JOBS_MAX - 1, 0))  # abre espaço para o job novo
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "em_andamento",   # em_andamento | concluido | erro
        "etapa": "Iniciando...",
        "atual": 0,
        "total": 1,
        "resultado": None,
        "erro": None,
        "criado_em": time.time(),
        "terminado_em": None,
    }
    return job_id


async def _processar_otimizacao(job_id: str, req: "OtimizarRequest", frota_usar: List[MotoristaItem], valores_informados: Optional[Dict[str, Any]] = None, loja: Optional[Dict[str, Any]] = None, contexto: Optional[Dict[str, Any]] = None):
    job = JOBS[job_id]
    contexto = contexto or {}
    turno = contexto.get("turno") or "manha"
    tempo_por_parada = contexto.get("tempo_por_parada_min") or roteirizacao.TEMPO_POR_PARADA_PADRAO_MIN
    try:
        modais_usar = {}
        if req.modais_config:
            for k, v in req.modais_config.items():
                modais_usar[k] = {'capacidade': v.capacidade}
        else:
            modais_usar = MODAIS_PADRAO_DEFAULT

        # --- Etapa 1: o Hub. Loja cadastrada usa a coordenada dela; "Outro endereço" é geocodificado ---
        if loja:
            job["etapa"] = "Usando a localização cadastrada da loja..."
            orig_lat, orig_lon, status_hub = loja["lat"], loja["lng"], "VALIDO"
        else:
            job["etapa"] = "Localizando a Loja Central..."
            async with httpx.AsyncClient() as client:
                orig_lat, orig_lon, cidade_hub, uf_hub, cep_hub, _, status_hub = await geocode_async(
                    client, req.origem_rua or "", req.origem_num or "", req.origem_bairro or "", req.origem_cep or ""
                )

        # Sem a coordenada real da loja não há como montar nenhuma rota — em vez de
        # rotear silenciosamente a partir de um ponto fictício (centro de SP), a
        # roteirização inteira falha aqui com uma mensagem clara para o operador.
        if status_hub == "ERRO_CEP_INVALIDO" or orig_lat is None or orig_lon is None:
            job["status"] = "erro"
            job["erro"] = (
                "Não foi possível localizar o endereço/CEP da loja central. "
                "Verifique o CEP e o endereço informados e tente novamente."
            )
            return

        if loja:
            origem_dict = {"rua": loja["nome"], "numero": "", "bairro": loja.get("endereco") or "", "lat": orig_lat, "lon": orig_lon, "loja_id": loja["id"]}
            loja_hub_texto = loja["nome"]
        else:
            origem_dict = {"rua": req.origem_rua, "numero": req.origem_num, "lat": orig_lat, "lon": orig_lon}
            loja_hub_texto = ", ".join(p for p in (str(req.origem_rua or "").strip(), str(req.origem_num or "").strip()) if p) + (f" - {req.origem_bairro}" if req.origem_bairro else "")

        # --- Etapa 2: geocodificar todos os pedidos (deduplicado + paralelo) ---
        total_pedidos = len(req.pedidos)
        job["etapa"] = f"Geocodificando endereços (0/{total_pedidos})..."
        job["atual"] = 0
        job["total"] = total_pedidos

        mapa_geocode = await geocodificar_lote(req.pedidos)
        job["atual"] = total_pedidos
        job["etapa"] = f"Endereços geocodificados ({total_pedidos}/{total_pedidos})."

        pedidos_geo = []
        pedidos_sem_geocodificacao = []
        for idx, p in enumerate(req.pedidos):
            rua = p.get("Endereco") or p.get("rua") or ""
            num = str(p.get("Numero") or p.get("numero") or "")
            bairro = p.get("Bairro") or p.get("bairro") or ""
            cep = p.get("CEP") or p.get("cep") or ""
            cidade_p = p.get("Cidade") or p.get("cidade") or ""
            uf_p = p.get("UF") or p.get("uf") or ""
            vol = p.get("Volume") or p.get("volume") or 1

            chave = _chave_cache(rua, numero=num, bairro=bairro, cep=cep, cidade=cidade_p, uf=uf_p)
            p_lat, p_lon, _, _, _, _, p_status = mapa_geocode.get(
                chave, (None, None, "", "", "", "", "ERRO_CEP_INVALIDO")
            )
            pedido_id = p.get("id", idx + 1)

            if p_status == "ERRO_CEP_INVALIDO" or p_lat is None or p_lon is None:
                # Não inventa mais uma posição (ex: no Hub) para este pedido — ele
                # sai do cálculo de rotas e volta destacado para o operador corrigir
                # o endereço/CEP manualmente.
                pedidos_sem_geocodificacao.append({
                    "id": pedido_id, "Endereco": rua, "Numero": num, "Bairro": bairro,
                    "CEP": cep, "Volume": vol,
                    "motivo": "Erro ao tentar encontrar endereço do pedido."
                })
                continue

            pedidos_geo.append({
                "id": pedido_id, "Endereco": rua, "Numero": num, "Bairro": bairro, "Cidade": cidade_p, "UF": uf_p,
                "CEP": cep, "Volume": vol, "lat": p_lat, "lon": p_lon,
                # ALERTA_APROXIMADO = só achou bairro/cidade (sem precisão de rua).
                # O pedido continua sendo roteirizado normalmente, só fica marcado
                # para o frontend destacar em amarelo no mapa/lista.
                "geocode_status": p_status,
            })

        # --- Etapa 3: roteirizar com OR-Tools (agrupamento, ordem das paradas, setores, tempos e avisos) ---
        # Capacidade por NÚMERO de pedidos por viagem; o peso nunca entra. Tudo é sugestão: o sistema nunca recusa.
        capacidades = {nome: int(cfg["capacidade"]) for nome, cfg in modais_usar.items()}
        por_id = {f.id: f for f in frota_usar}
        valores_informados = valores_informados or {}
        rotas_resultado = []
        km_total_geral = 0.0
        custo_total_geral = 0.0
        tempo_total_min = 0
        async with httpx.AsyncClient() as client:
            plano = await roteirizacao.executar(
                pedidos=pedidos_geo, hub=(orig_lat, orig_lon), motoristas=frota_usar, capacidades=capacidades, turno=turno,
                tempo_por_parada_min=tempo_por_parada, rotas_hoje=contexto.get("rotas_hoje"), proibidos=contexto.get("proibidos"),
                viagens_por_motorista=contexto.get("viagens"),
                obter_matriz=lambda pontos: obter_matriz(client, pontos),
                progresso=lambda texto: job.__setitem__("etapa", texto),
            )
            viagens = plano["viagens"]
            job["etapa"] = f"Montando as rotas (0/{len(viagens)})..."
            job["atual"] = 0
            job["total"] = len(viagens)
            total_viagens_por_motorista = {}
            for v in viagens:
                total_viagens_por_motorista[v["motorista_id"]] = total_viagens_por_motorista.get(v["motorista_id"], 0) + 1

            for c_idx, viagem in enumerate(viagens):
                mot_info = por_id[viagem["motorista_id"]]
                num_viagem = viagem["viagem_num"]
                pts_rota = viagem["pedidos"]
                for p in pts_rota:
                    p['modal_alocado'] = mot_info.modal
                    p['motorista_alocado'] = mot_info.motorista
                    p['viagem_alocada'] = num_viagem

                pontos_coords = [(orig_lat, orig_lon)] + [(p['lat'], p['lon']) for p in pts_rota] + [(orig_lat, orig_lon)]
                # A distância e o tempo vêm da matriz (iguais aos trechos mostrados); daqui só se usa o traçado para o mapa.
                _, _, geometria = await get_osrm_route_async(client, pontos_coords)
                dist_km = viagem["km_total"]
                tempo_min = viagem["tempo_min"]

                # Valor da rota, do mais específico ao mais geral: (1) o informado pelo operador nesta roteirização
                # para o tipo de veículo, (2) o valor próprio do motorista, (3) o valor base do tipo
                # (sem combustível nem hora do motorista).
                informado = valores_informados.get(mot_info.modal.strip().lower())
                custos = calcular_custo_rota(
                    len(pts_rota), mot_info.custo_rota, None if informado is None else float(informado), mot_info.valor_motorista
                )
                custo_rota = custos["custo_total"]
                km_total_geral += dist_km
                custo_total_geral += custo_rota
                tempo_total_min += tempo_min

                waypoint_coords = "/".join([f"{p['lat']},{p['lon']}" for p in pts_rota])
                link_maps = f"https://www.google.com/maps/dir/{orig_lat},{orig_lon}/{waypoint_coords}/{orig_lat},{orig_lon}"
                titulo_viagem = f"{mot_info.motorista} • Viagem {num_viagem}" if total_viagens_por_motorista[mot_info.id] > 1 else mot_info.motorista

                rotas_resultado.append({
                    "id": c_idx + 1, "motorista": titulo_viagem, "motorista_base": mot_info.motorista, "motorista_id": mot_info.id,
                    "viagem_num": num_viagem, "modal": mot_info.modal, "cor": CORES_ROTAS[c_idx % len(CORES_ROTAS)],
                    "qtd_pedidos": len(pts_rota), "km_total": dist_km,
                    "tempo_formatado": roteirizacao.formatar_tempo(tempo_min), "tempo_min": tempo_min,
                    "tempo_deslocamento_min": viagem["tempo_deslocamento_min"], "tempo_paradas_min": viagem["tempo_paradas_min"],
                    "setores": viagem["setores"], "distancias_trechos_km": viagem["distancias_trechos_km"], "tempos_trechos_s": viagem.get("tempos_trechos_s"),
                    "distancia_retorno_km": viagem["distancia_retorno_km"], "violacoes_rotacao": viagem["violacoes_rotacao"],
                    "rota_personalizada": viagem["personalizada"], "teto_recomendado": viagem["teto_recomendado"],
                    "viagens_solicitadas": viagem["viagens_solicitadas"],
                    "custo_total": custos["custo_total"], "custo_por_pedido": custos["custo_por_pedido"],
                    "valor_rota": custos["valor_rota"], "origem_valor": custos["origem_valor"],
                    "geometria": geometria, "paradas": pts_rota, "link_maps": link_maps
                })

                job["atual"] = c_idx + 1
                job["etapa"] = f"Montando as rotas ({c_idx + 1}/{len(viagens)})..."

        # Resumo do valor por rota usado em cada tipo de veículo desta execução e de onde veio (o mesmo tipo pode ter
        # valores diferentes se algum motorista tiver valor próprio): uma linha por tipo, valor e origem.
        valores_por_tipo = {}
        for rota in rotas_resultado:
            chave = (rota["modal"], rota["valor_rota"], rota["origem_valor"])
            item = valores_por_tipo.setdefault(chave, {"tipo": rota["modal"], "valor": rota["valor_rota"], "origem": rota["origem_valor"], "rotas": 0})
            item["rotas"] += 1

        total_p = len(pedidos_geo)
        kpis = {
            "total_pedidos": total_p, "total_veiculos": len({r["motorista_id"] for r in rotas_resultado}),
            # Motoristas realmente usados nas rotas (podem ser menos que os escolhidos se não houve pedido para todos).
            "total_motoristas": len({r["motorista_id"] for r in rotas_resultado}),
            "total_rotas_viagens": len(rotas_resultado), "km_total": round(km_total_geral, 2),
            "custo_total": round(custo_total_geral, 2),
            "custo_medio_pedido": round(custo_total_geral / max(total_p, 1), 2),
            "valores_por_tipo": list(valores_por_tipo.values()),
            "total_pedidos_sem_geocodificacao": len(pedidos_sem_geocodificacao),
            "tempo_total_min": tempo_total_min,
        }
        avisos = list(plano["avisos"])
        if not pedidos_geo and pedidos_sem_geocodificacao:
            avisos.append({"tipo": "sem_pedidos", "gravidade": "atencao", "mensagem": "Nenhum pedido pôde ser localizado no mapa, então não há rotas."})

        job["status"] = "concluido"
        job["etapa"] = "Concluído."
        job["resultado"] = {
            "execucao_id": job_id,  # identifica esta roteirização para "Confirmar rotas"
            "loja_hub": loja_hub_texto,
            "origem": origem_dict,
            "rotas": rotas_resultado,
            "kpis": kpis,
            # Pedidos com CEP/endereço não localizado: ficam de fora das rotas
            # calculadas acima e voltam aqui para o operador ver e corrigir.
            "pedidos_sem_geocodificacao": pedidos_sem_geocodificacao,
            # Etapa 8: turno escolhido, de onde vieram as distâncias (osrm | linha_reta), avisos (rotação, linha reta, viagens extras...)
            "turno": turno,
            "origem_distancias": plano["origem_distancias"],
            "metodo": plano["metodo"],
            "avisos": avisos,
            "parametros": plano["parametros"],
        }

    except Exception as e:
        job["status"] = "erro"
        # só a classe do erro: a mensagem pode trazer endereço de pedido (dado pessoal)
        print(f"[otimizar] Falha na roteirização: {type(e).__name__}")
        job["erro"] = f"Erro interno no algoritmo de roteirização ({type(e).__name__}). Tente de novo; se persistir, avise o administrador."
    finally:
        if job.get("status") != "em_andamento":
            job["terminado_em"] = time.time()


@app.post("/api/otimizar", dependencies=[Depends(obter_operador_atual)])
async def iniciar_otimizacao(req: "OtimizarRequest"):
    """Inicia a roteirização em segundo plano e devolve um job_id na hora."""
    try:
        valores_informados = frota.interpretar_valores_informados(req.valores_por_rota)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    try:
        turno = roteirizacao.normalizar_turno(req.turno)
        tempo_por_parada = roteirizacao.interpretar_tempo_por_parada(req.tempo_por_parada_min)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    loja = await _com_conexao_lojas(lambda c: lojas.obter_ativa(c, req.loja_id)) if req.loja_id is not None else None
    if loja is None and not (req.origem_rua or req.origem_cep):
        raise HTTPException(status_code=422, detail="Escolha uma loja ou informe o endereço do hub.")

    async def _motoristas_e_historico_do_dia(c):
        escolhidos = await frota.selecionar_motoristas(c, req.motorista_ids)
        dia = rotas_realizadas.hoje_em_brasilia()
        return escolhidos, await rotas_realizadas.contagem_do_dia(c, dia), await rotas_realizadas.setores_do_dia(c, dia, turno)

    motoristas, rotas_hoje, proibidos = await _com_conexao_frota(_motoristas_e_historico_do_dia)
    try:  # número de viagens por motorista (opcional; nulo = automático): só vale para motoristas marcados
        viagens_por_motorista = roteirizacao.interpretar_viagens(req.viagens_por_motorista, {int(m["id"]) for m in motoristas})
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    frota_usar = [
        MotoristaItem(id=m["id"], motorista=m["nome"], modal=m["tipo_veiculo"], custo_rota=m["custo_rota"], valor_motorista=m.get("valor_rota"))
        for m in motoristas
    ]
    job_id = _novo_job()
    asyncio.create_task(_processar_otimizacao(
        job_id, req, frota_usar, valores_informados, loja,
        {"turno": turno, "tempo_por_parada_min": tempo_por_parada, "rotas_hoje": rotas_hoje, "proibidos": proibidos, "viagens": viagens_por_motorista},
    ))
    return {"job_id": job_id}


@app.get("/api/otimizar/status/{job_id}", dependencies=[Depends(obter_operador_atual)])
def status_otimizacao(job_id: str):
    _limpar_jobs()
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Cálculo não encontrado (pode ter expirado). Gere as rotas novamente.")
    resposta = {
        "status": job["status"],
        "etapa": job["etapa"],
        "atual": job["atual"],
        "total": job["total"],
    }
    if job["status"] == "concluido":
        resposta["resultado"] = job["resultado"]
    if job["status"] == "erro":
        resposta["erro"] = job["erro"]
    return resposta

@app.get("/api/modelo-xlsx", dependencies=[Depends(obter_operador_atual)])
def download_modelo_xlsx():
    """Modelo padrão de pedidos em XLSX (aba Pedidos com exemplos e aba Instruções)."""
    return StreamingResponse(
        io.BytesIO(pedidos_fonte.gerar_modelo_xlsx()),
        headers={'Content-Disposition': 'attachment; filename="modelo_pedidos_zubale.xlsx"'},
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/api/modelo-csv", dependencies=[Depends(obter_operador_atual)])
def download_modelo_csv():
    """Modelo padrão de pedidos em CSV (UTF-8 com BOM e ponto e vírgula)."""
    return StreamingResponse(
        io.BytesIO(pedidos_fonte.gerar_modelo_csv()),
        headers={'Content-Disposition': 'attachment; filename="modelo_pedidos_zubale.csv"'},
        media_type="text/csv; charset=utf-8",
    )


# ---------------------------------------------------------------------------------------------
# Pesos dos itens (SKUs): manutenção e fila "sem peso". Todas as rotas exigem operador logado.
# O peso é apenas informativo: aqui só se guarda e se edita o peso de cada item.
# ---------------------------------------------------------------------------------------------
MSG_PESOS_INDISPONIVEL = (
    "O cadastro de pesos não está disponível agora. Tente novamente em instantes; "
    "se o problema continuar, avise o administrador do sistema."
)


async def _com_conexao_pesos(operacao):
    """Roda `operacao(conn)` numa conexão do pool; falha do banco vira 503 claro, valor inválido vira 422."""
    pool = await database.get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail=MSG_PESOS_INDISPONIVEL)
    try:
        async with pool.acquire() as conn:
            return await operacao(conn)
    except HTTPException:
        raise
    except item_pesos.ItemJaExiste as erro:
        raise HTTPException(status_code=409, detail=str(erro))
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    except Exception as erro:
        print(f"[pesos] Falha no cadastro de pesos: {erro!r}")
        raise HTTPException(status_code=503, detail=MSG_PESOS_INDISPONIVEL)


def _rotulo_do_operador(operador: Operador) -> str:
    return f"{operador.nome} ({operador.email})"


class AtualizarPesoRequest(BaseModel):
    peso_kg: Optional[Union[float, str]] = None  # vazio/None = tira o peso (o item volta para a fila "sem peso")
    confianca: Optional[str] = "alta"


class SkuVistoRequest(BaseModel):
    id_sku: str
    quantidade: int = 1
    nome: Optional[str] = None
    reference_code: Optional[str] = None


class SkusVistosRequest(BaseModel):
    itens: List[SkuVistoRequest] = Field(max_length=5000)


@app.get("/api/item-pesos/resumo")
async def resumo_item_pesos(operador: Operador = Depends(obter_operador_atual)):
    return await _com_conexao_pesos(item_pesos.resumo)


@app.get("/api/item-pesos/fila-sem-peso")
async def fila_sem_peso(limite: int = 50, deslocamento: int = 0, operador: Operador = Depends(obter_operador_atual)):
    """Itens sem peso, os mais vendidos primeiro."""
    return await _com_conexao_pesos(lambda c: item_pesos.listar(c, None, True, limite, deslocamento))


@app.get("/api/item-pesos")
async def listar_item_pesos(
    busca: Optional[str] = None, somente_sem_peso: bool = False, limite: int = 50, deslocamento: int = 0,
    operador: Operador = Depends(obter_operador_atual),
):
    """Todos os itens (mais vendidos primeiro), com busca por nome, id_sku ou referência."""
    return await _com_conexao_pesos(lambda c: item_pesos.listar(c, busca, somente_sem_peso, limite, deslocamento))


@app.put("/api/item-pesos/{id_sku}")
async def atualizar_item_peso(id_sku: str, dados: AtualizarPesoRequest, operador: Operador = Depends(obter_operador_atual)):
    """Qualquer operador logado edita; o sistema registra quem alterou (atualizado_por) e quando (atualizado_em)."""
    item = await _com_conexao_pesos(
        lambda c: item_pesos.atualizar_peso(c, id_sku, dados.peso_kg, dados.confianca, _rotulo_do_operador(operador))
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item não encontrado no cadastro de pesos.")
    return item


class NovoItemRequest(BaseModel):
    id_sku: Optional[str] = None
    reference_code: Optional[str] = None
    nome: Optional[str] = None
    peso_kg: Optional[Union[float, str]] = None  # opcional; vírgula decimal aceita; maior que 0 e até 1000
    fonte: Optional[str] = None
    confianca: Optional[str] = None  # alta, media ou baixa (padrão media)


@app.post("/api/item-pesos", status_code=201)
async def criar_item_peso(dados: NovoItemRequest, operador: Operador = Depends(obter_operador_atual)):
    """Cria um item (um por vez). Código repetido (sem diferença de maiúsculas e espaços) responde 409. Registra quem criou e quando."""
    return await _com_conexao_pesos(lambda c: item_pesos.criar_item(c, dados.model_dump(), _rotulo_do_operador(operador)))


MSG_ARQUIVO_DE_ITENS_ILEGIVEL = "Não consegui ler o arquivo. Confira se é um .csv ou .xlsx válido ou use o modelo (botão \"Baixar modelo\")."


async def _ler_arquivo_de_itens(file: UploadFile):
    """Lê e valida o arquivo (sem banco). Arquivo ruim vira 400 com texto fixo, sem detalhe técnico."""
    try:
        conteudo = await file.read(item_pesos_importacao.MAX_BYTES + 1)
        lote = item_pesos_importacao.ler_arquivo(conteudo, file.filename or "")
        validas, erros = item_pesos_importacao.validar_linhas(lote)
        return lote, validas, erros
    except item_pesos_importacao.ErroDeImportacao as erro:
        raise HTTPException(status_code=400, detail=str(erro))
    except Exception as erro:
        print(f"[pesos] Falha ao ler o arquivo de itens: {type(erro).__name__}")
        raise HTTPException(status_code=400, detail=MSG_ARQUIVO_DE_ITENS_ILEGIVEL)


@app.get("/api/item-pesos/modelo")
def baixar_modelo_de_itens(operador: Operador = Depends(obter_operador_atual)):
    """Modelo de CSV para importar vários itens (colunas id_sku, reference_code, nome, peso_kg, fonte, confianca; 2 exemplos)."""
    return StreamingResponse(
        io.BytesIO(item_pesos_importacao.gerar_modelo_csv()),
        headers={"Content-Disposition": 'attachment; filename="modelo_itens_pesos.csv"'},
        media_type="text/csv; charset=utf-8",
    )


@app.post("/api/item-pesos/importar/validar")
async def validar_importacao_de_itens(file: UploadFile = File(...), operador: Operador = Depends(obter_operador_atual)):
    """
    Etapa 1 da importação: valida o arquivo e devolve o RELATÓRIO (novos, já existentes, sem peso, inválidos, linha e motivo de cada
    erro). Não grava nada e não guarda o arquivo. O banco só é consultado se houver linha válida.
    """
    lote, validas, erros = await _ler_arquivo_de_itens(file)
    existentes = await _com_conexao_pesos(item_pesos_importacao.ler_existentes) if validas else None
    return item_pesos_importacao.relatorio(lote, validas, erros, existentes)


@app.post("/api/item-pesos/importar/confirmar")
async def confirmar_importacao_de_itens(
    file: UploadFile = File(...),
    atualizar_existentes: bool = Form(False),
    incluir_sem_peso: bool = Form(True),
    operador: Operador = Depends(obter_operador_atual),
):
    """
    Etapa 2: o arquivo vem de novo e é REVALIDADO aqui (nada ficou guardado); grava numa transação só as linhas válidas. Item que já
    existe é ignorado, salvo "atualizar_existentes", que nunca sobrescreve um peso editado por operador. Registra quem importou e quando.
    """
    _, validas, erros = await _ler_arquivo_de_itens(file)
    if not validas:
        raise HTTPException(status_code=422, detail="Não há itens válidos para importar neste arquivo.")
    rotulo = _rotulo_do_operador(operador)
    resultado = await _com_conexao_pesos(lambda c: item_pesos_importacao.importar(c, validas, atualizar_existentes, incluir_sem_peso, rotulo))
    resultado["invalidos"] = len(erros)
    return resultado


class ConsultarPesosRequest(BaseModel):
    skus: List[str] = Field(default_factory=list, max_length=5000)


@app.post("/api/item-pesos/consultar")
async def consultar_pesos_dos_skus(dados: ConsultarPesosRequest, operador: Operador = Depends(obter_operador_atual)):
    """
    Pesos dos SKUs informados (só leitura), para recalcular o peso dos pedidos na tela depois que o operador cadastra um peso. Recebe SÓ códigos de SKU e devolve só
    peso e confiança dos que existem: {"pesos": {"10001": {"peso_kg": 5.0, "confianca": "alta"}}} (peso_kg nulo = existe sem peso). Nada vai para log.
    """
    return {"pesos": await _com_conexao_pesos(lambda c: item_pesos.consultar_pesos(c, dados.skus))}


MSG_ARQUIVO_DE_ITENS_DO_PEDIDO_ILEGIVEL = 'Não consegui ler o arquivo. Confira se é um .csv ou .xlsx válido ou use o modelo (botão "Baixar modelo").'


@app.get("/api/itens-pedido/modelo")
def baixar_modelo_de_itens_do_pedido(operador: Operador = Depends(obter_operador_atual)):
    """Modelo de CSV do arquivo de itens do pedido (id_pedido, sku, quantidade e a descricao opcional; 2 exemplos)."""
    return StreamingResponse(
        io.BytesIO(itens_fonte.gerar_modelo_csv()),
        headers={"Content-Disposition": 'attachment; filename="modelo_itens_do_pedido.csv"'},
        media_type="text/csv; charset=utf-8",
    )


@app.post("/api/itens-pedido/validar")
async def validar_itens_do_pedido(file: UploadFile = File(...), ids_pedidos: Optional[str] = Form(None), operador: Operador = Depends(obter_operador_atual)):
    """
    Lê o arquivo de itens (id_pedido, sku, quantidade, descricao opcional) e devolve o RELATÓRIO de validação mais os itens válidos e os pesos dos SKUs, para o operador conferir
    ANTES de aceitar. `ids_pedidos` (texto JSON, só os ids do lote da tela) serve para listar e ignorar os pedidos que não estão no lote. Não grava nada e não guarda o arquivo;
    o banco só é LIDO (peso e confiança dos SKUs das linhas válidas). Ids, SKUs e itens nunca vão para log nem para mensagem de erro.
    """
    ids_do_lote = None
    if ids_pedidos:
        try:
            lista = json.loads(ids_pedidos)
            if not isinstance(lista, list) or len(lista) > itens_fonte.MAX_IDS_DO_LOTE:
                raise ValueError
            ids_do_lote = [str(i) for i in lista]
        except ValueError:
            raise HTTPException(status_code=422, detail="A lista de pedidos do lote não está num formato válido. Atualize a tela e tente de novo.")
    try:
        conteudo = await file.read(itens_fonte.MAX_BYTES + 1)
        resultado = itens_fonte.validar_itens(itens_fonte.FONTES["arquivo"](conteudo, file.filename or "").ler(), ids_do_lote)
    except itens_fonte.ErroDeItens as erro:
        raise HTTPException(status_code=400, detail=str(erro))
    except Exception as erro:  # só a classe: a mensagem do erro pode trazer um pedaço do arquivo
        print(f"[itens] Falha ao ler o arquivo de itens: {type(erro).__name__}")
        raise HTTPException(status_code=400, detail=MSG_ARQUIVO_DE_ITENS_DO_PEDIDO_ILEGIVEL)
    pesos = await _com_conexao_pesos(lambda c: item_pesos.consultar_pesos(c, [i["sku"] for i in resultado.itens])) if resultado.itens else None
    return itens_fonte.relatorio(resultado, pesos)


@app.post("/api/item-pesos/skus-vistos")
async def registrar_skus_vistos(dados: SkusVistosRequest, operador: Operador = Depends(obter_operador_atual)):
    """SKUs que apareceram em pedidos: os novos entram na fila "sem peso"; os que já existem só somam unidades."""
    return await _com_conexao_pesos(lambda c: item_pesos.registrar_skus_vistos(c, [i.model_dump() for i in dados.itens]))


# ---------------------------------------------------------------------------------------------
# Frota: tipos de veículo (valor base por rota e peso de referência) e motoristas (Etapa 5)
# ---------------------------------------------------------------------------------------------
MSG_FROTA_INDISPONIVEL = (
    "O cadastro de motoristas não está disponível agora. Tente novamente em instantes; "
    "se o problema continuar, avise o administrador do sistema."
)


async def _com_conexao_frota(operacao):
    """Roda `operacao(conn)` numa conexão do pool; falha do banco vira 503 claro, valor inválido vira 422."""
    pool = await database.get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail=MSG_FROTA_INDISPONIVEL)
    try:
        async with pool.acquire() as conn:
            return await operacao(conn)
    except HTTPException:
        raise
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    except Exception as erro:
        # Só a classe e o código do erro: a mensagem do banco pode trazer a linha inteira (telefone é dado pessoal).
        print(f"[frota] Falha no cadastro de motoristas: {type(erro).__name__} (sqlstate={getattr(erro, 'sqlstate', None)})")
        raise HTTPException(status_code=503, detail=MSG_FROTA_INDISPONIVEL)


class AtualizarTipoVeiculoRequest(BaseModel):
    custo_rota: Optional[Union[float, str]] = None
    peso_referencia_kg: Optional[Union[float, str]] = None  # vazio/None = sem referência (não é limite, só um guia)


class NovoMotoristaRequest(BaseModel):
    codigo: Optional[str] = None  # obrigatório no cadastro novo (ex.: MOT-0001); único
    nome: Optional[str] = None
    tipo_veiculo: Optional[str] = None
    valor_rota: Optional[Union[float, str]] = None  # diária própria (vazio = usa a diária base do tipo)
    telefone: Optional[str] = None  # opcional; dado pessoal (nunca vai para log nem para mensagem de erro)
    lojas: Optional[List[Any]] = None  # ids das lojas do motorista


class AtualizarMotoristaRequest(BaseModel):
    codigo: Optional[str] = None  # ausente mantém; não pode ser apagado de quem já tem
    nome: Optional[str] = None
    tipo_veiculo: Optional[str] = None
    ativo: bool = True
    valor_rota: Optional[Union[float, str]] = None  # vazio apaga o valor próprio; se o campo nem vier, ele é mantido
    telefone: Optional[str] = None  # vazio apaga; ausente mantém
    lojas: Optional[List[Any]] = None  # presente substitui o conjunto de lojas; ausente mantém


@app.get("/api/tipos-veiculo")
async def listar_tipos_veiculo(operador: Operador = Depends(obter_operador_atual)):
    return await _com_conexao_frota(frota.listar_tipos_veiculo)


@app.put("/api/tipos-veiculo/{id_tipo}")
async def atualizar_tipo_veiculo(id_tipo: int, dados: AtualizarTipoVeiculoRequest, operador: Operador = Depends(obter_operador_atual)):
    """Qualquer operador logado edita o valor base por rota e o peso de referência; fica registrado quem alterou e quando."""
    tipo = await _com_conexao_frota(
        lambda c: frota.atualizar_tipo_veiculo(c, id_tipo, dados.custo_rota, dados.peso_referencia_kg, _rotulo_do_operador(operador))
    )
    if tipo is None:
        raise HTTPException(status_code=404, detail="Tipo de veículo não encontrado.")
    return tipo


@app.get("/api/motoristas")
async def listar_motoristas(incluir_inativos: bool = True, operador: Operador = Depends(obter_operador_atual)):
    return await _com_conexao_frota(lambda c: frota.listar_motoristas(c, incluir_inativos))


@app.get("/api/motoristas/proximo-codigo")
async def proximo_codigo_motorista(operador: Operador = Depends(obter_operador_atual)):
    """Próximo código livre no padrão MOT-0001 (a tela sugere; o operador pode trocar)."""
    return {"codigo": await _com_conexao_frota(frota.proximo_codigo)}


@app.get("/api/motoristas/{id_motorista}")
async def obter_motorista(id_motorista: int, operador: Operador = Depends(obter_operador_atual)):
    """Um motorista com o telefone completo (só para a tela de edição; as listas trazem o telefone mascarado)."""
    motorista = await _com_conexao_frota(lambda c: frota.obter_motorista(c, id_motorista, True))
    if motorista is None:
        raise HTTPException(status_code=404, detail="Motorista não encontrado.")
    return motorista


@app.post("/api/motoristas", status_code=201)
async def criar_motorista(dados: NovoMotoristaRequest, operador: Operador = Depends(obter_operador_atual)):
    return await _com_conexao_frota(
        lambda c: frota.criar_motorista(c, dados.nome, dados.tipo_veiculo, _rotulo_do_operador(operador), dados.valor_rota,
                                        dados.codigo, dados.telefone, dados.lojas)
    )


@app.put("/api/motoristas/{id_motorista}")
async def atualizar_motorista(id_motorista: int, dados: AtualizarMotoristaRequest, operador: Operador = Depends(obter_operador_atual)):
    """Edita nome, código, tipo, situação, telefone, valor próprio e lojas. Não existe exclusão: o motorista é desativado."""
    enviados = dados.model_fields_set

    def valor(campo):
        return getattr(dados, campo) if campo in enviados else frota.MANTER

    motorista = await _com_conexao_frota(
        lambda c: frota.atualizar_motorista(
            c, id_motorista, dados.nome, dados.tipo_veiculo, dados.ativo, _rotulo_do_operador(operador),
            valor("valor_rota"), valor("codigo"), valor("telefone"), valor("lojas"),
        )
    )
    if motorista is None:
        raise HTTPException(status_code=404, detail="Motorista não encontrado.")
    return motorista


# ---------------------------------------------------------------------------------------------
# Rotas realizadas: confirmar o resultado, desfazer e a contagem do dia (Etapa 5b)
# ---------------------------------------------------------------------------------------------
MSG_LOJAS_INDISPONIVEL = (
    "O cadastro de lojas não está disponível agora. Tente novamente em instantes; "
    "se o problema continuar, avise o administrador do sistema."
)


async def _com_conexao_lojas(operacao):
    """Roda `operacao(conn)` numa conexão do pool; falha do banco vira 503 claro, valor inválido vira 422."""
    pool = await database.get_pool()
    if not pool:
        raise HTTPException(status_code=503, detail=MSG_LOJAS_INDISPONIVEL)
    try:
        async with pool.acquire() as conn:
            return await operacao(conn)
    except HTTPException:
        raise
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    except Exception as erro:
        print(f"[lojas] Falha no cadastro de lojas: {erro!r}")
        raise HTTPException(status_code=503, detail=MSG_LOJAS_INDISPONIVEL)


class LojaRequest(BaseModel):
    nome: Optional[str] = None
    uf: Optional[str] = None
    endereco: Optional[str] = None
    cidade: Optional[str] = None
    codigo_externo: Optional[str] = None  # código da loja no sistema de origem (Superset); único
    nome_operacao: Optional[str] = None  # nome da loja usado na operação; único
    lat: Optional[Union[float, str]] = None
    lng: Optional[Union[float, str]] = None
    ativo: bool = True
    capacidade_peso: Optional[Union[float, str]] = None  # só informativa: nunca bloqueia
    capacidade_volume: Optional[Union[float, str]] = None
    janela_manha_inicio: Optional[str] = None
    janela_manha_fim: Optional[str] = None
    janela_tarde_inicio: Optional[str] = None
    janela_tarde_fim: Optional[str] = None
    janela_noite_inicio: Optional[str] = None
    janela_noite_fim: Optional[str] = None
    usa_noite: bool = True


@app.get("/api/lojas")
async def listar_lojas(incluir_inativas: bool = True, operador: Operador = Depends(obter_operador_atual)):
    return await _com_conexao_lojas(lambda c: lojas.listar(c, incluir_inativas))


@app.post("/api/lojas", status_code=201)
async def criar_loja(dados: LojaRequest, operador: Operador = Depends(obter_operador_atual)):
    return await _com_conexao_lojas(lambda c: lojas.criar(c, dados.model_dump(), _rotulo_do_operador(operador)))


@app.put("/api/lojas/{id_loja}")
async def atualizar_loja(id_loja: int, dados: LojaRequest, operador: Operador = Depends(obter_operador_atual)):
    """Edita a loja inteira, inclusive ativar/desativar. Não existe exclusão: a loja é desativada."""
    corpo = dados.model_dump()
    for campo in ("codigo_externo", "nome_operacao"):  # cliente que não os envia não pode apagá-los
        if campo not in dados.model_fields_set:
            corpo.pop(campo)
    loja = await _com_conexao_lojas(lambda c: lojas.atualizar(c, id_loja, corpo, _rotulo_do_operador(operador)))
    if loja is None:
        raise HTTPException(status_code=404, detail=lojas.MSG_NAO_ENCONTRADA)
    return loja


class ConfirmarRotasRequest(BaseModel):
    execucao_id: str
    turno: Optional[str] = None
    # Etapa 10: motorista final das rotas que o operador trocou na matriz de despacho, {"<numero da rota>": <id do motorista>}. Ausente = o do solver.
    atribuicoes: Optional[Any] = None


MSG_ROTA_AJUSTADA_INEXISTENTE = "Uma das rotas ajustadas não existe neste resultado. Gere as rotas de novo."


def _atribuicoes_validas(atribuicoes, numeros_das_rotas: set) -> Dict[int, Any]:
    """{numero_da_rota: motorista_id (ainda não validado no banco)}; ValueError em linguagem do operador se a rota não existe ou o formato é inválido."""
    if not atribuicoes:
        return {}
    if not isinstance(atribuicoes, dict):
        raise ValueError(MSG_ROTA_AJUSTADA_INEXISTENTE)
    validas = {}
    for chave, motorista in atribuicoes.items():
        try:
            numero = int(str(chave).strip())
        except ValueError:
            raise ValueError(MSG_ROTA_AJUSTADA_INEXISTENTE) from None
        if numero not in numeros_das_rotas:
            raise ValueError(MSG_ROTA_AJUSTADA_INEXISTENTE)
        validas[numero] = motorista
    return validas


@app.get("/api/rotas-realizadas/hoje")
async def rotas_realizadas_hoje(operador: Operador = Depends(obter_operador_atual)):
    """Rotas confirmadas hoje (dia de Brasília) por motorista: {"data": "2026-10-15", "por_motorista": {"3": 2}}."""
    dia = rotas_realizadas.hoje_em_brasilia()
    totais = await _com_conexao_frota(lambda c: rotas_realizadas.totais_do_dia(c, dia))
    return {
        "data": dia.isoformat(),
        "por_motorista": {str(k): v["rotas"] for k, v in totais.items()},
        # Etapa 8b: pedidos das rotas confirmadas do dia por motorista (acrescentado; "por_motorista" continua igual)
        "pedidos_por_motorista": {str(k): v["pedidos"] for k, v in totais.items()},
    }


@app.get("/api/rotas-realizadas/rotacao")
async def rotacao_do_dia(turno: Optional[str] = None, operador: Operador = Depends(obter_operador_atual)):
    """
    Etapa 10 (selo de rotação da matriz de despacho): setores que cada motorista já fez HOJE em OUTROS turnos (só rotas confirmadas),
    {"data", "turno", "por_motorista": {"3": {"N": ["manha"]}}}. Só ids de motorista e setores; nenhum dado de pedido.
    """
    try:
        turno_normal = roteirizacao.normalizar_turno(turno)
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    dia = rotas_realizadas.hoje_em_brasilia()
    por_motorista = await _com_conexao_frota(lambda c: rotas_realizadas.setores_do_dia(c, dia, turno_normal))
    return {"data": dia.isoformat(), "turno": turno_normal, "por_motorista": {str(k): v for k, v in por_motorista.items()}}


@app.post("/api/rotas-realizadas/confirmar")
async def confirmar_rotas(dados: ConfirmarRotasRequest, operador: Operador = Depends(obter_operador_atual)):
    """Grava uma rota por viagem do resultado, com o motorista de cada rota. Confirmar de novo não duplica."""
    job = JOBS.get(dados.execucao_id)
    if not job or job.get("status") != "concluido" or not job.get("resultado"):
        raise HTTPException(status_code=404, detail="Este resultado não está mais disponível. Gere as rotas de novo.")
    resultado = job["resultado"]
    rotas = [
        {"numero_rota": r["id"], "motorista_id": r["motorista_id"], "qtd_pedidos": r.get("qtd_pedidos", 0), "distancia_km": r.get("km_total", 0),
         "setores": modulo_setores.texto_dos_setores(r.get("setores") or []),
         # Só o mínimo vai para o banco: id, endereço (rua, número e bairro), cidade, UF e volume. Nunca cliente, telefone nem CEP.
         "pedidos": [
             {"ordem": p.get("ordem") or i + 1, "pedido_id": p.get("id"), "volume": p.get("Volume"), "cidade": p.get("Cidade"), "uf": p.get("UF"),
              "endereco": _endereco_da_parada(p)}
             for i, p in enumerate(r.get("paradas") or [])
         ]}
        for r in resultado.get("rotas", []) if r.get("motorista_id") is not None
    ]
    # O turno gravado é o da roteirização (escolhido pelo operador); o do corpo só vale para resultados sem turno.
    turno = (resultado.get("turno") or (dados.turno or "").strip())[:20] or None
    dia = rotas_realizadas.hoje_em_brasilia()
    try:
        atribuicoes = _atribuicoes_validas(dados.atribuicoes, {int(r["numero_rota"]) for r in rotas})
    except ValueError as erro:
        raise HTTPException(status_code=422, detail=str(erro))
    nomes = {int(r["motorista_id"]): r.get("motorista_base") for r in resultado.get("rotas", []) if r.get("motorista_id") is not None}
    sugeridos = {int(r["numero_rota"]): int(r["motorista_id"]) for r in rotas}

    async def confirmar_e_limpar(c):
        # Valida o motorista final ANTES de gravar qualquer coisa (inativo, inexistente ou valor inválido = 422, nada é gravado).
        nomes.update(await frota.nomes_dos_motoristas_ativos(c, list(atribuicoes.values())))
        ajustadas = 0
        for rota in rotas:
            novo = atribuicoes.get(int(rota["numero_rota"]))
            if novo is not None and int(novo) != sugeridos[int(rota["numero_rota"])]:
                rota["motorista_id"] = int(novo)
                ajustadas += 1
        avisos = []
        if turno:  # rotação é só aviso: nunca bloqueia nem derruba a confirmação
            try:
                avisos = rotas_realizadas.avisos_de_rotacao(rotas, await rotas_realizadas.setores_do_dia(c, dia, turno), nomes)
            except Exception as erro:
                print(f"[despacho] Falha ao conferir a rotação: {type(erro).__name__}")
        resposta = await rotas_realizadas.confirmar(c, dados.execucao_id, rotas, dia, resultado.get("loja_hub"), turno, _rotulo_do_operador(operador))
        await rotas_realizadas.limpeza_preguicosa(c, dia, HISTORICO_DIAS)  # no máximo uma vez por dia; nunca derruba a confirmação
        return {**resposta, "ajustadas": 0 if resposta.get("ja_confirmada") else ajustadas, "avisos": avisos}

    return await _com_conexao_frota(confirmar_e_limpar)


def _endereco_da_parada(p: dict) -> str:
    """'rua, número - bairro' (só o que existir)."""
    rua = ", ".join(t for t in (str(p.get("Endereco") or "").strip(), str(p.get("Numero") or "").strip()) if t)
    bairro = str(p.get("Bairro") or "").strip()
    return f"{rua} - {bairro}" if rua and bairro else (rua or bairro)


class JaRoteirizadosRequest(BaseModel):
    ids: List[Any] = Field(default_factory=list, max_length=rotas_realizadas.MAX_IDS_DUPLICIDADE)


@app.post("/api/pedidos/ja-roteirizados")
async def pedidos_ja_roteirizados(dados: JaRoteirizadosRequest, operador: Operador = Depends(obter_operador_atual)):
    """
    Controle de duplicidade (aviso, nunca bloqueio): dos ids recebidos, os que já estão em rotas CONFIRMADAS de hoje (dia de Brasília), com o número da rota,
    o motorista, o turno, a loja, o nome de quem confirmou (sem e-mail) e a hora. Usa só o id do pedido; nada do corpo vai para log.
    """
    dia = rotas_realizadas.hoje_em_brasilia()
    return {"data": dia.isoformat(), "pedidos": await _com_conexao_frota(lambda c: rotas_realizadas.ja_roteirizados(c, dados.ids, dia))}


def _data_do_filtro(texto: Optional[str], padrao):
    if texto is None or not str(texto).strip():
        return padrao
    try:
        return date.fromisoformat(str(texto).strip()[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail="Data inválida. Use o formato aaaa-mm-dd.")


@app.get("/api/historico")
async def historico_de_rotas(
    de: Optional[str] = None, ate: Optional[str] = None, loja: Optional[str] = None, motorista_id: Optional[int] = None,
    operador_nome: Optional[str] = None, q: Optional[str] = None, desfeitas: bool = False, limite: int = 50, deslocamento: int = 0,
    operador: Operador = Depends(obter_operador_atual),
):
    """
    Histórico das rotas confirmadas (padrão: últimos 7 dias), agrupável por dia, loja e motorista-rota, com os pedidos de cada rota (id e endereço; o endereço
    some depois de HISTORICO_DIAS). Filtros por período, loja, motorista, operador (pelo nome) e busca (id do pedido ou trecho do endereço). Paginado.
    """
    hoje = rotas_realizadas.hoje_em_brasilia()
    padrao_de, padrao_ate = rotas_realizadas.periodo_padrao(hoje)
    de_dia, ate_dia = _data_do_filtro(de, padrao_de), _data_do_filtro(ate, padrao_ate)
    if de_dia > ate_dia:
        raise HTTPException(status_code=422, detail="A data inicial precisa ser antes da data final.")

    async def consultar(c):
        await rotas_realizadas.limpeza_preguicosa(c, hoje, HISTORICO_DIAS)
        return await rotas_realizadas.historico(c, de_dia, ate_dia, loja, motorista_id, operador_nome, q, desfeitas, limite, deslocamento)

    resposta = await _com_conexao_frota(consultar)
    return {"hoje": hoje.isoformat(), "de": de_dia.isoformat(), "ate": ate_dia.isoformat(), "dias_retencao": HISTORICO_DIAS, **resposta}


@app.get("/api/historico/filtros")
async def filtros_do_historico(de: Optional[str] = None, ate: Optional[str] = None, operador: Operador = Depends(obter_operador_atual)):
    """Lojas, motoristas e operadores (só nomes) do período, para os seletores de filtro do histórico."""
    hoje = rotas_realizadas.hoje_em_brasilia()
    padrao_de, padrao_ate = rotas_realizadas.periodo_padrao(hoje)
    de_dia, ate_dia = _data_do_filtro(de, padrao_de), _data_do_filtro(ate, padrao_ate)
    return await _com_conexao_frota(lambda c: rotas_realizadas.filtros_do_historico(c, de_dia, ate_dia))


@app.post("/api/rotas-realizadas/{execucao_id}/desfazer")
async def desfazer_confirmacao(execucao_id: str, operador: Operador = Depends(obter_operador_atual)):
    """Marca as rotas confirmadas desta roteirização como canceladas (não apaga); elas deixam de contar."""
    dia = rotas_realizadas.hoje_em_brasilia()
    return await _com_conexao_frota(lambda c: rotas_realizadas.desfazer(c, execucao_id, dia))


class RegistroOperadorSchema(BaseModel):
    nome: str
    email: EmailStr
    senha: str
    codigo_convite: str

class LoginSchema(BaseModel):
    email: EmailStr
    senha: str

@app.post("/api/auth/register")
def registrar_operador(dados: RegistroOperadorSchema, db: Session = Depends(get_db)):
    # Sem OPERATOR_INVITE_CODE configurado no ambiente, o cadastro fica
    # bloqueado por padrão — mais seguro do que deixar aberto por engano.
    if not OPERATOR_INVITE_CODE or dados.codigo_convite != OPERATOR_INVITE_CODE:
        raise HTTPException(status_code=403, detail="Código de convite inválido.")

    existente = db.query(Operador).filter(Operador.email == dados.email).first()
    if existente:
        raise HTTPException(status_code=400, detail="E-mail já cadastrado.")
    
    novo_operador = Operador(
        nome=dados.nome,
        email=dados.email,
        senha_hash=gerar_hash_senha(dados.senha)
    )
    db.add(novo_operador)
    db.commit()
    db.refresh(novo_operador)
    return {"mensagem": "Operador cadastrado com sucesso", "id": novo_operador.id, "nome": novo_operador.nome}

@app.post("/api/auth/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Em vez de dados.email, o form_data entrega em form_data.username
    operador = db.query(Operador).filter(Operador.email == form_data.username).first()

    if not operador or not verificar_senha_hash(form_data.password, operador.senha_hash):
        raise HTTPException(status_code=400, detail="E-mail ou senha incorretos")

    token = criar_token_acesso(data={"sub": operador.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "operador": {"id": operador.id, "nome": operador.nome, "email": operador.email},
    }

@app.get("/api/auth/me")
def obter_perfil(operador_atual: Operador = Depends(obter_operador_atual)):
    return {"id": operador_atual.id, "nome": operador_atual.nome, "email": operador_atual.email}