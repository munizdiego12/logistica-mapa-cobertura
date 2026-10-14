import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CHAVE_TEMA, TEMAS, TEMA_PADRAO, CAMADAS, PALETAS, FUNDO_APROXIMADO, ATRIBUICAO_ESRI,
  lerTema, salvarTema, contraste, corDoTexto, corDaRotaNoTema,
} from './temaMapa.js';

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
  assert.match(CAMADAS.claro.base, /World_Light_Gray_Base/);
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
  assert.equal(corDaRotaNoTema('#1d4ed8', 'claro'), '#1d4ed8');
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
