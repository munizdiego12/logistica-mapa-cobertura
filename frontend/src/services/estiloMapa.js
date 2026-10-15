// Estilo do mapa: um único tema, escuro (azul-marinho). Camadas, cores e contraste.
// Sem dependências, para ser testável com o `node --test` do Node.
//
// Mapa-base: Esri, sem chave de API, nas camadas em cinza escuro (base e rótulos). O tom azul-marinho vem de um filtro
// de CSS aplicado só nos blocos do mapa (ver .mapa-escuro em index.css); os cálculos de contraste abaixo usam a cor
// aproximada que o mapa fica depois do filtro.

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas';
export const ATRIBUICAO_ESRI = 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS user community';

// Base em cinza (sem rótulos) e a camada de rótulos.
export const CAMADAS = {
  base: `${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
  rotulos: `${ESRI}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
};

// Cor aproximada do mapa depois do filtro azul (terreno típico).
export const FUNDO_APROXIMADO = '#13275e';

export const ESTILO = {
  fundoDoContainer: '#0b1a33',
  // Raios (do maior para o menor): tons claros, que se destacam no azul-marinho.
  zonas: { 30000: '#cbd5e1', 20000: '#c084fc', 12000: '#fbbf24', 7000: '#60a5fa', 3000: '#34d399' },
  zonaPreenchimento: 0.07,
  rotaContorno: '#020617', rotaContornoOpacidade: 0.6,
  paradaBorda: '#ffffff', paradaSombra: 'rgba(0,0,0,0.6)',
  hub: { fundo: '#38bdf8', icone: '#0b1a33', borda: '#ffffff', brilho: 'rgba(56,189,248,0.65)' },
  // Lojas cadastradas (marcadores do mapa permanente) e a loja escolhida como hub (borda verde).
  loja: { fundo: '#cbd5e1', icone: '#0b1a33', borda: '#0b1a33', sombra: 'rgba(0,0,0,0.55)' },
  hubEscolhido: { borda: '#22c55e', brilho: 'rgba(34,197,94,0.7)' },
};

// ---------------------------------------------------------------- cores e contraste
function paraRgb(hex) {
  const limpo = String(hex).replace('#', '');
  const completo = limpo.length === 3 ? limpo.split('').map((c) => c + c).join('') : limpo;
  const n = parseInt(completo, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

export function luminancia(hex) {
  const [r, g, b] = paraRgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Razão de contraste (1 a 21) entre duas cores, como nas diretrizes de acessibilidade (WCAG). */
export function contraste(corA, corB) {
  const a = luminancia(corA);
  const b = luminancia(corB);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/** Texto claro ou escuro, o que tiver mais contraste sobre a cor de fundo (números das paradas). */
export function corDoTexto(fundo) {
  return contraste(fundo, '#ffffff') >= contraste(fundo, '#0f172a') ? '#ffffff' : '#0f172a';
}
