import os
import logging
from config import ORIGEM_PADRAO, MODAIS, PRECO_GASOLINA_LITRO, CUSTO_HOMEM_HORA
from logistica.validation import carregar_e_validar_csv
from logistica.geocoding import GeocoderSP
from logistica.routing import sequenciar_rotas_nearest_neighbor
from logistica.mapping import construir_mapa

logger = logging.getLogger("MainPipeline")

def executar_pipeline(caminho_csv: str = "data/pedidos.csv", nome_modal: str = "Carro de Passeio"):
    logger.info(f"Iniciando pipeline para modal '{nome_modal}'...")
    
    df = carregar_e_validar_csv(caminho_csv)
    geocoder = GeocoderSP()
    
    origem_coords = geocoder.geocodificar(
        ORIGEM_PADRAO["logradouro"], 
        ORIGEM_PADRAO["numero"], 
        ORIGEM_PADRAO["bairro"], 
        ORIGEM_PADRAO["cep"]
    )
    
    lats, lons = [], []
    for _, row in df.iterrows():
        lat, lon = geocoder.geocodificar(row["Logradouro"], str(row["Numero"]), row["Bairro"], row["CEP_LIMPO"])
        lats.append(lat)
        lons.append(lon)
    df["lat"] = lats
    df["lon"] = lons
    
    capacidade = MODAIS[nome_modal].capacidade
    rotas = sequenciar_rotas_nearest_neighbor(origem_coords, df.to_dict("records"), capacidade)
    
    mapa = construir_mapa(
        origem_coords, rotas, nome_modal, 
        preco_gasolina=PRECO_GASOLINA_LITRO, custo_hora=CUSTO_HOMEM_HORA
    )
    
    os.makedirs("maps", exist_ok=True)
    caminho_mapa = os.path.join("maps", "mapa_logistica_integrado.html")
    mapa.save(caminho_mapa)
    logger.info(f"Pipeline finalizado! Mapa gerado em: {caminho_mapa}")

if __name__ == "__main__":
    executar_pipeline()