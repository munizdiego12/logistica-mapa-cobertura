// Tema do mapa (Escuro / Claro): escolha lembrada no navegador, paletas e ajuste de cores para ter bom contraste.
// Sem dependências, para ser testável com o `node --test` do Node.
//
// Mapa-base: mesmo provedor de antes (Esri, sem chave de API), nas bases em cinza escuro e cinza claro. O tom azul
// vem de um filtro de CSS aplicado só nos blocos do mapa (ver .mapa-escuro e .mapa-claro em index.css); os
// cálculos de contraste abaixo usam a cor aproximada que o mapa fica depois do filtro.

export const CHAVE_TEMA = 'mapa-tema';
export const TEMAS = ['escuro', 'claro'];
export const TEMA_PADRAO = 'escuro';

export const ROTULO_TEMA = { escuro: 'Escuro', claro: 'Claro' };

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas';
export const ATRIBUICAO_ESRI = 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors, and the GIS user community';

// Bases em cinza (sem rótulos) e as camadas de rótulos de cada uma.
export const CAMADAS = {
  escuro: {
    base: `${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    rotulos: `${ESRI}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
  },
  claro: {
    base: `${ESRI}/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    rotulos: `${ESRI}/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
  },
};

// Cor aproximada do mapa depois do filtro azul (terreno típico de cada base).
export const FUNDO_APROXIMADO = { escuro: '#13275e', claro: '#e9f2ff' };

export const PALETAS = {
  escuro: {
    fundoDoContainer: '#0b1a33',
    // Raios (do maior para o menor): tons claros, que se destacam no azul-marinho.
    zonas: { 30000: '#cbd5e1', 20000: '#c084fc', 12000: '#fbbf24', 7000: '#60a5fa', 3000: '#34d399' },
    zonaPreenchimento: 0.07,
    rotaContorno: '#020617', rotaContornoOpacidade: 0.6,
    paradaBorda: '#ffffff', paradaSombra: 'rgba(0,0,0,0.6)',
    hub: { fundo: '#38bdf8', icone: '#0b1a33', borda: '#ffffff', brilho: 'rgba(56,189,248,0.65)' },
    pinCep: { fundo: '#10b981', borda: '#ffffff' },
  },
  claro: {
    fundoDoContainer: '#e9f2ff',
    // Raios: tons escuros, que se destacam no branco azulado.
    zonas: { 30000: '#475569', 20000: '#7e22ce', 12000: '#b45309', 7000: '#1d4ed8', 3000: '#047857' },
    zonaPreenchimento: 0.05,
    rotaContorno: '#ffffff', rotaContornoOpacidade: 0.9,
    paradaBorda: '#0f172a', paradaSombra: 'rgba(15,23,42,0.4)',
    hub: { fundo: '#0b2a5b', icone: '#ffffff', borda: '#ffffff', brilho: 'rgba(11,42,91,0.55)' },
    pinCep: { fundo: '#047857', borda: '#ffffff' },
  },
};

// ---------------------------------------------------------------- escolha lembrada no navegador
export function lerTema(armazenamento = globalThis.localStorage) {
  try {
    const salvo = armazenamento?.getItem(CHAVE_TEMA);
    return TEMAS.includes(salvo) ? salvo : TEMA_PADRAO;
  } catch {
    return TEMA_PADRAO;
  }
}

export function salvarTema(tema, armazenamento = globalThis.localStorage) {
  if (!TEMAS.includes(tema)) return false;
  try {
    armazenamento?.setItem(CHAVE_TEMA, tema);
    return true;
  } catch {
    return false; // navegador bloqueando o armazenamento: o tema vale só nesta visita
  }
}

// ---------------------------------------------------------------- cores e contraste
function paraRgb(hex) {
  const limpo = String(hex).replace('#', '');
  const completo = limpo.length === 3 ? limpo.split('').map((c) => c + c).join('') : limpo;
  const n = parseInt(completo, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function paraHex([r, g, b]) {
  return `#${[r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('')}`;
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

const misturar = (hex, alvo, parte) => {
  const a = paraRgb(hex);
  const b = paraRgb(alvo);
  return paraHex(a.map((v, i) => v + (b[i] - v) * parte));
};

/**
 * Cor da rota ajustada ao tema: no mapa claro escurece as cores vivas (amarelo, verde-limão, ciano...) até ficarem
 * visíveis no fundo branco; no escuro clareia as muito escuras. Só mexe quando o contraste com o mapa é baixo.
 */
export function corDaRotaNoTema(cor, tema, minimo = 3) {
  const fundo = FUNDO_APROXIMADO[tema] ?? FUNDO_APROXIMADO[TEMA_PADRAO];
  const alvo = tema === 'claro' ? '#000000' : '#ffffff';
  let atual = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(String(cor)) ? String(cor) : '#3b82f6';
  for (let i = 0; i < 20 && contraste(atual, fundo) < minimo; i += 1) atual = misturar(atual, alvo, 0.1);
  return atual;
}
