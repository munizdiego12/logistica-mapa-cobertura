import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  CHAVE_TEMA, TEMAS, TEMA_PADRAO, CAMADAS, PALETAS, FUNDO_APROXIMADO, RUAS_APROXIMADAS, SUBSTITUTOS_CLARO, ATRIBUICAO_ESRI,
  lerTema, salvarTema, contraste, corDoTexto, corDaRotaNoTema, distanciaDeCor, pareceComAsRuas,
} from './temaMapa.js';

const CSS = readFileSync(new URL('../index.css', import.meta.url), 'utf8');
const RUAS = RUAS_APROXIMADAS.claro;

const armazenamento = (inicial = {}) => {
  const dados = { ...inicial };
  return { dados, getItem: (k) => (k in dados ? dados[k] : null), setItem: (k, v) => { dados[k] = String(v); } };
};

// As cores que o servidor usa nas rotas (backend/main.py, CORES_ROTAS).
const CORES_DAS_ROTAS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16', '#F97316', '#14B8A6', '#6366F1', '#D946EF'];

test('o tema padrão é o escuro e só existem Escuro e Claro', () => {
  assert.equal(TEMA_PADRAO, 'escuro');
  assert.deepEqual(TEMAS, ['escuro', 'claro']);
  assert.equal(lerTema(armazenamento()), 'escuro');
});

test('a escolha fica lembrada no navegador e valores estranhos voltam ao padrão', () => {
  const arm = armazenamento();
  assert.equal(salvarTema('claro', arm), true);
  assert.equal(arm.dados[CHAVE_TEMA], 'claro');
  assert.equal(lerTema(arm), 'claro');
  assert.equal(salvarTema('azul', arm), false);
  assert.equal(lerTema(armazenamento({ [CHAVE_TEMA]: 'qualquer coisa' })), 'escuro');
});

test('armazenamento bloqueado ou ausente não quebra o mapa', () => {
  const quebrado = { getItem: () => { throw new Error('bloqueado'); }, setItem: () => { throw new Error('bloqueado'); } };
  assert.equal(lerTema(quebrado), 'escuro');
  assert.equal(salvarTema('claro', quebrado), false);
  assert.equal(lerTema(null), 'escuro');
});

test('mesmo provedor (Esri), bases em cinza escuro e cinza claro, sem chave de API e com a atribuição', () => {
  for (const tema of TEMAS) {
    for (const url of Object.values(CAMADAS[tema])) {
      assert.match(url, /^https:\/\/server\.arcgisonline\.com\/ArcGIS\/rest\/services\/Canvas\//);
      assert.doesNotMatch(url, /key|token|apikey/i);
    }
  }
  assert.match(CAMADAS.escuro.base, /World_Dark_Gray_Base/);
  // O claro usa a base cinza escuro da Esri (ruas mais claras que o terreno) e o filtro a inverte: a base cinza claro
  // desenha ruas brancas sobre cinza claro e não dá para recolorir com contraste.
  assert.match(CAMADAS.claro.base, /World_Dark_Gray_Base/);
  assert.match(CAMADAS.claro.rotulos, /World_Dark_Gray_Reference/);
  assert.match(ATRIBUICAO_ESRI, /Esri/);
  assert.match(ATRIBUICAO_ESRI, /OpenStreetMap/);
});

test('os círculos de raio têm bom contraste (3:1 ou mais) com o mapa de cada tema', () => {
  for (const tema of TEMAS) {
    for (const [raio, cor] of Object.entries(PALETAS[tema].zonas)) {
      assert.ok(contraste(cor, FUNDO_APROXIMADO[tema]) >= 3, `${tema} ${raio}: ${cor} = ${contraste(cor, FUNDO_APROXIMADO[tema]).toFixed(2)}`);
    }
  }
});

test('as rotas, depois do ajuste, têm bom contraste com o mapa em cada tema', () => {
  for (const tema of TEMAS) {
    for (const cor of CORES_DAS_ROTAS) {
      const ajustada = corDaRotaNoTema(cor, tema);
      assert.ok(contraste(ajustada, FUNDO_APROXIMADO[tema]) >= 3, `${tema} ${cor} -> ${ajustada}`);
    }
  }
});

test('só mexe na cor da rota quando precisa: cores que já contrastam ficam como estão', () => {
  assert.equal(corDaRotaNoTema('#F59E0B', 'escuro'), '#F59E0B');
  assert.equal(corDaRotaNoTema('#047857', 'claro'), '#047857');
  assert.notEqual(corDaRotaNoTema('#F59E0B', 'claro'), '#F59E0B'); // amarelo no fundo claro precisa escurecer
  assert.equal(corDaRotaNoTema('cor inválida', 'escuro').startsWith('#'), true);
});

test('o número da parada tem texto legível sobre a cor da rota, em qualquer tema', () => {
  for (const tema of TEMAS) {
    for (const cor of CORES_DAS_ROTAS) {
      const fundo = corDaRotaNoTema(cor, tema);
      assert.ok(contraste(fundo, corDoTexto(fundo)) >= 3.5, `${tema} ${fundo}`);
    }
  }
  assert.equal(corDoTexto('#fbbf24'), '#0f172a');
  assert.equal(corDoTexto('#1d4ed8'), '#ffffff');
});

test('o contorno das rotas, a borda das paradas e o hub se destacam do mapa', () => {
  for (const tema of TEMAS) {
    const p = PALETAS[tema];
    const fundo = FUNDO_APROXIMADO[tema];
    assert.ok(contraste(p.paradaBorda, fundo) >= 7, `borda ${tema}`);
    assert.ok(contraste(p.hub.fundo, fundo) >= 3, `hub ${tema}`);
    assert.ok(contraste(p.hub.icone, p.hub.fundo) >= 4.5, `ícone do hub ${tema}`);
    assert.ok(contraste(p.pinCep.fundo, fundo) >= 2.2, `pin de CEP ${tema}`);
  }
  assert.ok(contraste(PALETAS.claro.rotaContorno, FUNDO_APROXIMADO.claro) >= 1); // contorno branco só separa a linha das ruas
});

// ---------------------------------------------------------------- tema Claro: ruas azuis
test('no tema Claro as ruas têm contraste com o terreno branco: médias e grandes bem fortes, pequenas só como fios claros', () => {
  const [pequena, media, grande] = RUAS;
  // As ruas pequenas são fios de 1 px em azul-celeste claro de propósito (hierarquia); as médias e grandes é que carregam o mapa.
  assert.ok(contraste(pequena, FUNDO_APROXIMADO.claro) >= 1.2, `pequena ${contraste(pequena, FUNDO_APROXIMADO.claro).toFixed(2)}`);
  assert.ok(contraste(media, FUNDO_APROXIMADO.claro) >= 3, `média ${contraste(media, FUNDO_APROXIMADO.claro).toFixed(2)}`);
  assert.ok(contraste(grande, FUNDO_APROXIMADO.claro) >= 7, `grande ${contraste(grande, FUNDO_APROXIMADO.claro).toFixed(2)}`);
});

test('as ruas do tema Claro são azuis (azul bem acima do vermelho) e o terreno é branco', () => {
  for (const rua of RUAS) {
    const r = parseInt(rua.slice(1, 3), 16);
    const b = parseInt(rua.slice(5, 7), 16);
    assert.ok(b - r >= 90, `${rua}: azul ${b} vs vermelho ${r}`);
  }
  const fundo = FUNDO_APROXIMADO.claro;
  assert.ok([1, 3, 5].every((i) => parseInt(fundo.slice(i, i + 2), 16) >= 240), `terreno ${fundo}`);
});

test('no tema Claro nenhuma rota fica parecida com o azul das ruas (distância de cor 40 das médias e grandes, 25 das pequenas)', () => {
  const [pequena, media, grande] = RUAS;
  for (const cor of CORES_DAS_ROTAS) {
    const ajustada = corDaRotaNoTema(cor, 'claro');
    assert.ok(distanciaDeCor(ajustada, media) >= 40, `${cor} -> ${ajustada} vs rua média: ${distanciaDeCor(ajustada, media).toFixed(1)}`);
    assert.ok(distanciaDeCor(ajustada, grande) >= 40, `${cor} -> ${ajustada} vs rua grande: ${distanciaDeCor(ajustada, grande).toFixed(1)}`);
    assert.ok(distanciaDeCor(ajustada, pequena) >= 25, `${cor} -> ${ajustada} vs rua pequena: ${distanciaDeCor(ajustada, pequena).toFixed(1)}`);
    assert.equal(pareceComAsRuas(ajustada), false, ajustada);
  }
  // as cores originais da família do azul eram parecidas com as ruas (por isso trocam)
  for (const original of Object.keys(SUBSTITUTOS_CLARO)) assert.equal(pareceComAsRuas(original), true, original);
});

test('as rotas continuam distintas entre si no tema Claro (nenhum par de cores quase igual)', () => {
  const cores = CORES_DAS_ROTAS.map((c) => corDaRotaNoTema(c, 'claro'));
  assert.equal(new Set(cores).size, cores.length);
  for (let i = 0; i < cores.length; i += 1) {
    for (let j = i + 1; j < cores.length; j += 1) {
      assert.ok(distanciaDeCor(cores[i], cores[j]) >= 18, `${cores[i]} e ${cores[j]}: ${distanciaDeCor(cores[i], cores[j]).toFixed(1)}`);
    }
  }
});

test('as rotas azuis trocam de cor no Claro e ficam como estavam no Escuro', () => {
  for (const [original, trocada] of Object.entries(SUBSTITUTOS_CLARO)) {
    assert.equal(corDaRotaNoTema(original, 'claro'), trocada);
    assert.notEqual(corDaRotaNoTema(original, 'escuro'), trocada);
    assert.ok(contraste(trocada, FUNDO_APROXIMADO.claro) >= 3, trocada);
  }
  assert.equal(corDaRotaNoTema('#3B82F6', 'escuro'), '#3B82F6'); // tema Escuro não muda
});

test('círculos de raio e hub do tema Claro não se confundem com as ruas azuis', () => {
  for (const [raio, cor] of Object.entries(PALETAS.claro.zonas)) {
    assert.equal(pareceComAsRuas(cor), false, `raio ${raio} ${cor}`);
  }
  assert.equal(pareceComAsRuas(PALETAS.claro.hub.fundo), false, 'hub');
});

test('distância de cor: igual dá 0, preto e branco dão a maior', () => {
  assert.equal(distanciaDeCor('#3b82f6', '#3b82f6'), 0);
  assert.ok(distanciaDeCor('#000000', '#ffffff') > 95);
  assert.ok(distanciaDeCor('#3b82f6', '#3084ff') < 15);
});

test('o tema Escuro não mudou: mesmo filtro, mesmas camadas e mesma paleta', () => {
  assert.match(CSS, /\.mapa-escuro \.leaflet-tile-pane \{\s*filter: sepia\(1\) hue-rotate\(186deg\) saturate\(1\.6\) brightness\(0\.7\) contrast\(1\.8\);\s*\}/);
  assert.match(CAMADAS.escuro.base, /World_Dark_Gray_Base/);
  assert.equal(FUNDO_APROXIMADO.escuro, '#13275e');
  assert.deepEqual(PALETAS.escuro.zonas, { 30000: '#cbd5e1', 20000: '#c084fc', 12000: '#fbbf24', 7000: '#60a5fa', 3000: '#34d399' });
  assert.equal(PALETAS.escuro.hub.fundo, '#38bdf8');
});

test('o filtro do tema Claro inverte a base escura da Esri (ruas azuis sobre terreno branco)', () => {
  const m = CSS.match(/\.mapa-claro \.leaflet-tile-pane \{\s*filter: ([^;]+);/);
  assert.ok(m, 'filtro do tema claro não encontrado');
  assert.match(m[1], /^invert\(1\)/);
  assert.match(m[1], /sepia\(1\) hue-rotate\(\d+deg\) saturate\(/);
});
