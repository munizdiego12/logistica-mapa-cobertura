import io
import logging
from typing import List, Optional
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import MODAIS, ORIGEM_PADRAO, PRECO_GASOLINA_LITRO, CUSTO_HOMEM_HORA
from logistica.validation import sanitizar_cep, validar_e_higienizar_dataframe
from logistica.geocoding import GeocoderSP
from logistica.routing import sequenciar_rotas_nearest_neighbor, obter_trajeto_asfalto_osrm
from logistica.costs import calcular_custo_operacional

logger = logging.getLogger("FastAPILogistica")

app = FastAPI(
    title="API Hub Logístico SP",
    description="Motor de Roteirização Last-Mile e Inteligência Tarifária Urbana",
    version="2.0.0"
)

# Habilita CORS para o React acessar a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Schemas Pydantic
class PedidoInput(BaseModel):
    id_pedido: str
    cliente: str
    logradouro: str
    numero: str
    bairro: str
    cep: str
    volume: Optional[int] = 1

class OtimizacaoRequest(BaseModel):
    origem_rua: str = ORIGEM_PADRAO["logradouro"]
    origem_num: str = ORIGEM_PADRAO["numero"]
    origem_bairro: str = ORIGEM_PADRAO["bairro"]
    origem_cep: str = ORIGEM_PADRAO["cep"]
    modal: str = "Carro de Passeio"
    preco_gasolina: float = PRECO_GASOLINA_LITRO
    custo_hora: float = CUSTO_HOMEM_HORA
    pedidos: List[PedidoInput]

@app.get("/api/health")
def health_check():
    return {"status": "online", "version": "2.0.0", "engine": "FastAPI + OSRM"}

@app.get("/api/modais")
def listar_modais():
    return {
        nome: {
            "capacidade": config.capacidade,
            "consumo_km_l": config.consumo_km_l,
            "manutencao_km": config.manutencao_km
        }
        for nome, config in MODAIS.items()
    }

@app.post("/api/otimizar")
def otimizar_rotas(payload: OtimizacaoRequest):
    geocoder = GeocoderSP()
    
    # 1. Origem
    cep_orig_limpo = sanitizar_cep(payload.origem_cep)
    origem_coords = geocoder.geocodificar(
        payload.origem_rua, payload.origem_num, payload.origem_bairro, cep_orig_limpo
    )

    # 2. Geocodificação dos pedidos
    pedidos_processados = []
    for p in payload.pedidos:
        cep_limpo = sanitizar_cep(p.cep)
        lat, lon = geocoder.geocodificar(p.logradouro, str(p.numero), p.bairro, cep_limpo)
        pedidos_processados.append({
            "ID Pedido": p.id_pedido,
            "Cliente": p.cliente,
            "Logradouro": p.logradouro,
            "Numero": p.numero,
            "Bairro": p.bairro,
            "CEP": cep_limpo,
            "lat": lat,
            "lon": lon
        })

    # 3. Sequenciamento VRP
    capacidade = MODAIS.get(payload.modal, MODAIS["Carro de Passeio"]).capacidade
    rotas = sequenciar_rotas_nearest_neighbor(origem_coords, pedidos_processados, capacidade)

    # 4. Traçado OSRM e Métricas
    km_geral = 0.0
    custo_geral = 0.0
    rotas_response = []

    cores = ['#0043FC', '#F97316', '#10B981', '#8B5CF6', '#EC4899']

    for idx, rota in enumerate(rotas, 1):
        pontos = [origem_coords] + [(p['lat'], p['lon']) for p in rota] + [origem_coords]
        geometria, km_real, tempo_transito_h = obter_trajeto_asfalto_osrm(pontos)
        met = calcular_custo_operacional(
            km_real, tempo_transito_h, len(rota), payload.modal,
            preco_gasolina=payload.preco_gasolina, custo_hora=payload.custo_hora
        )
        
        km_geral += met["km_total"]
        custo_geral += met["custo_total"]

        # Link Google Maps
        coords_str = [f"{origem_coords[0]},{origem_coords[1]}"] + [f"{p['lat']},{p['lon']}" for p in rota] + [f"{origem_coords[0]},{origem_coords[1]}"]
        link_maps = "https://www.google.com/maps/dir/" + "/".join(coords_str)

        rotas_response.append({
            "id": idx,
            "cor": cores[(idx - 1) % len(cores)],
            "qtd_pedidos": len(rota),
            "pedidos": rota,
            "geometria": geometria,  # lista de [lat, lon] para renderizar direto no Leaflet
            "km_total": met["km_total"],
            "tempo_formatado": met["tempo_formatado"],
            "custo_total": met["custo_total"],
            "custo_por_pedido": met["custo_por_pedido"],
            "link_maps": link_maps
        })

    return {
        "origem": {
            "rua": payload.origem_rua,
            "numero": payload.origem_num,
            "bairro": payload.origem_bairro,
            "cep": payload.origem_cep,
            "lat": origem_coords[0],
            "lon": origem_coords[1]
        },
        "kpis": {
            "total_pedidos": len(pedidos_processados),
            "total_veiculos": len(rotas),
            "km_total": round(km_geral, 1),
            "custo_total": round(custo_geral, 2),
            "custo_medio_pedido": round(custo_geral / len(pedidos_processados), 2) if pedidos_processados else 0.0
        },
        "rotas": rotas_response
    }

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
            raise HTTPException(status_code=400, detail="Formato de arquivo não suportado (.csv ou .xlsx).")

        # Normaliza todos os nomes de colunas (minúsculo e sem espaços)
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Mapeamento inteligente de colunas
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

            if rua:  # Só adiciona se houver logradouro
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

        if not pedidos:
            raise HTTPException(status_code=400, detail="Nenhum endereço válido encontrado na planilha.")

        return {"pedidos": pedidos, "total": len(pedidos)}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao processar planilha: {str(e)}")