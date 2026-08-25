import io
import math
import requests
import pandas as pd
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import math
from fastapi.responses import StreamingResponse

app = FastAPI(title="Zubale Routing Core - Polar Clustering & Vehicle Allocation")

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

# Dicionário Geoespacial Preciso para São Paulo
COORDENADAS_PONTOS_SP = {
    'paulista': (-23.5614, -46.6559),
    'augusta': (-23.5539, -46.6575),
    'oscar freire': (-23.5630, -46.6698),
    'santos': (-23.5670, -46.6520),
    'consolacao': (-23.5505, -46.6542),
    'consolação': (-23.5505, -46.6542),
    'brigadeiro': (-23.5678, -46.6489),
    'faria lima': (-23.5866, -46.6823),
    'pinheiros': (-23.5663, -46.6912),
    'fradique': (-23.5601, -46.6890),
    'harmonia': (-23.5540, -46.6910),
    'pedroso de morais': (-23.5580, -46.6950),
    'maracatins': (-23.6080, -46.6610),
    'ibirapuera': (-23.6020, -46.6600),
    'macuco': (-23.6010, -46.6660),
    'antonio jose dos santos': (-23.6120, -46.6880),
    'antônio josé dos santos': (-23.6120, -46.6880),
    'vieira de morais': (-23.6210, -46.6780),
    'domingos de morais': (-23.5850, -46.6380),
    'vergueiro': (-23.5780, -46.6400),
    'tuiuti': (-23.5410, -46.5750),
    'serra de braganca': (-23.5430, -46.5680),
    'serra de bragança': (-23.5430, -46.5680),
    'mooca': (-23.5580, -46.5980),
    'braz leme': (-23.5080, -46.6420),
    'voluntarios da patria': (-23.5010, -46.6260),
    'voluntários da pátria': (-23.5010, -46.6260)
}

def geocode_endereco(rua: str, numero: str = "", bairro: str = "", cidade: str = "São Paulo", uf: str = "SP"):
    r_lower = (rua or "").lower()
    for chave, coords in COORDENADAS_PONTOS_SP.items():
        if chave in r_lower:
            num_offset = (int(''.join(filter(str.isdigit, str(numero))) or 1) % 50) * 0.0001
            return coords[0] + num_offset, coords[1] + num_offset

    query = f"{rua}, {numero}, {bairro}, {cidade} - {uf}, Brasil"
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={query}&limit=1"
    headers = {'User-Agent': 'ZubaleSpatialRouting/3.0'}
    
    try:
        res = requests.get(url, headers=headers, timeout=4)
        data = res.json()
        if data and len(data) > 0:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception:
        pass
    
    # Coordenada base central com separação determinística
    hash_val = sum(ord(c) for c in (rua + str(numero))) % 50
    return -23.5505 + (hash_val * 0.001), -46.6333 + (hash_val * 0.001)

def dist_coords(c1, c2):
    return math.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2)

# Otimização TSP 2-Opt para menor trajeto interno
def ordenar_paradas_otimizadas(origem_coords, lista_pedidos):
    if len(lista_pedidos) <= 1:
        return lista_pedidos

    nao_visitados = list(lista_pedidos)
    rota_ordenada = []
    ponto_atual = origem_coords

    while nao_visitados:
        proximo = min(
            nao_visitados, 
            key=lambda p: dist_coords(ponto_atual, (p['lat'], p['lon']))
        )
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

# Agrupamento Espacial por Setores Angulares (Polígonos Geográficos)
def agrupar_pedidos_por_poligono_setorial(origem_lat, origem_lon, pedidos, max_por_rota=6):
    if not pedidos:
        return []

    # Calcula o ângulo de cada entrega em relação ao Hub Central
    for p in pedidos:
        d_lat = p['lat'] - origem_lat
        d_lon = p['lon'] - origem_lon
        p['angulo'] = math.atan2(d_lat, d_lon)
        p['dist_hub'] = math.sqrt(d_lat**2 + d_lon**2)

    # Ordena os pedidos pela rotação angular em torno da cidade
    pedidos_ordenados = sorted(pedidos, key=lambda x: x['angulo'])

    clusters = []
    cluster_atual = []

    for p in pedidos_ordenados:
        if len(cluster_atual) >= max_por_rota:
            clusters.append(cluster_atual)
            cluster_atual = []
        elif cluster_atual:
            # Se o novo ponto estiver em quadrante muito distante, abre novo setor
            diff_ang = abs(p['angulo'] - cluster_atual[0]['angulo'])
            if diff_ang > 1.2:  # ~70 graus de diferença
                clusters.append(cluster_atual)
                cluster_atual = []

        cluster_atual.append(p)

    if cluster_atual:
        clusters.append(cluster_atual)

    return clusters

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

        # 1. Geocodifica a Loja Central
        orig_lat, orig_lon = geocode_endereco(
            req.origem_rua, req.origem_num, req.origem_bairro or "", "São Paulo", "SP"
        )
        origem_dict = {
            "rua": req.origem_rua,
            "numero": req.origem_num,
            "lat": orig_lat,
            "lon": orig_lon
        }

        # 2. Geocodifica todos os Pedidos
        pedidos_geo = []
        for p in req.pedidos:
            rua = p.get("Endereco") or p.get("rua") or ""
            num = str(p.get("Numero") or p.get("numero") or "")
            bairro = p.get("Bairro") or p.get("bairro") or ""
            cep = p.get("CEP") or p.get("cep") or ""
            vol = p.get("Volume") or p.get("volume") or 1
            
            p_lat, p_lon = geocode_endereco(rua, num, bairro)
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

        # 3. Frota
        frota_usar = req.frota if req.frota and len(req.frota) > 0 else [
            MotoristaItem(id=1, motorista="Motorista 01", modal="Carro de Passeio")
        ]

        # 4. Agrupamento por Setor/Polígono Regional
        max_setor = max(1, sum(modais_usar.get(f.modal, {'capacidade': 6})['capacidade'] for f in frota_usar) // len(frota_usar))
        clusters_setoriais = agrupar_pedidos_por_poligono_setorial(orig_lat, orig_lon, pedidos_geo, max_por_rota=max_setor)

        # 5. Distribuição de Viagens e Rotas
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

            # Rota interna otimizada no setor
            pts_rota = ordenar_paradas_otimizadas((orig_lat, orig_lon), cluster)

            # Carimba em cada pedido o modal e motorista alocado
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

def haversine_distance(coord1: tuple, coord2: tuple) -> float:
    """Calcula a distância exata em km entre dois pontos usando Haversine em radianos."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371.0  # Raio da Terra em km

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

class RaioCepRequest(BaseModel):
    origem_rua: str
    origem_num: str
    origem_cep: Optional[str] = ""
    raio_km: Optional[float] = 30.0

@app.post("/api/cobertura-ceps")
def gerar_cobertura_ceps(req: RaioCepRequest):
    orig_lat, orig_lon = geocode_endereco(req.origem_rua, req.origem_num, "", "São Paulo", "SP")
    hub_coords = (orig_lat, orig_lon)

    # Varre as bases de CEPs e calcula Haversine
    ceps_no_raio = []
    for chave, coords in COORDENADAS_PONTOS_SP.items():
        dist = haversine_distance(hub_coords, coords)
        if dist <= req.raio_km:
            ceps_no_raio.append({
                "localidade": chave.title(),
                "distancia_km": round(dist, 2),
                "lat": coords[0],
                "lon": coords[1]
            })

    # Ordena do mais próximo para o mais distante
    ceps_no_raio.sort(key=lambda x: x["distancia_km"])
    return {
        "hub": {"lat": orig_lat, "lon": orig_lon, "endereco": f"{req.origem_rua}, {req.origem_num}"},
        "raio_limite_km": req.raio_km,
        "total_pontos": len(ceps_no_raio),
        "pontos_cobertos": ceps_no_raio
    }

# Base de Faixas de CEPs por Regiões/Municípios de SP (Raio 0 a 30 km)
FAIXAS_CEPS_SP = [
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Bela Vista / Paulista", "cep_ini": "01300000", "cep_fim": "01399999", "lat": -23.5614, "lon": -46.6559},
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Consolação / Higienópolis", "cep_ini": "01200000", "cep_fim": "01299999", "lat": -23.5505, "lon": -46.6542},
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Jardins / Cerqueira César", "cep_ini": "01400000", "cep_fim": "01499999", "lat": -23.5630, "lon": -46.6698},
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Pinheiros / Vila Madalena", "cep_ini": "05400000", "cep_fim": "05499999", "lat": -23.5663, "lon": -46.6912},
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Itaim Bibi / Faria Lima", "cep_ini": "04530000", "cep_fim": "04549999", "lat": -23.5866, "lon": -46.6823},
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Moema / Indianópolis", "cep_ini": "04070000", "cep_fim": "04089999", "lat": -23.6080, "lon": -46.6610},
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Vila Mariana / Saúde", "cep_ini": "04000000", "cep_fim": "04199999", "lat": -23.5850, "lon": -46.6380},
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Brooklin / Campo Belo", "cep_ini": "04600000", "cep_fim": "04699999", "lat": -23.6210, "lon": -46.6780},
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Mooca / Tatuapé", "cep_ini": "03100000", "cep_fim": "03399999", "lat": -23.5410, "lon": -46.5750},
    {"ibge": 3550308, "uf": "SP", "cidade": "São Paulo", "bairro": "Santana / Zona Norte", "cep_ini": "02000000", "cep_fim": "02499999", "lat": -23.5080, "lon": -46.6420},
    {"ibge": 3534401, "uf": "SP", "cidade": "Osasco", "bairro": "Centro / Industrial", "cep_ini": "06000000", "cep_fim": "06299999", "lat": -23.5329, "lon": -46.7920},
    {"ibge": 3505708, "uf": "SP", "cidade": "Barueri / Alphaville", "bairro": "Geral", "cep_ini": "06400000", "cep_fim": "06499999", "lat": -23.5110, "lon": -46.8760},
    {"ibge": 3518800, "uf": "SP", "cidade": "Guarulhos", "bairro": "Centro / Aeroporto", "cep_ini": "07000000", "cep_fim": "07399999", "lat": -23.4540, "lon": -46.5330},
    {"ibge": 3548708, "uf": "SP", "cidade": "São Bernardo do Campo", "bairro": "Geral", "cep_ini": "09700000", "cep_fim": "09899999", "lat": -23.6910, "lon": -46.5650},
    {"ibge": 3547809, "uf": "SP", "cidade": "Santo André", "bairro": "Geral", "cep_ini": "09000000", "cep_fim": "09299999", "lat": -23.6570, "lon": -46.5310},
    {"ibge": 3548807, "uf": "SP", "cidade": "São Caetano do Sul", "bairro": "Geral", "cep_ini": "09500000", "cep_fim": "09599999", "lat": -23.6220, "lon": -46.5540},
    {"ibge": 3552809, "uf": "SP", "cidade": "Taboão da Serra", "bairro": "Geral", "cep_ini": "06750000", "cep_fim": "06799999", "lat": -23.6010, "lon": -46.7580},
    {"ibge": 3515004, "uf": "SP", "cidade": "Embu das Artes", "bairro": "Geral", "cep_ini": "06800000", "cep_fim": "06849999", "lat": -23.6490, "lon": -46.8520},
    {"ibge": 3513009, "uf": "SP", "cidade": "Cotia / Granja Viana", "bairro": "Geral", "cep_ini": "06700000", "cep_fim": "06729999", "lat": -23.6030, "lon": -46.9190}
]

@app.post("/api/cobertura-ceps")
def gerar_cobertura_ceps(req: RaioCepRequest):
    orig_lat, orig_lon = geocode_endereco(req.origem_rua, req.origem_num, "", "São Paulo", "SP")
    hub_coords = (orig_lat, orig_lon)

    ceps_no_raio = []
    for item in FAIXAS_CEPS_SP:
        dist = haversine_distance(hub_coords, (item["lat"], item["lon"]))
        if dist <= req.raio_km:
            ceps_no_raio.append({
                "ibge": item["ibge"],
                "uf": item["uf"],
                "cidade": item["cidade"],
                "bairro": item["bairro"],
                "cep_inicial": item["cep_ini"],
                "cep_final": item["cep_fim"],
                "distancia_km": round(dist, 2),
                "dias_sla": 1 if dist <= 12 else 2,
                "lat": item["lat"],
                "lon": item["lon"]
            })

    ceps_no_raio.sort(key=lambda x: x["distancia_km"])
    return {
        "hub": {"lat": orig_lat, "lon": orig_lon, "endereco": f"{req.origem_rua}, {req.origem_num}"},
        "raio_limite_km": req.raio_km,
        "total_pontos": len(ceps_no_raio),
        "pontos_cobertos": ceps_no_raio
    }