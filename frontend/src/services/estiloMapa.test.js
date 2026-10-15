import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import {
  CAMADAS, ESTILO, FUNDO_APROXIMADO, ATRIBUICAO_ESRI, contraste, corDoTexto,
} from './estiloMapa.js';

const CSS = readFileSync(new URL('../index.css', import.meta.url), 'utf8');
const MAPA = readFileSync(new URL('../components/MapaLeaflet.jsx', import.meta.url), 'utf8');

// As cores que o servidor usa nas rotas (backend/main.py, CORES_ROTAS).
const CORES_DAS_ROTAS = ['#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#06B6D4', '#84CC16', '#F97316', '#14B8A6', '#6366F1', '#D946EF'];

test('o mapa é da Esri, sem chave de API, em cinza escuro, e a atribuição continua', () => {
  for (const url of Object.values(CAMADAS)) {
    assert.match(url, /^https:\/\/server\.arcgisonline\.com\/ArcGIS\/rest\/services\/Canvas\//);
    assert.doesNotMatch(url, /key|token|apikey/i);
  }
  assert.match(CAMADAS.base, /World_Dark_Gray_Base/);
  assert.match(CAMADAS.rotulos, /World_Dark_Gray_Reference/);
  assert.match(ATRIBUICAO_ESRI, /Esri/);
  assert.match(ATRIBUICAO_ESRI, /OpenStreetMap/);
});

test('o tom azul-marinho vem do filtro de CSS do mapa (o mesmo de antes)', () => {
  assert.match(CSS, /\.mapa-escuro \.leaflet-tile-pane \{\s*filter: sepia\(1\) hue-rotate\(186deg\) saturate\(1\.6\) brightness\(0\.7\) contrast\(1\.8\);\s*\}/);
});

test('há um único tema: sem seletor Escuro/Claro, sem escolha guardada no navegador e sem CSS do tema claro', () => {
  assert.doesNotMatch(CSS, /mapa-claro/);
  assert.doesNotMatch(MAPA, /Fundo do mapa|aria-pressed|localStorage|lerTema|salvarTema|TEMAS|mapa-claro/);
  assert.equal(existsSync(new URL('./temaMapa.js', import.meta.url)), false);
  assert.match(MAPA, /mapa-escuro/);
});

test('os círculos de raio têm bom contraste (3:1 ou mais) com o mapa', () => {
  for (const [raio, cor] of Object.entries(ESTILO.zonas)) {
    assert.ok(contraste(cor, FUNDO_APROXIMADO) >= 3, `${raio}: ${cor} = ${contraste(cor, FUNDO_APROXIMADO).toFixed(2)}`);
  }
});

test('as cores das rotas já têm bom contraste com o mapa e são usadas como vêm do servidor', () => {
  for (const cor of CORES_DAS_ROTAS) {
    assert.ok(contraste(cor, FUNDO_APROXIMADO) >= 3, `${cor} = ${contraste(cor, FUNDO_APROXIMADO).toFixed(2)}`);
  }
  assert.doesNotMatch(MAPA, /corDaRotaNoTema/);
});

test('o número da parada tem texto legível sobre a cor da rota', () => {
  for (const cor of CORES_DAS_ROTAS) {
    assert.ok(contraste(cor, corDoTexto(cor)) >= 3.5, cor);
  }
  assert.equal(corDoTexto('#fbbf24'), '#0f172a');
  assert.equal(corDoTexto('#1d4ed8'), '#ffffff');
});

test('o contorno das rotas, a borda das paradas e o hub se destacam do mapa', () => {
  assert.ok(contraste(ESTILO.paradaBorda, FUNDO_APROXIMADO) >= 7, 'borda');
  assert.ok(contraste(ESTILO.hub.fundo, FUNDO_APROXIMADO) >= 3, 'hub');
  assert.ok(contraste(ESTILO.hub.icone, ESTILO.hub.fundo) >= 4.5, 'ícone do hub');
  assert.ok(contraste(ESTILO.pinCep.fundo, FUNDO_APROXIMADO) >= 2.2, 'pin de CEP');
});

test('as lojas do mapa permanente e a borda verde do hub escolhido se destacam do mapa', () => {
  assert.ok(contraste(ESTILO.loja.fundo, FUNDO_APROXIMADO) >= 3, 'marcador de loja');
  assert.ok(contraste(ESTILO.loja.icone, ESTILO.loja.fundo) >= 4.5, 'ícone da loja');
  assert.ok(contraste(ESTILO.hubEscolhido.borda, FUNDO_APROXIMADO) >= 3, 'borda verde do hub');
  assert.match(ESTILO.hubEscolhido.borda, /^#22c55e$/i);
});

test('o mapa mostra as lojas com hover (nome, endereço e UF) e clique para escolher o hub, sem popup de loja', () => {
  assert.match(MAPA, /Tooltip/);
  assert.match(MAPA, /linhasDoHover/);
  assert.match(MAPA, /onEscolherLoja/);
  assert.doesNotMatch(MAPA, /filial/i);
});
