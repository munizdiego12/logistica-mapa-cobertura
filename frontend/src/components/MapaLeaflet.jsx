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

const isCoordValid = (lat, lon) => {
  return typeof lat === 'number' && !isNaN(lat) && typeof lon === 'number' && !isNaN(lon);
};

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
        font-weight: 800;
        font-size: 11px;
        border: 2px solid #ffffff;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        font-family: sans-serif;
        cursor: pointer;
      ">
        ${num}
      </div>
    `,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    popupAnchor: [0, -13]
  });
};

const cityPinIcon = L.divIcon({
  className: 'custom-city-pin',
  html: `
    <div style="
      background-color: #059669;
      color: #ffffff;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 8px;
      border: 1.5px solid #ffffff;
      box-shadow: 0 2px 5px rgba(0,0,0,0.3);
      opacity: 0.85;
    ">
      📍
    </div>
  `,
  iconSize: [18, 18],
  iconAnchor: [9, 9],
  popupAnchor: [0, -9]
});

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
    try {
      const pontosValidos = (pontos || []).filter(p => Array.isArray(p) && isCoordValid(p[0], p[1]));
      if (pontosValidos.length > 1) {
        map.fitBounds(pontosValidos, { padding: [50, 50], maxZoom: 15 });
      } else if (center && isCoordValid(center[0], center[1])) {
        map.setView(center, 12);
      }
    } catch (e) {
      if (center && isCoordValid(center[0], center[1])) {
        map.setView(center, 12);
      }
    }
  }, [center, pontos, map]);
  return null;
}

export default function MapaLeaflet({ origem, rotas, dadosCeps = null }) {
  const hubLat = origem ? Number(origem.lat) : NaN;
  const hubLon = origem ? Number(origem.lon) : NaN;

  if (!isCoordValid(hubLat, hubLon)) {
    return (
      <div className="w-full h-[540px] rounded-xl flex items-center justify-center bg-slate-950/40 border border-slate-800 text-slate-400 text-xs">
        Aguardando coordenadas da Loja Central...
      </div>
    );
  }

  const center = [hubLat, hubLon];
  const rotasArray = Array.isArray(rotas) ? rotas : [];
  const temRotasAtivas = rotasArray.length > 0;
  const cidadesCobertas = (dadosCeps && Array.isArray(dadosCeps.pontos_cobertos)) ? dadosCeps.pontos_cobertos : [];

  const todosPontos = [center];
  rotasArray.forEach(r => {
    (r.paradas || r.pedidos || []).forEach(p => {
      const pLat = Number(p.lat);
      const pLon = Number(p.lon);
      if (isCoordValid(pLat, pLon)) {
        todosPontos.push([pLat, pLon]);
      }
    });
  });

  // Só adiciona pontos de CEP ao enquadramento se não houver rota ativa
  if (!temRotasAtivas) {
    cidadesCobertas.forEach(c => {
      const cLat = Number(c.lat);
      const cLon = Number(c.lon);
      if (isCoordValid(cLat, cLon) && Number(c.distancia_km) > 0) {
        todosPontos.push([cLat, cLon]);
      }
    });
  }

  const zonasCobertura = [
    {
      raio: 30000,
      cor: '#94a3b8',
      titulo: 'Limite de Cobertura de Frete / CEPs (0 a 30 km)',
      sla: 'Raio de Atendimento do Cliente'
    },
    {
      raio: 12000,
      cor: '#f59e0b',
      titulo: 'Zona Estendida (Metropolitana)',
      sla: 'Mesmo dia (Same-Day / D+0)'
    },
    {
      raio: 7000,
      cor: '#3b82f6',
      titulo: 'Zona Secundária (Padrão)',
      sla: 'Até 2 horas'
    },
    {
      raio: 3000,
      cor: '#10b981',
      titulo: 'Zona Primária (Expressa)',
      sla: 'Até 45 minutos'
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

        {/* 1. Isolinhas Concêntricas de Raio */}
        {zonasCobertura.map((zona, idx) => (
          <Circle
            key={idx}
            center={center}
            radius={zona.raio}
            pathOptions={{
              color: zona.cor,
              fillColor: zona.cor,
              fillOpacity: zona.raio === 30000 ? 0.02 : 0.04,
              weight: zona.raio === 30000 ? 1.5 : 2,
              dashArray: zona.raio === 30000 ? '8, 8' : '5, 5'
            }}
          />
        ))}

        {/* 2. Marcador do Hub Central */}
        <Marker position={center} icon={hubIcon} zIndexOffset={1000}>
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

        {/* 3. Marcadores de Amostragem de CEPs (Apenas exibidos se NÃO houver rotas ativas) */}
        {!temRotasAtivas && cidadesCobertas.map((c, cIdx) => {
          const cLat = Number(c.lat);
          const cLon = Number(c.lon);
          if (Number(c.distancia_km) === 0 || !isCoordValid(cLat, cLon)) return null;

          return (
            <Marker
              key={`city-${cIdx}`}
              position={[cLat, cLon]}
              icon={cityPinIcon}
            >
              <Popup>
                <div className="text-slate-900 font-sans p-1 min-w-[200px]">
                  <div className="flex items-center justify-between pb-1 border-b border-slate-200">
                    <span className="text-xs font-bold text-emerald-700">{c.bairro || c.cidade}</span>
                    <span className="text-[10px] font-mono text-slate-500">{c.distancia_km} km</span>
                  </div>
                  <div className="mt-1 text-[11px] space-y-0.5">
                    <p className="text-slate-600">Faixa: <span className="font-mono font-semibold text-slate-800">{c.cep_inicial} a {c.cep_final}</span></p>
                    <p className="text-slate-600">SLA: <span className="font-semibold text-emerald-600">{c.dias_sla} dia(s)</span></p>
                  </div>
                </div>
              </Popup>
            </Marker>
          );
        })}

        {/* 4. Traçados Viários e Marcadores dos Pedidos Reais */}
        {rotasArray.map((rota) => {
          const listaParadas = rota.paradas || rota.pedidos || [];
          const polylinePositions = (Array.isArray(rota.geometria) && rota.geometria.length > 0)
            ? rota.geometria.filter(pt => Array.isArray(pt) && isCoordValid(Number(pt[0]), Number(pt[1])))
            : [center, ...listaParadas.map(p => [Number(p.lat), Number(p.lon)]).filter(pt => isCoordValid(pt[0], pt[1])), center];

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
                />
              )}

              {listaParadas.map((p, pIdx) => {
                const pLat = Number(p.lat);
                const pLon = Number(p.lon);
                if (!isCoordValid(pLat, pLon)) return null;

                const volume = p.Volume || p.volume || 1;
                const logradouro = p.Endereco || p.Logradouro || p.rua || 'Endereço';
                const numero = p.Numero || p.numero || 'S/N';
                const bairro = p.Bairro || p.bairro || '';
                const modalAlocado = p.modal_alocado || rota.modal || 'Carro de Passeio';

                return (
                  <Marker
                    key={p.id || pIdx}
                    position={[pLat, pLon]}
                    icon={createStopIcon(pIdx + 1, rota.cor)}
                    zIndexOffset={500 + pIdx}
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
                          <span>Volume:</span>
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