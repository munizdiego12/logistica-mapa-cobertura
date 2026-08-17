import os
import hashlib
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
# BARRA LATERAL (PARÂMETROS E UPLOAD)
# ==========================================
st.sidebar.header("⚙️ Parâmetros Operacionais")

st.sidebar.subheader("📍 Centro de Distribuição / Loja")
origem_rua = st.sidebar.text_input("Logradouro", value=ORIGEM_PADRAO["logradouro"])
origem_num = st.sidebar.text_input("Número", value=ORIGEM_PADRAO["numero"])
origem_bairro = st.sidebar.text_input("Bairro", value=ORIGEM_PADRAO["bairro"])
origem_cep = st.sidebar.text_input("CEP", value=ORIGEM_PADRAO["cep"])

st.sidebar.subheader("🚗 Veículo e Precificação")
modal_selecionado = st.sidebar.selectbox("Modal de Entrega", list(MODAIS.keys()), index=0)
preco_gasolina = st.sidebar.number_input("Preço Gasolina (R$/L)", value=float(PRECO_GASOLINA_LITRO), min_value=1.0, max_value=20.0, step=0.10)
custo_hora = st.sidebar.number_input("Custo Motorista (R$/h)", value=float(CUSTO_HOMEM_HORA), min_value=5.0, max_value=200.0, step=1.00)

st.sidebar.subheader("📁 Carga de Pedidos")
arquivo_carregado = st.sidebar.file_uploader("Suba a planilha de entregas (.csv ou .xlsx)", type=["csv", "xlsx"])

# ==========================================
# FUNÇÃO DE PIPELINE COM CACHE
# ==========================================
@st.cache_data(show_spinner=False)
def executar_pipeline_otimizacao(df_records, rua_orig, num_orig, bairro_orig, cep_orig, modal_nome, p_gasolina, c_hora):
    """Executa geocoding, sequenciamento VRP, OSRM e cálculos com cache em memória."""
    geocoder = GeocoderSP()
    
    # 1. Geocodificar Origem
    cep_orig_limpo = sanitizar_cep(cep_orig)
    origem_coords = geocoder.geocodificar(rua_orig, num_orig, bairro_orig, cep_orig_limpo)
    
    # 2. Geocodificar Pedidos
    pedidos_processados = []
    for item in df_records:
        item_copy = item.copy()
        lat, lon = geocoder.geocodificar(
            str(item_copy["Logradouro"]), 
            str(item_copy["Numero"]), 
            str(item_copy["Bairro"]), 
            str(item_copy["CEP_LIMPO"])
        )
        item_copy["lat"] = lat
        item_copy["lon"] = lon
        pedidos_processados.append(item_copy)
        
    # 3. Sequenciamento VRP
    capacidade = MODAIS[modal_nome].capacidade
    rotas = sequenciar_rotas_nearest_neighbor(origem_coords, pedidos_processados, capacidade)
    
    # 4. Roteamento OSRM e Consolidação
    km_geral = 0.0
    custo_geral = 0.0
    resumo_rotas = []
    dados_calculados = []
    
    for idx, rota in enumerate(rotas, 1):
        pontos = [origem_coords] + [(p['lat'], p['lon']) for p in rota] + [origem_coords]
        geometria, km_real, tempo_transito_h = obter_trajeto_asfalto_osrm(pontos)
        
        met = calcular_custo_operacional(
            km_real, tempo_transito_h, len(rota), modal_nome,
            preco_gasolina=p_gasolina, custo_hora=c_hora
        )
        link_maps = gerar_link_google_maps(origem_coords, rota)
        
        km_geral += met["km_total"]
        custo_geral += met["custo_total"]
        
        dados_calculados.append({"geometria": geometria, "metricas": met})
        resumo_rotas.append({
            "Rota": f"Rota #{idx}",
            "Qtd Pedidos": len(rota),
            "Distância Real (km)": met["km_total"],
            "Tempo Estimado": met["tempo_formatado"],
            "Custo Total (R$)": met["custo_total"],
            "Custo por Pedido (R$)": met["custo_por_pedido"],
            "Link GPS": link_maps
        })
        
    return origem_coords, pedidos_processados, rotas, dados_calculados, resumo_rotas, km_geral, custo_geral

# ==========================================
# CARREGAMENTO E HIGIENIZAÇÃO DE DADOS
# ==========================================
df_pedidos = None

if arquivo_carregado is not None:
    # Trava preventiva por tamanho bruto em bytes (10 MB)
    if arquivo_carregado.size > 10 * 1024 * 1024:
        st.error("⚠️ O arquivo enviado excede o limite máximo permitido de 10 MB.")
        st.stop()
        
    try:
        if arquivo_carregado.name.endswith(".csv"):
            df_raw = pd.read_csv(arquivo_carregado)
        else:
            df_raw = pd.read_excel(arquivo_carregado)
            
        df_pedidos = validar_e_higienizar_dataframe(df_raw)
    except Exception as e:
        logger.exception("Falha na validação do arquivo do usuário:")
        msg = str(e) if isinstance(e, (KeyError, ValueError)) else "Falha ao processar o arquivo. Verifique o layout das colunas."
        st.error(f"⚠️ {msg}")
        st.stop()
else:
    caminho_padrao = "data/pedidos.csv"
    if os.path.exists(caminho_padrao):
        try:
            df_pedidos = validar_e_higienizar_dataframe(pd.read_csv(caminho_padrao))
            st.info("💡 Usando base modelo padrão (`data/pedidos.csv`). Você pode subir sua própria planilha pela barra lateral.")
        except Exception:
            logger.exception("Erro ao carregar base padrão:")
            st.error("Erro interno ao ler arquivo padrão de pedidos.")
            st.stop()
    else:
        st.warning("Envie uma planilha na barra lateral para iniciar a roteirização.")
        st.stop()

# ==========================================
# EXECUÇÃO DO PIPELINE
# ==========================================
df_records = tuple(df_pedidos.to_dict("records"))

with st.spinner("Processando roteirização e calculando custos reais..."):
    origem_coords, pedidos_proc, rotas, dados_calculados, resumo_rotas, km_geral, custo_geral = executar_pipeline_otimizacao(
        df_records, origem_rua, origem_num, origem_bairro, origem_cep, 
        modal_selecionado, float(preco_gasolina), float(custo_hora)
    )

df_resumo = pd.DataFrame(resumo_rotas)
custo_medio_pedido = custo_geral / len(pedidos_proc) if len(pedidos_proc) > 0 else 0.0

# ==========================================
# EXIBIÇÃO: CARDS EXECUTIVOS (KPIS)
# ==========================================
st.markdown("---")
col1, col2, col3, col4 = st.columns(4)
col1.metric("📦 Total de Pedidos", f"{len(pedidos_proc)}")
col2.metric("🚗 Veículos / Rotas", f"{len(rotas)}")
col3.metric("🛣️ Quilometragem Total", f"{km_geral:.1f} km")
col4.metric("💰 Custo Total Estimado", f"R$ {custo_geral:.2f}", f"R$ {custo_medio_pedido:.2f} / entrega")

# ==========================================
# EXIBIÇÃO: MAPA ESTÁVEL
# ==========================================
st.markdown("### 🗺️ Visualização Espacial & Roteamento")
mapa_folium = construir_mapa(
    origem_coords, rotas, modal_selecionado,
    preco_gasolina=float(preco_gasolina), custo_hora=float(custo_hora),
    dados_rotas_calculados=dados_calculados
)

st_folium(mapa_folium, width=None, height=520, use_container_width=True, returned_objects=[])

# Tabela e Download
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