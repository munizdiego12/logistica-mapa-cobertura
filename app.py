import os
import logging
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from config import MODAIS, ORIGEM_PADRAO, PRECO_GASOLINA_LITRO, CUSTO_HOMEM_HORA
from logistica.validation import sanitizar_cep, validar_e_higienizar_dataframe
from logistica.geocoding import GeocoderSP
from logistica.routing import sequenciar_rotas_nearest_neighbor, obter_trajeto_asfalto_osrm
from logistica.costs import calcular_custo_operacional
from logistica.mapping import construir_mapa, gerar_link_google_maps

logger = logging.getLogger("AppStreamlit")

# ==========================================
# CONFIGURAÇÃO DA PÁGINA
# ==========================================
st.set_page_config(
    page_title="Hub Logístico SP | Roteirização & Precificação",
    page_icon="🚚",
    layout="wide"
)

st.title("🚚 Hub Logístico SP - Roteirização & Precificação Last-Mile")
st.markdown("Otimização de frotas sobre malha viária real, cálculo de custos operacionais e roteirização urbana.")

# ==========================================
# BARRA LATERAL
# ==========================================
st.sidebar.header("⚙️ Parâmetros Operacionais")

st.sidebar.subheader("📍 Centro de Distribuição / Loja")
origem_rua = st.sidebar.text_input("Logradouro", value=ORIGEM_PADRAO["logradouro"])
origem_num = st.sidebar.text_input("Número", value=ORIGEM_PADRAO["numero"])
origem_bairro = st.sidebar.text_input("Bairro", value=ORIGEM_PADRAO["bairro"])
origem_cep = st.sidebar.text_input("CEP", value=ORIGEM_PADRAO["cep"])

st.sidebar.subheader("🚗 Veículo e Precificação")
modal_selecionado = st.sidebar.selectbox("Modal de Entrega", list(MODAIS.keys()), index=0)
preco_gasolina = st.sidebar.number_input("Preço Gasolina (R$/L)", value=float(PRECO_GASOLINA_LITRO), step=0.10)
custo_hora = st.sidebar.number_input("Custo Motorista (R$/h)", value=float(CUSTO_HOMEM_HORA), step=1.00)

st.sidebar.subheader("📁 Carga de Pedidos")
arquivo_carregado = st.sidebar.file_uploader("Suba a planilha de entregas (.csv ou .xlsx)", type=["csv", "xlsx"])

# ==========================================
# CARREGAMENTO E HIGIENIZAÇÃO DE DADOS
# ==========================================
df_pedidos = None

if arquivo_carregado is not None:
    try:
        if arquivo_carregado.name.endswith(".csv"):
            df_raw = pd.read_csv(arquivo_carregado)
        else:
            df_raw = pd.read_excel(arquivo_carregado)
            
        df_pedidos = validar_e_higienizar_dataframe(df_raw)
    except Exception as e:
        logger.exception("Erro ao validar arquivo enviado pelo usuário:")
        st.error(f"⚠️ {str(e) if isinstance(e, (KeyError, ValueError)) else 'Falha ao processar o arquivo. Verifique o formato e as colunas obrigatórias.'}")
        st.stop()
else:
    caminho_padrao = "data/pedidos.csv"
    if os.path.exists(caminho_padrao):
        try:
            df_pedidos = validar_e_higienizar_dataframe(pd.read_csv(caminho_padrao))
            st.info("💡 Usando base modelo padrão (`data/pedidos.csv`). Você pode subir sua própria planilha pela barra lateral.")
        except Exception:
            logger.exception("Erro ao ler base padrão:")
            st.error("Erro interno ao carregar a base padrão de pedidos.")
            st.stop()
    else:
        st.warning("Envie uma planilha na barra lateral para iniciar o processamento.")
        st.stop()

# ==========================================
# GEOCODIFICAÇÃO E ROTEIRIZAÇÃO
# ==========================================
geocoder = GeocoderSP()
cep_origem_limpo = sanitizar_cep(origem_cep)
origem_coords = geocoder.geocodificar(origem_rua, origem_num, origem_bairro, cep_origem_limpo)

# Georreferenciamento com barra de progresso visual
total_linhas = len(df_pedidos)
barra_progresso = st.progress(0, text="Georreferenciando entregas...")

lats, lons = [], []
for idx_row, (_, row) in enumerate(df_pedidos.iterrows()):
    lat, lon = geocoder.geocodificar(str(row["Logradouro"]), str(row["Numero"]), str(row["Bairro"]), row["CEP_LIMPO"])
    lats.append(lat)
    lons.append(lon)
    barra_progresso.progress((idx_row + 1) / total_linhas, text=f"Georreferenciando pedido {idx_row + 1} de {total_linhas}...")

barra_progresso.empty()

df_processado = df_pedidos.copy()
df_processado["lat"] = lats
df_processado["lon"] = lons

# Otimização VRP
capacidade = MODAIS[modal_selecionado].capacidade
rotas = sequenciar_rotas_nearest_neighbor(origem_coords, df_processado.to_dict("records"), capacidade)

# ==========================================
# CONSOLIDAÇÃO DE KPIS
# ==========================================
km_geral = 0.0
custo_geral = 0.0
resumo_rotas = []

for idx, rota in enumerate(rotas, 1):
    pontos = [origem_coords] + [(p['lat'], p['lon']) for p in rota] + [origem_coords]
    geometria, km_real, tempo_transito_h = obter_trajeto_asfalto_osrm(pontos)
    met = calcular_custo_operacional(km_real, tempo_transito_h, len(rota), modal_selecionado)
    link_maps = gerar_link_google_maps(origem_coords, rota)
    
    km_geral += met["km_total"]
    custo_geral += met["custo_total"]
    
    resumo_rotas.append({
        "Rota": f"Rota #{idx}",
        "Qtd Pedidos": len(rota),
        "Distância Real (km)": met["km_total"],
        "Tempo Estimado": met["tempo_formatado"],
        "Custo Total (R$)": met["custo_total"],
        "Custo por Pedido (R$)": met["custo_por_pedido"],
        "Link GPS": link_maps
    })

df_resumo = pd.DataFrame(resumo_rotas)
custo_medio_pedido = custo_geral / len(df_processado) if len(df_processado) > 0 else 0.0

# ==========================================
# EXIBIÇÃO: CARDS EXECUTIVOS
# ==========================================
st.markdown("---")
col1, col2, col3, col4 = st.columns(4)
col1.metric("📦 Total de Pedidos", f"{len(df_processado)}")
col2.metric("🚗 Veículos / Rotas", f"{len(rotas)}")
col3.metric("🛣️ Quilometragem Total", f"{km_geral:.1f} km")
col4.metric("💰 Custo Total Estimado", f"R$ {custo_geral:.2f}", f"R$ {custo_medio_pedido:.2f} / entrega")

# ==========================================
# EXIBIÇÃO: MAPA E DETALHES
# ==========================================
st.markdown("### 🗺️ Visualização Espacial & Roteamento")
mapa_folium = construir_mapa(origem_coords, rotas, modal_selecionado)
st_folium(mapa_folium, width=None, height=520, use_container_width=True, returned_objects=[])

st.markdown("### 📊 Detalhamento Operacional por Veículo")
st.dataframe(
    df_resumo,
    column_config={
        "Link GPS": st.column_config.LinkColumn("Navegação Mobile (Waze/Maps)", display_text="Abrir Rota")
    },
    use_container_width=True,
    hide_index=True
)

csv_export = df_resumo.to_csv(index=False).encode('utf-8')
st.download_button(
    label="📥 Baixar Relatório Operacional em CSV",
    data=csv_export,
    file_name="planejamento_rotas_sp.csv",
    mime="text/csv"
)