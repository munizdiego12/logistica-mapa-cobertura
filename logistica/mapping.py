import html
import folium
from typing import List, Tuple, Dict, Any, Optional
from logistica.costs import calcular_custo_operacional
from logistica.routing import obter_trajeto_asfalto_osrm

def gerar_link_google_maps(origem_coords: Tuple[float, float], rota: List[Dict[str, Any]]) -> str:
    base_url = "https://www.google.com/maps/dir/"
    coords = [f"{origem_coords[0]},{origem_coords[1]}"]
    for p in rota:
        coords.append(f"{p['lat']},{p['lon']}")
    coords.append(f"{origem_coords[0]},{origem_coords[1]}")
    return base_url + "/".join(coords)

def construir_mapa(
    origem_coords: Tuple[float, float], 
    rotas: List[List[Dict[str, Any]]], 
    nome_modal: str,
    preco_gasolina: Optional[float] = None,
    custo_hora: Optional[float] = None,
    dados_rotas_calculados: Optional[List[Dict[str, Any]]] = None
) -> folium.Map:
    mapa = folium.Map(location=origem_coords, zoom_start=13, tiles="CartoDB positron")
    
    css_fix = """
    <style>
        path:focus, svg:focus, .leaflet-interactive:focus {
            outline: none !important;
        }
    </style>
    """
    mapa.get_root().html.add_child(folium.Element(css_fix))
    
    # 1. Camada Macro (Zonas)
    camada_zonas = folium.FeatureGroup(name="Zonas de Cobertura (Macro)", show=False)
    zonas = [
        {"nome": "Zona 3 (Até 12 km)", "raio": 12000, "cor": "#E67E22"},
        {"nome": "Zona 2 (Até 7 km)",   "raio": 7000,  "cor": "#2980B9"},
        {"nome": "Zona 1 (Até 3 km)",   "raio": 3000,  "cor": "#27AE60"}
    ]
    for z in zonas:
        folium.Circle(
            location=origem_coords,
            radius=z["raio"],
            color=z["cor"],
            weight=1.5,
            fill=True,
            fill_color=z["cor"],
            fill_opacity=0.08,
            tooltip=z["nome"]
        ).add_to(camada_zonas)
    camada_zonas.add_to(mapa)
    
    # 2. Camada Micro (Rotas)
    camada_rotas = folium.FeatureGroup(name="Rotas Reais por Ruas (OSRM)", show=True)
    cores = ['#2980B9', '#E67E22', '#27AE60', '#8E44AD']
    
    for idx, rota in enumerate(rotas):
        cor = cores[idx % len(cores)]
        
        # Reutiliza geometria/métrica se já tiver sido pré-calculada no pipeline com cache
        if dados_rotas_calculados and idx < len(dados_rotas_calculados):
            geometria = dados_rotas_calculados[idx]["geometria"]
            met = dados_rotas_calculados[idx]["metricas"]
        else:
            pontos = [origem_coords] + [(p['lat'], p['lon']) for p in rota] + [origem_coords]
            geometria, km_real, tempo_transito_h = obter_trajeto_asfalto_osrm(pontos)
            met = calcular_custo_operacional(
                km_real, tempo_transito_h, len(rota), nome_modal, 
                preco_gasolina=preco_gasolina, custo_hora=custo_hora
            )
            
        link_maps = gerar_link_google_maps(origem_coords, rota)
        
        # Marcadores de Paradas (Sanitizados contra XSS com html.escape)
        for seq, p in enumerate(rota, 1):
            pt = (p['lat'], p['lon'])
            cliente = html.escape(str(p.get('Cliente', 'N/A')))
            logradouro = html.escape(str(p.get('Logradouro', '')))
            numero = html.escape(str(p.get('Numero', '')))
            bairro = html.escape(str(p.get('Bairro', '')))
            
            popup_ponto = f"""
            <div style="font-family: Arial; font-size: 13px; min-width: 180px;">
                <h4 style="margin: 0 0 6px 0; color: {cor};">Parada #{seq} (Rota {idx+1})</h4>
                <b>Cliente:</b> {cliente}<br>
                <b>Endereço:</b> {logradouro}, {numero}<br>
                <b>Bairro:</b> {bairro}
            </div>
            """
            folium.Marker(
                location=pt,
                icon=folium.DivIcon(
                    html=f"""
                    <div style="background-color: {cor}; color: white; border-radius: 50%; width: 24px; height: 24px; 
                                display: flex; align-items: center; justify-content: center; font-weight: bold; 
                                font-size: 11px; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.35);">
                        {seq}
                    </div>
                    """
                ),
                popup=folium.Popup(popup_ponto, max_width=280),
                tooltip=f"Parada {seq} - {cliente}"
            ).add_to(camada_rotas)
            
        # Linha da Rota e Popup Operacional
        popup_linha = f"""
        <div style="font-family: Arial; font-size: 13px; min-width: 220px; line-height: 1.5;">
            <div style="background-color: {cor}; color: white; padding: 6px; border-radius: 4px; font-weight: bold;">
                🚗 Rota #{idx + 1} - Detalhes
            </div>
            <div style="margin-top: 6px;">
                <b>Entregas:</b> {len(rota)}<br>
                <b>Distância:</b> {met['km_total']} km<br>
                <b>Tempo:</b> {met['tempo_formatado']}<br>
                <b>Custo Total:</b> R$ {met['custo_total']:.2f}<br>
                <b>Custo/Pedido:</b> <span style="color:#27ae60; font-weight: bold;">R$ {met['custo_por_pedido']:.2f}</span>
            </div>
            <div style="margin-top: 8px; text-align: center;">
                <a href="{link_maps}" target="_blank" style="background-color: {cor}; color: white; text-decoration: none; padding: 5px 10px; border-radius: 4px; font-size: 11px; font-weight: bold; display: inline-block;">
                    🗺️ Abrir no Google Maps
                </a>
            </div>
        </div>
        """
        folium.PolyLine(
            locations=geometria,
            color=cor,
            weight=5,
            opacity=0.85,
            popup=folium.Popup(popup_linha, max_width=300),
            tooltip=f"Rota {idx+1}: {met['km_total']} km | R$ {met['custo_por_pedido']}/pedido"
        ).add_to(camada_rotas)
        
    camada_rotas.add_to(mapa)
    
    # Origem
    folium.Marker(
        location=origem_coords,
        popup="<b>Origem: Loja / Centro de Distribuição</b>",
        tooltip="Ponto de Saída",
        icon=folium.Icon(color="black", icon="home", prefix="fa")
    ).add_to(mapa)
    
    folium.LayerControl(position='topright', collapsed=False).add_to(mapa)
    return mapa