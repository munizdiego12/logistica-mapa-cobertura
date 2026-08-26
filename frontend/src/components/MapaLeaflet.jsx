import React, { useEffect } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, Circle, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Correção dos caminhos padrão dos ícones do Leaflet
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

// Validação segura de coordenadas geográficas
const isCoordValid = (lat, lon) => {
  return typeof lat === 'number' && !isNaN(lat) && typeof lon === 'number' && !isNaN(lon) && (lat !== 0 || lon !== 0);
};

// Ícone customizado para paradas de pedidos numeradas
const createStopIcon = (num, color) => {
  return L.divIcon({
    className: 'custom-stop-marker',
    html: `
      <div style="
        background-color: ${color || '#3b82f6'};
        color: #ffffff;
        width: 26px;
        height: 26px;
        border-radius: 7px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 11px;
        border: 2px solid #ffffff;
        box-shadow: 0 4px 10px rgba(0,0,0,0.5);
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

// Ícone para os pontos de amostragem de CEP do Haversine
const createCityPinIcon = () => {
  return L.divIcon({
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
        box-shadow: 0 2px 6px rgba(0,0,0,0.35);
        cursor: pointer;
      ">
        📍
      </div>
    `,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -9]
  });
};

// Ícone estilizado do Hub Central / Loja de Origem
const hubIcon = L.divIcon({
  className: 'custom-hub-marker',
  html: `
    <div style="
      background-color: #0f172a;
      color: #38bdf8;
      width: 38px;
      height: 38px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      border: 2.5px solid #38bdf8;
      box-shadow: 0 0 20px rgba(56, 189, 248, 0.6);
      cursor: pointer;
    ">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
        <polyline points="9 22 9 12 15 12 15 22"></polyline>
      </svg>
    </div>
  `,
  iconSize: [38, 38],
  iconAnchor: [19, 19],
  popupAnchor: [0, -19]
});

// Componente para reenquadrar o zoom da tela
function AjustarZoom({ center, pontos }) {
  const map = useMap();
  useEffect(() => {
    try {
      const pontosValidos = (pontos || []).filter(p => Array.isArray(p) && isCoordValid(p[0], p[1]));
      if (pontosValidos.length > 1) {
        map.fitBounds(pontosValidos, { padding: [55, 55], maxZoom: 15 });
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

  // 1. Processamento de todas as paradas com deslocamento anti-sobreposição
  const coordsContador = {};
  const todasParadasProcessadas = [];

  rotasArray.forEach((rota) => {
    const lista = rota.paradas || rota.pedidos || [];
    lista.forEach((p, idx) => {
      let lat = Number(p.lat);
      let lon = Number(p.lon);
      if (!isCoordValid(lat, lon)) return;

      const chaveCoord = `${lat.toFixed(5)},${lon.toFixed(5)}`;
      coordsContador[chaveCoord] = (coordsContador[chaveCoord] || 0) + 1;
      const repeticoes = coordsContador[chaveCoord];

      // Se mais de um pedido tiver a mesma coordenada, afasta em ESPIRAL usando o ângulo
      // áureo (~137.5°). Isso nunca repete a mesma posição, não importa quantos pedidos
      // caiam no mesmo ponto (o método antigo, de 8 posições fixas em círculo, colidia
      // consigo mesmo a partir do 9º pedido repetido).
      if (repeticoes > 1) {
        const ANGULO_AUREO = 2.399963; // radianos
        const angulo = repeticoes * ANGULO_AUREO;
        const raio = 0.00012 * Math.sqrt(repeticoes); // cresce a cada repetição (~15m, ~20m, ~25m...)
        lat = lat + (raio * Math.cos(angulo));
        lon = lon + (raio * Math.sin(angulo));
      }

      todasParadasProcessadas.push({
        ...p,
        latAjustada: lat,
        lonAjustada: lon,
        ordemNumero: idx + 1,
        rotaId: rota.id,
        rotaCor: rota.cor || '#3b82f6',
        rotaMotorista: rota.motorista_base || rota.motorista || `Rota ${rota.id}`,
        rotaModal: rota.modal || 'Veículo'
      });
    });
  });

  // Lista de pontos para enquadramento do mapa
  const todosPontosZoom = [center, ...todasParadasProcessadas.map(p => [p.latAjustada, p.lonAjustada])];
  if (!temRotasAtivas) {
    cidadesCobertas.forEach(c => {
      const cLat = Number(c.lat);
      const cLon = Number(c.lon);
      if (isCoordValid(cLat, cLon) && Number(c.distancia_km) > 0) {
        todosPontosZoom.push([cLat, cLon]);
      }
    });
  }

  // Zonas concêntricas de raio completas
  const zonasCobertura = [
    {
      raio: 30000,
      cor: '#94a3b8',
      titulo: 'Limite de Cobertura de Frete / CEPs (0 a 30 km)',
      sla: 'Raio Operacional Máximo',
      veiculoSugerido: 'Todos os Modais Atendidos',
      descricao: 'Perímetro máximo de cálculo de Haversine para cotação e faixas de CEP atendidas.'
    },
    {
      raio: 12000,
      cor: '#f59e0b',
      titulo: 'Zona Estendida (Metropolitana)',
      sla: 'Mesmo dia (Same-Day / D+0)',
      veiculoSugerido: 'VUC / Fiorino / Carro',
      descricao: 'Região intermediária com maior impacto em km rodados e combustível.'
    },
    {
      raio: 7000,
      cor: '#3b82f6',
      titulo: 'Zona Secundária (Padrão)',
      sla: 'Até 2 horas',
      veiculoSugerido: 'Carro de Passeio / Fiorino',
      descricao: 'Área intermediária com fluxo moderado de tráfego.'
    },
    {
      raio: 3000,
      cor: '#10b981',
      titulo: 'Zona Primária (Expressa)',
      sla: 'Até 45 minutos',
      veiculoSugerido: 'Moto / Carro Leve',
      descricao: 'Raio central de alta densidade urbana e máxima agilidade.'
    }
  ];

  return (
    <div className="w-full h-[540px] rounded-xl overflow-hidden border border-slate-800 shadow-inner relative z-0">
      <MapContainer center={center} zoom={12} style={{ height: '100%', width: '100%' }}>
        <TileLayer
          attribution='&copy; <a href="https://carto.com/">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
        />

        <AjustarZoom center={center} pontos={todosPontosZoom} />

        {/* 1. Isolinhas Concêntricas de Raio com Popups Completos */}
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
              <div className="text-slate-900 font-sans p-1.5 min-w-[240px]">
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
                    <span className="text-slate-500">Classificação SLA:</span>
                    <span className="font-semibold text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200">
                      {zona.sla}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-500">Modal Recomendado:</span>
                    <span className="font-medium text-slate-700">{zona.veiculoSugerido}</span>
                  </div>
                  <p className="text-[10px] text-slate-500 pt-1 border-t border-slate-100 italic">
                    {zona.descricao}
                  </p>
                </div>
              </div>
            </Popup>
          </Circle>
        ))}

        {/* 2. Marcador da Loja Central / Hub com Popup Completo */}
        <Marker position={center} icon={hubIcon} zIndexOffset={1000}>
          <Popup>
            <div className="text-slate-900 font-sans p-1 min-w-[210px]">
              <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600 block">
                Loja Central / Hub Operacional
              </span>
              <p className="font-bold text-xs text-slate-900 mt-1">{origem.rua}, {origem.numero}</p>
              <p className="text-[11px] text-slate-600">{origem.bairro} {origem.cep ? `• CEP ${origem.cep}` : ''}</p>
              <div className="mt-2 pt-1 border-t border-slate-200 text-[10px] text-slate-500 font-mono">
                Centro geodésico Haversine (0 km)
              </div>
            </div>
          </Popup>
        </Marker>

        {/* 3. Marcadores de Amostragem de CEP (Exibidos na consulta de raio) */}
        {!temRotasAtivas && cidadesCobertas.map((c, cIdx) => {
          const cLat = Number(c.lat);
          const cLon = Number(c.lon);
          if (Number(c.distancia_km) === 0 || !isCoordValid(cLat, cLon)) return null;

          return (
            <Marker
              key={`city-${cIdx}`}
              position={[cLat, cLon]}
              icon={createCityPinIcon()}
              zIndexOffset={50}
            >
              <Popup>
                <div className="text-slate-900 font-sans p-1 min-w-[210px]">
                  <div className="flex items-center justify-between pb-1 border-b border-slate-200">
                    <span className="text-xs font-bold text-emerald-700">{c.bairro || c.cidade}</span>
                    <span className="text-[10px] font-mono text-slate-500">{c.distancia_km} km</span>
                  </div>
                  <div className="mt-1.5 space-y-1 text-[11px]">
                    <div className="flex justify-between">
                      <span className="text-slate-500">Faixa de CEP:</span>
                      <span className="font-mono font-semibold text-slate-800">{c.cep_inicial} a {c.cep_final}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">Prazo de Entrega:</span>
                      <span className="font-bold text-emerald-600">{c.dias_sla} dia(s)</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-slate-500">IBGE:</span>
                      <span className="font-mono text-slate-700">{c.ibge}</span>
                    </div>
                  </div>
                </div>
              </Popup>
            </Marker>
          );
        })}

        {/* 4. Traçados Viários das Rotas OSRM (clicável: mostra resumo da rota) */}
        {rotasArray.map((rota) => {
          const listaParadas = rota.paradas || rota.pedidos || [];
          const polylinePositions = (Array.isArray(rota.geometria) && rota.geometria.length > 0)
            ? rota.geometria.filter(pt => Array.isArray(pt) && isCoordValid(Number(pt[0]), Number(pt[1])))
            : [center, ...listaParadas.map(p => [Number(p.lat), Number(p.lon)]).filter(pt => isCoordValid(pt[0], pt[1])), center];

          return (
            <Polyline
              key={`poly-${rota.id}`}
              positions={polylinePositions}
              pathOptions={{
                color: rota.cor || '#3b82f6',
                weight: 5,
                opacity: 0.9,
                lineCap: 'round',
                lineJoin: 'round'
              }}
              eventHandlers={{
                mouseover: (e) => e.target.setStyle({ weight: 8, opacity: 1 }),
                mouseout: (e) => e.target.setStyle({ weight: 5, opacity: 0.9 }),
                click: (e) => e.target.bringToFront(),
              }}
            >
              <Popup>
                <div className="text-slate-900 font-sans p-1.5 min-w-[230px]">
                  <div className="flex items-center gap-2 pb-1.5 border-b border-slate-200">
                    <span className="w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: rota.cor }}></span>
                    <span className="text-xs font-extrabold uppercase tracking-wider text-slate-800">
                      {rota.motorista}
                    </span>
                  </div>
                  <div className="mt-2 space-y-1.5 text-[11px]">
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">Veículo:</span>
                      <span className="font-semibold text-slate-800">{rota.modal}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">Total de Pedidos:</span>
                      <span className="font-bold text-slate-800">{rota.qtd_pedidos}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">Distância da Rota:</span>
                      <span className="font-semibold text-slate-800">{rota.km_total} km</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">Tempo Estimado:</span>
                      <span className="font-semibold text-slate-800">{rota.tempo_formatado}</span>
                    </div>
                    <div className="flex justify-between items-center pt-1 border-t border-slate-100">
                      <span className="text-slate-500">Custo Total da Rota:</span>
                      <span className="font-bold text-emerald-600">R$ {Number(rota.custo_total).toFixed(2)}</span>
                    </div>
                    <div className="flex justify-between items-center">
                      <span className="text-slate-500">Custo Médio / Pedido:</span>
                      <span className="font-semibold text-slate-700">R$ {Number(rota.custo_por_pedido).toFixed(2)}</span>
                    </div>
                  </div>
                  {rota.link_maps && (
                    <a
                      href={rota.link_maps}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 pt-2 border-t border-slate-100 flex items-center justify-center gap-1 text-[11px] font-semibold text-blue-600 hover:text-blue-800"
                    >
                      Abrir no Google Maps →
                    </a>
                  )}
                </div>
              </Popup>
            </Polyline>
          );
        })}

        {/* 5. Todas as Paradas de Entrega Reais Numeradas (1, 2, 3... N) */}
        {todasParadasProcessadas.map((p, pIdx) => {
          const volume = p.Volume || p.volume || 1;
          const logradouro = p.Endereco || p.Logradouro || p.rua || 'Endereço';
          const numero = p.Numero || p.numero || 'S/N';
          const bairro = p.Bairro || p.bairro || '';

          return (
            <Marker
              key={`stop-${p.id || pIdx}`}
              position={[p.latAjustada, p.lonAjustada]}
              icon={createStopIcon(p.ordemNumero, p.rotaCor)}
              zIndexOffset={300 + pIdx}
            >
              <Popup>
                <div className="text-slate-900 font-sans p-1 min-w-[220px]">
                  <div className="flex items-center justify-between pb-1 border-b border-slate-200">
                    <span className="text-[10px] font-bold tracking-wider uppercase" style={{ color: p.rotaCor }}>
                      Parada {p.ordemNumero} • {p.rotaMotorista}
                    </span>
                    <span className="text-[10px] font-mono text-slate-400">ID #{p.id}</span>
                  </div>
                  <div className="mt-1.5 mb-1 inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-[10px] font-bold text-slate-800">
                    <span>Modal:</span>
                    <span className="text-blue-600">{p.rotaModal}</span>
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
      </MapContainer>
    </div>
  );
}