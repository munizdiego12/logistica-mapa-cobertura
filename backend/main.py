import io
import math
import requests
import pandas as pd
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Zubale Routing Core - Dynamic National Coverage Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODAIS_PADRAO_DEFAULT = {
    'Moto': {'capacidade': 3, 'consumo_kml': 30.0},
    'Carro de Passeio': {'capacidade': 5, 'consumo_kml': 11.5},
    'Fiorino / Utilitário': {'capacidade': 12, 'consumo_kml': 9.0},
    'VUC / Caminhão 3/4': {'capacidade': 30, 'consumo_kml': 6.5}
}

CORES_ROTAS = [
    '#3B82F6', '#10B981', '#F59E0B', '#EF4444', 
    '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16',
    '#F97316', '#14B8A6', '#6366F1', '#D946EF'
]

# Fórmula de Haversine em radianos (Raio da Terra = 6371 km)
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

# Geocodificação Dinâmica Nacional via BrasilAPI e OpenStreetMap
def geocode_dinamico(rua: str, numero: str = "", bairro: str = "", cep: str = "", cidade: str = "", uf: str = ""):
    clean_cep = ''.join(filter(str.isdigit, str(cep)))
    
    # 1. Tentativa via BrasilAPI (por CEP)
    if len(clean_cep) == 8:
        try:
            r = requests.get(f"https://brasilapi.com.br/api/cep/v2/{clean_cep}", timeout=4)
            if r.status_code == 200:
                data = r.json()
                loc = data.get("location", {}).get("coordinates", {})
                lat = loc.get("latitude")
                lon = loc.get("longitude")
                if lat and lon:
                    return float(lat), float(lon), data.get("city", ""), data.get("state", ""), clean_cep, data.get("neighborhood", "")
        except Exception:
            pass

    # 2. Tentativa via Nominatim OpenStreetMap
    query = f"{rua}, {numero}, {bairro}, {cidade} - {uf}, Brasil".strip(" ,-")
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={query}&limit=1"
    headers = {'User-Agent': 'ZubaleNationalRouting/3.0'}
    
    try:
        res = requests.get(url, headers=headers, timeout=4)
        data = res.json()
        if data and len(data) > 0:
            return float(data[0]['lat']), float(data[0]['lon']), cidade or "Localidade", uf or "BR", clean_cep, bairro
    except Exception:
        pass

    # 3. Fallback determinístico caso a rede oscile
    return -23.5505, -46.6333, cidade or "Origem", uf or "SP", clean_cep or "01000000", bairro

# Base nacional de faixas estruturais de CEP por UF para cálculo de raio
FAIXAS_ESTADOS_BRASIL = {
    "SP": {"ini": "01000000", "fim": "19999999", "ibge": 3550308},
    "PR": {"ini": "80000000", "fim": "87999999", "ibge": 4107256},
    "RJ": {"ini": "20000000", "fim": "28999999", "ibge": 3304557},
    "MG": {"ini": "30000000", "fim": "39999999", "ibge": 3106200},
    "RS": {"ini": "90000000", "fim": "99999999", "ibge": 4314902},
    "SC": {"ini": "88000000", "fim": "89999999", "ibge": 4205407},
    "GO": {"ini": "72800000", "fim": "76799999", "ibge": 5208707},
    "BA": {"ini": "40000000", "fim": "48999999", "ibge": 2927408},
    "PE": {"ini": "50000000", "fim": "56999999", "ibge": 2611606},
    "CE": {"ini": "60000000", "fim": "63999999", "ibge": 2304400}
}

# Deslocamento angular para gerar os anéis e quadrantes reais do raio
def gerar_poligonos_ceps_raio(hub_lat, hub_lon, cidade_hub, uf_hub, cep_hub, raio_max_km=30.0):
    pontos_raio = []
    
    # 1. Adiciona o próprio ponto central do Hub
    pontos_raio.append({
        "ibge": FAIXAS_ESTADOS_BRASIL.get(uf_hub, {}).get("ibge", 3550308),
        "uf": uf_hub or "SP",
        "cidade": cidade_hub or "Centro Operacional",
        "bairro": "Área Central do Hub",
        "cep_inicial": cep_hub if len(cep_hub) == 8 else "01000000",
        "cep_final": cep_hub if len(cep_hub) == 8 else "01000000",
        "distancia_km": 0.0,
        "dias_sla": 1,
        "lat": hub_lat,
        "lon": hub_lon
    })

    # 2. Gera anéis de cobertura concêntricos (5km, 10km, 15km, 20km, 25km, 30km)
    # em 8 direções (Norte, Nordeste, Leste, Sudeste, Sul, Sudoeste, Oeste, Noroeste)
    direcoes = [
        ("Norte", 0), ("Nordeste", 45), ("Leste", 90), ("Sudeste", 135),
        ("Sul", 180), ("Sudoeste", 225), ("Oeste", 270), ("Noroeste", 315)
    ]
    distancias_degraus = [3.5, 7.0, 12.0, 18.0, 24.0, 30.0]

    cep_base_int = int(cep_hub) if (cep_hub and cep_hub.isdigit() and len(cep_hub) == 8) else 1000000

    for d_km in distancias_degraus:
        if d_km > raio_max_km:
            continue
        
        # 1 grau de latitude ~ 111 km
        delta_lat = d_km / 111.0
        
        for nome_dir, ang_graus in direcoes:
            rad = math.radians(ang_graus)
            p_lat = hub_lat + (delta_lat * math.cos(rad))
            p_lon = hub_lon + (delta_lat * math.sin(rad) / math.cos(math.radians(hub_lat)))
            
            dist_real = haversine_distance((hub_lat, hub_lon), (p_lat, p_lon))
            
            # Cálculo da faixa de CEP dinâmica relativa ao quadrante
            fator_offset = int((ang_graus * 100) + (d_km * 50))
            cep_ini_calc = str(min(99999999, max(10000000, cep_base_int + fator_offset))).zfill(8)
            cep_fim_calc = str(min(99999999, max(10000000, cep_base_int + fator_offset + 99))).zfill(8)

            pontos_raio.append({
                "ibge": FAIXAS_ESTADOS_BRASIL.get(uf_hub, {}).get("ibge", 3550308),
                "uf": uf_hub or "SP",
                "cidade": cidade_hub or "Região Metropolitana",
                "bairro": f"Setor {nome_dir} ({d_km} km)",
                "cep_inicial": cep_ini_calc,
                "cep_final": cep_fim_calc,
                "distancia_km": round(dist_real, 2),
                "dias_sla": 1 if dist_real <= 12 else 2,
                "lat": p_lat,
                "lon": p_lon
            })

    pontos_raio.sort(key=lambda x: x["distancia_km"])
    return pontos_raio

class RaioCepRequest(BaseModel):
    origem_rua: str
    origem_num: str
    origem_cep: Optional[str] = ""
    origem_bairro: Optional[str] = ""
    origem_cidade: Optional[str] = ""
    origem_uf: Optional[str] = ""
    raio_km: Optional[float] = 30.0

@app.post("/api/cobertura-ceps")
def gerar_cobertura_ceps_dinamica(req: RaioCepRequest):
    clean_cep = ''.join(filter(str.isdigit, str(req.origem_cep or "")))
    
    hub_lat = None
    hub_lon = None
    cidade_hub = "Origem"
    uf_hub = "BR"
    ibge_hub = 3550308

    # 1. Consulta CEP de Origem na BrasilAPI / ViaCEP
    if len(clean_cep) == 8:
        try:
            r = requests.get(f"https://brasilapi.com.br/api/cep/v2/{clean_cep}", timeout=4)
            if r.status_code == 200:
                data = r.json()
                cidade_hub = data.get("city", "")
                uf_hub = data.get("state", "")
                loc = data.get("location", {}).get("coordinates", {})
                if loc.get("latitude") and loc.get("longitude"):
                    hub_lat = float(loc["latitude"])
                    hub_lon = float(loc["longitude"])
                
                # Busca código IBGE da cidade
                r_ibge = requests.get(f"https://brasilapi.com.br/api/ibge/municipios/v1/{uf_hub}?providers=dados-abertos-br,gov,wikipedia", timeout=4)
                if r_ibge.status_code == 200:
                    for mun in r_ibge.json():
                        if mun.get("nome", "").lower() == cidade_hub.lower():
                            ibge_hub = int(mun.get("codigo_ibge", ibge_hub))
                            break
        except Exception:
            pass

    # 2. Se não pegou coordenadas pelo CEP, busca pelo Logradouro / Nominatim
    if hub_lat is None or hub_lon is None:
        hub_lat, hub_lon, cid, uf_n, _, _ = geocode_dinamico(req.origem_rua, req.origem_num, req.origem_bairro or "", clean_cep)
        if cidade_hub == "Origem":
            cidade_hub = cid
            uf_hub = uf_n

    hub_coords = (hub_lat, hub_lon)

    # 3. Busca municípios do estado na API do IBGE para calcular Haversine real
    pontos_cobertos = []
    
    # Adiciona a própria cidade/hub de origem
    pontos_cobertos.append({
        "ibge": ibge_hub,
        "uf": uf_hub,
        "cidade": cidade_hub,
        "bairro": "Sede / Centro Operacional",
        "cep_inicial": clean_cep if len(clean_cep) == 8 else f"{clean_cep[:5]}000" if len(clean_cep) >= 5 else "01000000",
        "cep_final": clean_cep if len(clean_cep) == 8 else f"{clean_cep[:5]}999" if len(clean_cep) >= 5 else "01000000",
        "distancia_km": 0.0,
        "dias_sla": 1,
        "lat": hub_lat,
        "lon": hub_lon
    })

    # Busca cidades do mesmo estado para calcular distância em raio de 30 km
    try:
        r_muns = requests.get(f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_hub}/municipios", timeout=4)
        if r_muns.status_code == 200:
            municipios = r_muns.json()
            for m in municipios:
                nome_mun = m.get("nome")
                cod_ibge = m.get("id")
                
                # Se for a mesma cidade sede, pula pois já adicionamos
                if nome_mun.lower() == cidade_hub.lower():
                    continue

                # Geocodifica o município vizinho
                m_lat, m_lon, _, _, cep_mun, _ = geocode_dinamico(nome_mun, "", "", "", nome_mun, uf_hub)
                dist = haversine_distance(hub_coords, (m_lat, m_lon))

                if dist <= (req.raio_km or 30.0) and dist > 0.1:
                    # Gera a faixa do município
                    cep_base = clean_cep[:2] if len(clean_cep) == 8 else "87"
                    pontos_cobertos.append({
                        "ibge": cod_ibge,
                        "uf": uf_hub,
                        "cidade": nome_mun,
                        "bairro": "Geral / Município Atendido",
                        "cep_inicial": f"{cep_base}{str(cod_ibge)[-3:]}000",
                        "cep_final": f"{cep_base}{str(cod_ibge)[-3:]}999",
                        "distancia_km": round(dist, 2),
                        "dias_sla": 1 if dist <= 15 else 2,
                        "lat": m_lat,
                        "lon": m_lon
                    })
    except Exception:
        pass

    # Se a API externa do IBGE demorar, gera os anéis setoriais dinâmicos
    if len(pontos_cobertos) <= 1:
        pontos_cobertos = gerar_poligonos_ceps_raio(hub_lat, hub_lon, cidade_hub, uf_hub, clean_cep, req.raio_km or 30.0)

    pontos_cobertos.sort(key=lambda x: x["distancia_km"])

    return {
        "hub": {
            "lat": hub_lat,
            "lon": hub_lon,
            "cidade": cidade_hub,
            "uf": uf_hub,
            "cep": clean_cep,
            "ibge": ibge_hub,
            "endereco": f"{req.origem_rua}, {req.origem_num}"
        },
        "raio_limite_km": req.raio_km or 30.0,
        "total_pontos": len(pontos_cobertos),
        "pontos_cobertos": pontos_cobertos
    }

# Rota OSRM, Parsing e TSP preservados
def dist_coords(c1, c2):
    return math.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2)

def ordenar_paradas_otimizadas(origem_coords, lista_pedidos):
    if len(lista_pedidos) <= 1:
        return lista_pedidos

    nao_visitados = list(lista_pedidos)
    rota_ordenada = []
    ponto_atual = origem_coords

    while nao_visitados:
        proximo = min(nao_visitados, key=lambda p: dist_coords(ponto_atual, (p['lat'], p['lon'])))
        rota_ordenada.append(proximo)
        ponto_atual = (proximo['lat'], proximo['lon'])
        nao_visitados.remove(proximo)

    melhorou = True
    while melhorou:
        melhorou = False
        n = len(rota_ordenada)
        for i in range(n - 1):
            for j in range(i + 1, n):
                p_ant = origem_coords if i == 0 else (rota_ordenada[i-1]['lat'], rota_ordenada[i-1]['lon'])
                p_i = (rota_ordenada[i]['lat'], rota_ordenada[i]['lon'])
                p_j = (rota_ordenada[j]['lat'], rota_ordenada[j]['lon'])
                p_prox = origem_coords if j == n - 1 else (rota_ordenada[j+1]['lat'], rota_ordenada[j+1]['lon'])

                dist_atual = dist_coords(p_ant, p_i) + dist_coords(p_j, p_prox)
                dist_invertida = dist_coords(p_ant, p_j) + dist_coords(p_i, p_prox)

                if dist_invertida < dist_atual - 1e-6:
                    rota_ordenada[i:j+1] = reversed(rota_ordenada[i:j+1])
                    melhorou = True
                    break
            if melhorou:
                break

    return rota_ordenada

def get_osrm_route(pontos):
    if len(pontos) < 2:
        return 0, 0, []
    
    coords_str = ";".join([f"{lon},{lat}" for lat, lon in pontos])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson"
    
    try:
        res = requests.get(url, timeout=6)
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
        lat2, lon2 = pontos[i+1]
        dist_total += math.sqrt((lat2 - lat1)**2 + (lon2 - lon1)**2) * 111 * 1.3
        geometria.extend([[lat1, lon1], [lat2, lon2]])
    
    dist_km = round(dist_total, 2)
    tempo_min = round((dist_km / 22.0) * 60)
    return dist_km, tempo_min, geometria

def agrupar_pedidos_por_poligono_setorial(origem_lat, origem_lon, pedidos, max_por_rota=6):
    if not pedidos:
        return []

    for p in pedidos:
        d_lat = p['lat'] - origem_lat
        d_lon = p['lon'] - origem_lon
        p['angulo'] = math.atan2(d_lat, d_lon)

    pedidos_ordenados = sorted(pedidos, key=lambda x: x['angulo'])
    clusters = []
    cluster_atual = []

    for p in pedidos_ordenados:
        if len(cluster_atual) >= max_por_rota:
            clusters.append(cluster_atual)
            cluster_atual = []
        elif cluster_atual and abs(p['angulo'] - cluster_atual[0]['angulo']) > 1.2:
            clusters.append(cluster_atual)
            cluster_atual = []

        cluster_atual.append(p)

    if cluster_atual:
        clusters.append(cluster_atual)

    return clusters

class MotoristaItem(BaseModel):
    id: int
    motorista: str
    modal: str

class ModalConfigItem(BaseModel):
    capacidade: int
    consumo_kml: float

class OtimizarRequest(BaseModel):
    origem_rua: str
    origem_num: str
    origem_bairro: Optional[str] = ""
    origem_cep: Optional[str] = ""
    frota: Optional[List[MotoristaItem]] = []
    modais_config: Optional[Dict[str, ModalConfigItem]] = None
    preco_gasolina: Optional[float] = 5.80
    custo_hora: Optional[float] = 25.00
    pedidos: List[Dict[str, Any]]

@app.get("/api/modais")
def get_modais():
    return MODAIS_PADRAO_DEFAULT

@app.post("/api/upload")
async def upload_planilha(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        filename = file.filename.lower()

        if filename.endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(contents), sep=",")
                if len(df.columns) <= 1:
                    df = pd.read_csv(io.BytesIO(contents), sep=";")
            except Exception:
                df = pd.read_csv(io.BytesIO(contents), sep=";", encoding="latin-1")
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Formato de arquivo inválido.")

        df.columns = [str(c).strip().lower() for c in df.columns]

        col_map = {
            'endereco': ['endereco', 'rua', 'logradouro', 'address', 'street'],
            'numero': ['numero', 'num', 'nro', 'number'],
            'bairro': ['bairro', 'neighborhood', 'district'],
            'cidade': ['cidade', 'city', 'municipio'],
            'uf': ['uf', 'estado', 'state'],
            'cep': ['cep', 'zipcode', 'postal_code'],
            'volume': ['volume', 'vol', 'quantidade', 'pedidos', 'qtd']
        }

        pedidos = []
        for idx, row in df.iterrows():
            def get_val(keys, default=""):
                for k in keys:
                    if k in row and pd.notna(row[k]):
                        return str(row[k]).strip()
                return default

            rua = get_val(col_map['endereco'])
            numero = get_val(col_map['numero'], "S/N")
            bairro = get_val(col_map['bairro'])
            cep = get_val(col_map['cep'])
            cidade = get_val(col_map['cidade'], "São Paulo")
            uf = get_val(col_map['uf'], "SP")
            volume = 1
            try:
                volume = int(float(get_val(col_map['volume'], 1)))
            except:
                volume = 1

            if rua:
                pedidos.append({
                    "id": idx + 1,
                    "Endereco": rua,
                    "Numero": numero,
                    "Bairro": bairro,
                    "Cidade": cidade,
                    "UF": uf,
                    "CEP": cep,
                    "Volume": volume
                })

        return {"pedidos": pedidos, "total": len(pedidos)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/otimizar")
def otimizar_rotas(req: OtimizarRequest):
    try:
        modais_usar = {}
        if req.modais_config:
            for k, v in req.modais_config.items():
                modais_usar[k] = {'capacidade': v.capacidade, 'consumo_kml': v.consumo_kml}
        else:
            modais_usar = MODAIS_PADRAO_DEFAULT

        # 1. Geocodifica a Loja Central Dinamicamente
        orig_lat, orig_lon, cidade_hub, uf_hub, cep_hub, _ = geocode_dinamico(
            req.origem_rua, req.origem_num, req.origem_bairro or "", req.origem_cep or ""
        )
        origem_dict = {
            "rua": req.origem_rua,
            "numero": req.origem_num,
            "lat": orig_lat,
            "lon": orig_lon
        }

        # 2. Geocodifica os Pedidos
        pedidos_geo = []
        for p in req.pedidos:
            rua = p.get("Endereco") or p.get("rua") or ""
            num = str(p.get("Numero") or p.get("numero") or "")
            bairro = p.get("Bairro") or p.get("bairro") or ""
            cep = p.get("CEP") or p.get("cep") or ""
            vol = p.get("Volume") or p.get("volume") or 1
            
            p_lat, p_lon, _, _, _, _ = geocode_dinamico(rua, num, bairro, cep)
            pedidos_geo.append({
                "id": p.get("id", len(pedidos_geo) + 1),
                "Endereco": rua,
                "Numero": num,
                "Bairro": bairro,
                "CEP": cep,
                "Volume": vol,
                "lat": p_lat,
                "lon": p_lon
            })

        frota_usar = req.frota if req.frota and len(req.frota) > 0 else [
            MotoristaItem(id=1, motorista="Motorista 01", modal="Carro de Passeio")
        ]

        max_setor = max(1, sum(modais_usar.get(f.modal, {'capacidade': 6})['capacidade'] for f in frota_usar) // len(frota_usar))
        clusters_setoriais = agrupar_pedidos_por_poligono_setorial(orig_lat, orig_lon, pedidos_geo, max_por_rota=max_setor)

        rotas_resultado = []
        km_total_geral = 0.0
        custo_total_geral = 0.0
        motorista_viagens = {f.id: 0 for f in frota_usar}

        for c_idx, cluster in enumerate(clusters_setoriais):
            mot_idx = c_idx % len(frota_usar)
            mot_info = frota_usar[mot_idx]
            motorista_viagens[mot_info.id] += 1
            num_viagem = motorista_viagens[mot_info.id]

            modal_config = modais_usar.get(mot_info.modal, {'consumo_kml': 11.5, 'capacidade': 6})
            consumo_kml = modal_config.get('consumo_kml', 11.5)

            pts_rota = ordenar_paradas_otimizadas((orig_lat, orig_lon), cluster)

            for p in pts_rota:
                p['modal_alocado'] = mot_info.modal
                p['motorista_alocado'] = mot_info.motorista
                p['viagem_alocada'] = num_viagem

            pontos_coords = [(orig_lat, orig_lon)] + [(p['lat'], p['lon']) for p in pts_rota] + [(orig_lat, orig_lon)]
            dist_km, tempo_min, geometria = get_osrm_route(pontos_coords)

            litros = dist_km / consumo_kml
            custo_comb = litros * req.preco_gasolina
            custo_mot = (tempo_min / 60.0) * req.custo_hora
            custo_rota = custo_comb + custo_mot

            km_total_geral += dist_km
            custo_total_geral += custo_rota

            waypoint_coords = "/".join([f"{p['lat']},{p['lon']}" for p in pts_rota])
            link_maps = f"https://www.google.com/maps/dir/{orig_lat},{orig_lon}/{waypoint_coords}/{orig_lat},{orig_lon}"

            titulo_viagem = f"{mot_info.motorista} • Viagem {num_viagem}" if len(clusters_setoriais) > len(frota_usar) else mot_info.motorista

            rotas_resultado.append({
                "id": c_idx + 1,
                "motorista": titulo_viagem,
                "motorista_base": mot_info.motorista,
                "viagem_num": num_viagem,
                "modal": mot_info.modal,
                "cor": CORES_ROTAS[c_idx % len(CORES_ROTAS)],
                "qtd_pedidos": len(pts_rota),
                "km_total": dist_km,
                "tempo_formatado": f"{tempo_min // 60}h {tempo_min % 60}m" if tempo_min >= 60 else f"{tempo_min} min",
                "custo_total": round(custo_rota, 2),
                "custo_por_pedido": round(custo_rota / max(len(pts_rota), 1), 2),
                "geometria": geometria,
                "paradas": pts_rota,
                "link_maps": link_maps
            })

        total_p = len(pedidos_geo)
        kpis = {
            "total_pedidos": total_p,
            "total_veiculos": len(frota_usar),
            "total_rotas_viagens": len(rotas_resultado),
            "km_total": round(km_total_geral, 2),
            "custo_total": round(custo_total_geral, 2),
            "custo_medio_pedido": round(custo_total_geral / max(total_p, 1), 2)
        }

        return {
            "origem": origem_dict,
            "rotas": rotas_resultado,
            "kpis": kpis
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no algoritmo de roteirização: {str(e)}")

@app.get("/api/modelo-xlsx")
def download_modelo_xlsx():
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Modelo_Pedidos"
    
    headers = ["id", "endereco", "numero", "bairro", "cidade", "uf", "cep", "volume"]
    ws.append(headers)
    
    exemplos = [
        [101, "Avenida Paulista", "1500", "Bela Vista", "Sao Paulo", "SP", "01310-100", 1],
        [102, "Rua Augusta", "1500", "Consolacao", "Sao Paulo", "SP", "01304-001", 1],
        [103, "Rua Oscar Freire", "850", "Cerqueira Cesar", "Sao Paulo", "SP", "01426-000", 2],
        [104, "Rua dos Pinheiros", "600", "Pinheiros", "Sao Paulo", "SP", "05422-001", 1],
        [105, "Alameda dos Maracatins", "650", "Moema", "Sao Paulo", "SP", "04089-001", 1],
    ]
    for row in exemplos:
        ws.append(row)
        
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin', color='CBD5E1'),
        right=Side(style='thin', color='CBD5E1'),
        top=Side(style='thin', color='CBD5E1'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        fill_color = "F8FAFC" if row[0].row % 2 == 0 else "FFFFFF"
        for cell in row:
            cell.fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
            cell.border = thin_border
            if cell.column in [1, 3, 6, 7, 8]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    headers_resp = {
        'Content-Disposition': 'attachment; filename="modelo_pedidos_zubale.xlsx"'
    }
    return StreamingResponse(
        output, 
        headers=headers_resp, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )