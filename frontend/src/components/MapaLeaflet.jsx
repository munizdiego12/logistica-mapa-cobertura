import React, { useEffect } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, Circle, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

const createStopIcon = (num, color) => {
  return L.divIcon({
    className: 'custom-stop-marker',
    html: `
      <div style="
        background-color: ${color || '#3b82f6'};
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
        font-family: sans-serif;
      ">
        ${num}
      </div>
    `,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    popupAnchor: [0, -13]
  });
};

const hubIcon = L.divIcon({
  className: 'custom-hub-marker',
  html: `
    <div style="
      background-color: #0f172a;
      color: #38bdf8;
      width: 36px;
      height: 36px;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 2px solid #38bdf8;
      box-shadow: 0 0 16px rgba(56, 189, 248, 0.45);
    ">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
        <polyline points="9 22 9 12 15 12 15 22"></polyline>
      </svg>
    </div>
  `,
  iconSize: [36, 36],
  iconAnchor: [18, 18],
  popupAnchor: [0, -18]
});

function AjustarZoom({ center, pontos }) {
  const map = useMap();
  useEffect(() => {
    if (pontos && pontos.length > 1) {
      try {
        map.fitBounds(pontos, { padding: [45, 45], maxZoom: 14 });
      } catch (e) {
        if (center) map.setView(center, 13);
      }
    } else if (center) {
      map.setView(center, 13);
    }
  }, [center, pontos, map]);
  return null;
}

export default function MapaLeaflet({ origem, rotas, mostrarRaio30km = true }) {
  if (!origem || typeof origem.lat !== 'number' || typeof origem.lon !== 'number') {
    return (
      <div className="w-full h-[540px] rounded-xl flex items-center justify-center bg-slate-950/40 border border-slate-800 text-slate-400 text-xs">
        Aguardando coordenadas da Loja Central...
      </div>
    );
  }

  const center = [origem.lat, origem.lon];
  const rotasArray = Array.isArray(rotas) ? rotas : [];

  const todosPontos = [center];
  rotasArray.forEach(r => {
    const listaParadas = r.paradas || r.pedidos || [];
    listaParadas.forEach(p => {
      if (typeof p.lat === 'number' && typeof p.lon === 'number') {
        todosPontos.push([p.lat, p.lon]);
      }
    });
  });

  // Zonas de cobertura ordenadas da MAIOR para a MENOR (para permitir cliques em camadas inferiores)
  const zonasCobertura = [
    ...(mostrarRaio30km ? [{
      raio: 30000,
      cor: '#94a3b8',
      titulo: 'Limite de Cobertura de Frete / CEPs (0 a 30 km)',
      sla: 'Raio de Atendimento do Cliente',
      veiculoSugerido: 'Todos os Modais Atendidos',
      descricao: 'Perímetro máximo de cálculo de Haversine para cotação e faixas de CEP atendidas.'
    }] : []),
    {
      raio: 12000,
      cor: '#f59e0b',
      titulo: 'Zona Estendida (Metropolitana)',
      sla: 'Mesmo dia (Same-Day / D+0)',
      veiculoSugerido: 'VUC / Fiorino / Carro',
      descricao: 'Região periférica e anel metropolitano. Maior impacto em km rodados e combustível.'
    },
    {
      raio: 7000,
      cor: '#3b82f6',
      titulo: 'Zona Secundária (Padrão)',
      sla: 'Até 2 horas',
      veiculoSugerido: 'Carro de Passeio / Fiorino',
      descricao: 'Área intermediária com fluxo moderado de tráfego. Equilíbrio entre custo e velocidade.'
    },
    {
      raio: 3000,
      cor: '#10b981',
      titulo: 'Zona Primária (Expressa)',
      sla: 'Até 45 minutos',
      veiculoSugerido: 'Moto / Carro Leve',
      descricao: 'Raio central de alta densidade urbana, máxima agilidade e menor custo.'
    }
  ];

  return (
    <div className="w-full h-[540px] rounded-xl overflow-hidden border border-slate-800 shadow-inner relative z-0">
      <MapContainer center={center} zoom={12} style={{ height: '100%', width: '100%' }}>
        <TileLayer
          attribution='&copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
        />

        <AjustarZoom center={center} pontos={todosPontos} />

        {/* 1. Zonas Concêntricas (30km -> 12km -> 7km -> 3km) */}
        {zonasCobertura.map((zona, idx) => (
          <Circle
            key={idx}
            center={center}
            radius={zona.raio}
            pathOptions={{
              color: zona.cor,
              fillColor: zona.cor,
              fillOpacity: zona.raio === 30000 ? 0.02 : 0.05,
              weight: zona.raio === 30000 ? 1.5 : 2,
              dashArray: zona.raio === 30000 ? '8, 8' : '5, 5'
            }}
          >
            <Popup>
              <div className="text-slate-900 font-sans p-1.5 min-w-[230px]">
                <div className="flex items-center gap-2 pb-1.5 border-b border-slate-200">
                  <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: zona.cor }}></span>
                  <span className="text-xs font-extrabold uppercase tracking-wider text-slate-800">
                    {zona.titulo}
                  </span>
                </div>
                <div className="mt-2 space-y-1.5 text-[11px]">
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">Raio de Alcance:</span>
                    <span className="font-bold text-slate-800">{zona.raio / 1000} km do Hub</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">Classificação:</span>
                    <span className="font-semibold text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200">
                      {zona.sla}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">Modal:</span>
                    <span className="font-semibold text-slate-700">{zona.veiculoSugerido}</span>
                  </div>
                  <p className="text-[10px] text-slate-500 pt-1 border-t border-slate-100">
                    {zona.descricao}
                  </p>
                </div>
              </div>
            </Popup>
          </Circle>
        ))}

        {/* 2. Marcador Hub Central */}
        <Marker position={center} icon={hubIcon}>
          <Popup>
            <div className="text-slate-900 font-sans p-1 min-w-[200px]">
              <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600 block">
                Loja Central / Hub Zubale
              </span>
              <p className="font-bold text-xs text-slate-900 mt-1">{origem.rua}, {origem.numero}</p>
              <p className="text-[11px] text-slate-600">{origem.bairro} {origem.cep ? `• CEP ${origem.cep}` : ''}</p>
            </div>
          </Popup>
        </Marker>

        {/* 3. Traçados e Paradas */}
        {rotasArray.map((rota) => {
          const listaParadas = rota.paradas || rota.pedidos || [];
          const polylinePositions = (Array.isArray(rota.geometria) && rota.geometria.length > 0)
            ? rota.geometria
            : [center, ...listaParadas.map(p => [p.lat, p.lon]), center];

          return (
            <React.Fragment key={rota.id}>
              {polylinePositions.length > 1 && (
                <Polyline
                  positions={polylinePositions}
                  pathOptions={{
                    color: rota.cor || '#3b82f6',
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
                            {rota.motorista || `Rota #${rota.id}`}
                          </span>
                        </div>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-blue-100 text-blue-800">
                          {rota.modal}
                        </span>
                      </div>

                      <div className="mt-2.5 space-y-1.5 text-xs">
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500 text-[11px]">Custo Total:</span>
                          <span className="font-bold text-emerald-600 font-mono">
                            R$ {Number(rota.custo_total || 0).toFixed(2)}
                          </span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500 text-[11px]">Média por Pedido:</span>
                          <span className="font-semibold text-slate-800 font-mono">
                            R$ {Number(rota.custo_por_pedido || 0).toFixed(2)}
                          </span>
                        </div>
                        <div className="flex justify-between items-center pt-1 border-t border-slate-100 text-[11px] text-slate-500">
                          <span>{rota.km_total} km</span>
                          <span>{rota.tempo_formatado}</span>
                        </div>
                      </div>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* 4. Marcadores Numerados com Modal Recomendado */}
              {listaParadas.map((p, pIdx) => {
                if (typeof p.lat !== 'number' || typeof p.lon !== 'number') return null;
                const volume = p.Volume || p.volume || 1;
                const logradouro = p.Endereco || p.Logradouro || p.rua || 'Endereço';
                const numero = p.Numero || p.numero || 'S/N';
                const bairro = p.Bairro || p.bairro || '';
                const modalAlocado = p.modal_alocado || rota.modal || 'Carro de Passeio';

                return (
                  <Marker
                    key={p.id || pIdx}
                    position={[p.lat, p.lon]}
                    icon={createStopIcon(pIdx + 1, rota.cor)}
                  >
                    <Popup>
                      <div className="text-slate-900 font-sans p-1 min-w-[210px]">
                        <div className="flex items-center justify-between pb-1 border-b border-slate-200">
                          <span className="text-[10px] font-bold tracking-wider uppercase" style={{ color: rota.cor }}>
                            Parada {pIdx + 1} • {rota.motorista_base || `Rota ${rota.id}`}
                          </span>
                          <span className="text-[10px] font-mono text-slate-400">ID #{p.id}</span>
                        </div>

                        <div className="mt-1.5 mb-1 inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-[10px] font-bold text-slate-800">
                          <span>Modal:</span>
                          <span className="text-blue-600">{modalAlocado}</span>
                        </div>

                        <p className="font-semibold text-xs text-slate-900">{logradouro}, {numero}</p>
                        <p className="text-[11px] text-slate-500">{bairro} {p.CEP ? `• CEP ${p.CEP}` : ''}</p>
                        
                        <div className="mt-2 pt-1 border-t border-slate-200 flex justify-between text-[11px] text-slate-600 font-medium">
                          <span>Volume da Parada:</span>
                          <span className="text-slate-800 font-bold">{volume} {volume > 1 ? 'pedidos' : 'pedido'}</span>
                        </div>
                      </div>
                    </Popup>
                  </Marker>
                );
              })}
            </React.Fragment>
          );
        })}
      </MapContainer>
    </div>
  );
}