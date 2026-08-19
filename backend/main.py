import io
import math
import requests
import pandas as pd
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Zubale Routing Core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODAIS_PADRAO = {
    'Moto': {'capacidade': 10, 'consumo_kml': 30.0},
    'Carro de Passeio': {'capacidade': 25, 'consumo_kml': 11.5},
    'Fiorino / Van': {'capacidade': 60, 'consumo_kml': 9.0},
    'Fiorino / Utilitário': {'capacidade': 60, 'consumo_kml': 9.0},
    'VUC / Caminhão 3/4': {'capacidade': 150, 'consumo_kml': 6.5}
}

CORES_ROTAS = [
    '#3B82F6', '#10B981', '#F59E0B', '#EF4444', 
    '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16'
]

# Geocodificação robusta com User-Agent e Fallback inteligente para SP
def geocode_endereco(rua: str, numero: str = "", bairro: str = "", cidade: str = "São Paulo", uf: str = "SP"):
    query = f"{rua}, {numero}, {bairro}, {cidade} - {uf}, Brasil"
    url = f"https://nominatim.openstreetmap.org/search?format=json&q={query}&limit=1"
    headers = {'User-Agent': 'ZubaleEnterpriseLogisticsPlatform/2.0 (operations@zubale.com)'}
    
    try:
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        if data and len(data) > 0:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception:
        pass
    
    # Fallback por palavra-chave para endereços comuns de SP se a API externa demorar
    r_lower = rua.lower()
    if 'paulista' in r_lower:
        return -23.5614, -46.6559
    elif 'faria lima' in r_lower:
        return -23.5866, -46.6823
    elif 'augusta' in r_lower:
        return -23.5539, -46.6575
    elif 'oscar freire' in r_lower:
        return -23.5630, -46.6698
    elif 'consolacao' in r_lower or 'consolação' in r_lower:
        return -23.5505, -46.6542
    elif 'brigadeiro' in r_lower:
        return -23.5678, -46.6489
    elif 'pinheiros' in r_lower:
        return -23.5663, -46.6912
    elif 'fradique' in r_lower:
        return -23.5601, -46.6890
    elif 'maracatins' in r_lower or 'ibirapuera' in r_lower or 'moema' in r_lower:
        return -23.6050, -46.6630
    elif 'domingos de morais' in r_lower or 'vergueiro' in r_lower:
        return -23.5850, -46.6380
    
    # Coordenada central de São Paulo com pequeno desvio randômico determinístico
    hash_val = sum(ord(c) for c in (rua + str(numero))) % 100
    return -23.5505 + (hash_val * 0.0005), -46.6333 + (hash_val * 0.0005)

# Cálculo de rota e traçado viário via OSRM
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
            # Converte [lon, lat] retornado pelo geojson para [lat, lon] do Leaflet
            geometria = [[coord[1], coord[0]] for coord in route["geometry"]["coordinates"]]
            return dist_km, tempo_min, geometria
    except Exception:
        pass
    
    # Fallback Euclidiano/Manhattan viário se o OSRM falhar
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

class OtimizarRequest(BaseModel):
    origem_rua: str
    origem_num: str
    origem_bairro: Optional[str] = ""
    origem_cep: Optional[str] = ""
    modal: Optional[str] = "Carro de Passeio"
    frota: Optional[List[MotoristaItem]] = []
    preco_gasolina: Optional[float] = 5.80
    custo_hora: Optional[float] = 25.00
    pedidos: List[Dict[str, Any]]

@app.get("/api/modais")
def get_modais():
    return MODAIS_PADRAO

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

        # 2. Geocodifica os Pedidos
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

        # 3. Configura a frota
        frota_usar = req.frota if req.frota and len(req.frota) > 0 else [
            MotoristaItem(id=1, motorista="Motorista 01", modal=req.modal or "Carro de Passeio")
        ]
        num_rotas = min(len(frota_usar), len(pedidos_geo))
        if num_rotas == 0:
            num_rotas = 1

        # 4. Distribuição das entregas por veículo
        rotas_pedidos = [[] for _ in range(num_rotas)]
        for idx, p in enumerate(pedidos_geo):
            rotas_pedidos[idx % num_rotas].append(p)

        # 5. Cálculo das Rotas e Métricas Operacionais
        rotas_resultado = []
        km_total_geral = 0.0
        custo_total_geral = 0.0

        for r_idx in range(num_rotas):
            pts_rota = rotas_pedidos[r_idx]
            if not pts_rota:
                continue

            modal_info = frota_usar[r_idx]
            modal_config = MODAIS_PADRAO.get(modal_info.modal, {'consumo_kml': 10.0, 'capacidade': 30})
            consumo_kml = modal_config.get('consumo_kml', 10.0)

            pontos_coords = [(orig_lat, orig_lon)] + [(p['lat'], p['lon']) for p in pts_rota] + [(orig_lat, orig_lon)]
            dist_km, tempo_min, geometria = get_osrm_route(pontos_coords)

            # Cálculo de custos operacionais (Combustível + Horas do motorista)
            litros = dist_km / consumo_kml
            custo_comb = litros * req.preco_gasolina
            custo_mot = (tempo_min / 60.0) * req.custo_hora
            custo_rota = custo_comb + custo_mot

            km_total_geral += dist_km
            custo_total_geral += custo_rota

            # Link de navegação direta no Google Maps
            waypoint_coords = "/".join([f"{p['lat']},{p['lon']}" for p in pts_rota])
            link_maps = f"https://www.google.com/maps/dir/{orig_lat},{orig_lon}/{waypoint_coords}/{orig_lat},{orig_lon}"

            rotas_resultado.append({
                "id": r_idx + 1,
                "motorista": modal_info.motorista,
                "modal": modal_info.modal,
                "cor": CORES_ROTAS[r_idx % len(CORES_ROTAS)],
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
            "total_veiculos": len(rotas_resultado),
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