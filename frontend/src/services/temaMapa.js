// Tema do mapa (Escuro / Claro): escolha lembrada no navegador, paletas e ajuste de cores para ter bom contraste.
// Sem dependências, para ser testável com o `node --test` do Node.
//
// Mapa-base: mesmo provedor de antes (Esri, sem chave de API). O tom azul vem de um filtro de CSS aplicado só nos
// blocos do mapa (ver .mapa-escuro e .mapa-claro em index.css); os cálculos de contraste abaixo usam as cores
// aproximadas que o mapa fica depois do filtro (medidas no mapa renderizado).
//
// Tema Claro: a base "cinza claro" da Esri desenha as ruas em BRANCO sobre cinza muito claro (255 sobre 235), e nenhum
// filtro de CSS consegue tirar daí ruas azuis com contraste. Por isso o tema Claro usa a base "cinza escuro" da mesma
// Esri (nela as ruas são mais CLARAS que o terreno, ao contrário) e o filtro a inverte: terreno branco, ruas azuis.

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
    // Mesmas camadas da Esri do tema Escuro; o filtro do tema Claro (index.css) inverte e recolore.
    base: `${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`,
    rotulos: `${ESRI}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`,
  },
};

// Cor aproximada do mapa depois do filtro azul (terreno típico de cada base).
export const FUNDO_APROXIMADO = { escuro: '#13275e', claro: '#fff5ff' };

// Cores das ruas do tema Claro depois do filtro (medidas no mapa renderizado de São Paulo): ruas pequenas (azul-celeste
// bem claro, fios finos), médias (azul) e grandes (azul-marinho).
// Servem para conferir que rotas, círculos de raio e hub não se confundem com o azul das ruas.
export const RUAS_APROXIMADAS = { escuro: [], claro: ['#5df3ff', '#2769ed', '#153375'] };

// Evento disparado quando o operador troca o tema do mapa, para o resto da tela acompanhar (ex.: bolinha da rota).
export const EVENTO_TEMA = 'tema-mapa';

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
    // Raios: tons escuros e sem azul (o azul é das ruas), que se destacam no mapa branco.
    zonas: { 30000: '#57534e', 20000: '#86198f', 12000: '#b45309', 7000: '#be185d', 3000: '#047857' },
    zonaPreenchimento: 0.025, // baixo: os 5 círculos se somam e tingiriam de rosa as ruas azuis
    rotaContorno: '#ffffff', rotaContornoOpacidade: 0.9,
    paradaBorda: '#0f172a', paradaSombra: 'rgba(15,23,42,0.4)',
    hub: { fundo: '#7f1d1d', icone: '#ffffff', borda: '#ffffff', brilho: 'rgba(127,29,29,0.55)' },
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

/** Distância perceptiva entre duas cores (CIE76 em Lab): perto de 0 = parecidas; acima de ~40 = bem diferentes. */
export function distanciaDeCor(corA, corB) {
  const lab = (hex) => {
    const [r, g, b] = paraRgb(hex).map((v) => {
      const c = v / 255;
      return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    const x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047;
    const y = r * 0.2126 + g * 0.7152 + b * 0.0722;
    const z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883;
    const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
  };
  const [l1, a1, b1] = lab(corA);
  const [l2, a2, b2] = lab(corB);
  return Math.hypot(l1 - l2, a1 - a2, b1 - b2);
}

// No tema Claro as ruas são azuis: rotas na família do azul (azul, anil, ciano, violeta) trocam de cor para não se
// confundir com elas. Escolhidas por busca (maior distância entre todas as rotas e as ruas).
// Distância mínima de cor para as ruas médias e grandes (as que carregam o mapa) e para as pequenas (fios claros).
export const DISTANCIA_MINIMA_RUAS = 40;
export const DISTANCIA_MINIMA_RUAS_PEQUENAS = 25;
export const SUBSTITUTOS_CLARO = { '#3b82f6': '#9a3412', '#8b5cf6': '#be123c', '#6366f1': '#a21caf' };
const SUBSTITUTO_GENERICO_CLARO = '#9a3412';

/** Verdadeiro se a cor se confunde com alguma rua do tema Claro (ruas pequenas, médias e grandes, nesta ordem). */
export function pareceComAsRuas(cor, ruas = RUAS_APROXIMADAS.claro) {
  const [pequena, ...principais] = ruas;
  return distanciaDeCor(cor, pequena) < DISTANCIA_MINIMA_RUAS_PEQUENAS
    || principais.some((rua) => distanciaDeCor(cor, rua) < DISTANCIA_MINIMA_RUAS);
}

const misturar = (hex, alvo, parte) => {
  const a = paraRgb(hex);
  const b = paraRgb(alvo);
  return paraHex(a.map((v, i) => v + (b[i] - v) * parte));
};

/** Escurece (tema claro) ou clareia (escuro) a cor aos poucos até ter o contraste mínimo com o mapa; sem mexer se já tem. */
function comContraste(cor, tema, minimo) {
  const fundo = FUNDO_APROXIMADO[tema] ?? FUNDO_APROXIMADO[TEMA_PADRAO];
  const alvo = tema === 'claro' ? '#000000' : '#ffffff';
  let atual = cor;
  for (let i = 0; i < 20 && contraste(atual, fundo) < minimo; i += 1) atual = misturar(atual, alvo, 0.1);
  return atual;
}

/**
 * Cor da rota ajustada ao tema. No mapa claro: escurece as vivas (amarelo, verde-limão...) até ficarem visíveis no
 * fundo branco e, se a cor (já escurecida) ainda se confunde com o azul das ruas, troca por uma substituta. No mapa
 * escuro: clareia as muito escuras. Só mexe quando precisa.
 */
export function corDaRotaNoTema(cor, tema, minimo = 3) {
  const original = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(String(cor)) ? String(cor) : '#3b82f6';
  let atual = comContraste(original, tema, minimo);
  if (tema === 'claro' && pareceComAsRuas(atual)) {
    atual = comContraste(SUBSTITUTOS_CLARO[original.toLowerCase()] ?? SUBSTITUTO_GENERICO_CLARO, tema, minimo);
  }
  return atual;
}
