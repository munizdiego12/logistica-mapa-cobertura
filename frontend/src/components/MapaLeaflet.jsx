import React from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, Circle } from 'react-leaflet';
import L from 'leaflet';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// Ícone vetorial estilizado para as paradas
const createStopIcon = (num, color) => {
  return L.divIcon({
    className: 'custom-stop-marker',
    html: `
      <div style="
        background-color: ${color};
        color: #ffffff;
        width: 26px;
        height: 26px;
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 11px;
        border: 2px solid #ffffff;
        box-shadow: 0 4px 12px rgba(0,0,0,0.45);
      ">
        ${num}
      </div>
    `,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    popupAnchor: [0, -13]
  });
};

// Ícone vetorial do Centro de Distribuição (Hub)
const hubIcon = L.divIcon({
  className: 'custom-hub-marker',
  html: `
    <div style="
      background-color: #0f172a;
      color: #38bdf8;
      width: 34px;
      height: 34px;
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 2px solid #38bdf8;
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.45);
    ">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
        <polyline points="9 22 9 12 15 12 15 22"></polyline>
      </svg>
    </div>
  `,
  iconSize: [34, 34],
  iconAnchor: [17, 17],
  popupAnchor: [0, -17]
});

export default function MapaLeaflet({ origem, rotas }) {
  if (!origem) return null;
  const center = [origem.lat, origem.lon];

  // Configuração das zonas de cobertura
  const zonasCobertura = [
    {
      raio: 3000,
      cor: '#10b981',
      titulo: 'Zona Primária (Expressa)',
      sla: 'Até 45 minutos',
      descricao: 'Raio de alta densidade urbana e menor custo por entrega.'
    },
    {
      raio: 7000,
      cor: '#3b82f6',
      titulo: 'Zona Secundária (Padrão)',
      sla: 'Até 2 horas',
      descricao: 'Área intermediária com fluxo moderado de tráfego.'
    },
    {
      raio: 12000,
      cor: '#f59e0b',
      titulo: 'Zona Estendida (Metropolitana)',
      sla: 'Mesmo dia (Same-Day)',
      descricao: 'Área periférica com impacto elevado em quilometragem e combustível.'
    }
  ];

  return (
    <div className="w-full h-[540px] rounded-xl overflow-hidden border border-slate-800 shadow-inner">
      <MapContainer center={center} zoom={13} style={{ height: '100%', width: '100%' }}>
        <TileLayer
          attribution='&copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
        />

        {/* 1. ZONAS CIRCULARES DE COBERTURA COM POPUPS INTERATIVOS */}
        {zonasCobertura.map((zona, idx) => (
          <Circle
            key={idx}
            center={center}
            radius={zona.raio}
            pathOptions={{
              color: zona.cor,
              fillColor: zona.cor,
              fillOpacity: 0.04,
              weight: 1.5,
              dashArray: '4, 4'
            }}
          >
            <Popup>
              <div className="text-slate-900 font-sans p-1 min-w-[210px]">
                <div className="flex items-center gap-1.5 pb-1 border-b border-slate-200">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: zona.cor }}></span>
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-800">
                    {zona.titulo}
                  </span>
                </div>
                <div className="mt-2 space-y-1 text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-slate-500">Raio Linear:</span>
                    <span className="font-semibold text-slate-700">{zona.raio / 1000} km do CD</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">SLA Estimado:</span>
                    <span className="font-semibold text-slate-700">{zona.sla}</span>
                  </div>
                  <p className="text-[10px] text-slate-500 pt-1 leading-tight">
                    {zona.descricao}
                  </p>
                </div>
              </div>
            </Popup>
          </Circle>
        ))}

        {/* 2. MARCADOR DO HUB CENTRAL */}
        <Marker position={center} icon={hubIcon}>
          <Popup>
            <div className="text-slate-900 font-sans p-1 min-w-[200px]">
              <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600 block">
                Centro de Distribuição (Origem)
              </span>
              <p className="font-bold text-xs text-slate-900 mt-1">{origem.rua}, {origem.numero}</p>
              <p className="text-[11px] text-slate-600">{origem.bairro} • CEP {origem.cep}</p>
            </div>
          </Popup>
        </Marker>

        {/* 3. TRAÇADO DA ROTA COM POPUP DE CUSTOS E ENTREGAS */}
        {rotas.map((rota) => (
          <React.Fragment key={rota.id}>
            <Polyline
              positions={rota.geometria}
              pathOptions={{
                color: rota.cor,
                weight: 5,
                opacity: 0.9,
                lineCap: 'round',
                lineJoin: 'round'
              }}
            >
              <Popup>
                <div className="text-slate-900 font-sans p-1.5 min-w-[220px]">
                  <div className="flex items-center justify-between pb-1.5 border-b border-slate-200">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: rota.cor }}></span>
                      <span className="font-bold text-xs uppercase tracking-wider text-slate-900">
                        Rota #{rota.id}
                      </span>
                    </div>
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                      {rota.qtd_pedidos} pedidos
                    </span>
                  </div>

                  <div className="mt-2.5 space-y-1.5 text-xs">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500 text-[11px]">Custo Total:</span>
                      <span className="font-bold text-emerald-600 font-mono">
                        R$ {rota.custo_total.toFixed(2)}
                      </span>
                    </div>

                    <div className="flex justify-between items-center">
                      <span className="text-slate-500 text-[11px]">Média por Pedido:</span>
                      <span className="font-semibold text-slate-800 font-mono">
                        R$ {rota.custo_por_pedido.toFixed(2)}
                      </span>
                    </div>

                    <div className="flex justify-between items-center pt-1 border-t border-slate-100 text-[11px] text-slate-500">
                      <span>{rota.km_total} km rodados</span>
                      <span>{rota.tempo_formatado}</span>
                    </div>
                  </div>
                </div>
              </Popup>
            </Polyline>

            {/* MARCADORES NUMERADOS DE CADA PARADA */}
            {rota.pedidos.map((p, pIdx) => (
              <Marker
                key={p["ID Pedido"] || pIdx}
                position={[p.lat, p.lon]}
                icon={createStopIcon(pIdx + 1, rota.cor)}
              >
                <Popup>
                  <div className="text-slate-900 font-sans p-1 min-w-[200px]">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-bold tracking-wider uppercase block" style={{ color: rota.cor }}>
                        Parada {pIdx + 1} • Rota #{rota.id}
                      </span>
                      <span className="text-[10px] font-mono text-slate-400">
                        {p["ID Pedido"]}
                      </span>
                    </div>
                    <p className="font-bold text-xs text-slate-900 mt-1">{p.Cliente}</p>
                    <p className="text-[11px] text-slate-600 leading-tight">{p.Logradouro}, {p.Numero}</p>
                    <p className="text-[10px] text-slate-500">{p.Bairro} • CEP {p.CEP}</p>
                    <div className="mt-2 pt-1 border-t border-slate-200 flex justify-between text-[11px] text-slate-600 font-medium">
                      <span>Volume:</span>
                      <span className="text-slate-800 font-bold">{p.Volume} {p.Volume > 1 ? 'pedidos' : 'pedido'}</span>
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))}
          </React.Fragment>
        ))}
      </MapContainer>
    </div>
  );
}