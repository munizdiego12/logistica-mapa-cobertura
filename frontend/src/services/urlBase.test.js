import test from 'node:test';
import assert from 'node:assert/strict';
import { resolverUrlBase, URL_PADRAO } from './urlBase.js';

test('sem VITE_API_URL (ou vazia) o padrão é o backend do Render', () => {
  assert.equal(URL_PADRAO, 'https://routeflow-backend-v5ji.onrender.com');
  for (const vazio of [undefined, null, '', '   ']) assert.equal(resolverUrlBase(vazio), URL_PADRAO);
});

test('VITE_API_URL troca a URL base, inclusive para um backend local', () => {
  assert.equal(resolverUrlBase('http://127.0.0.1:8000'), 'http://127.0.0.1:8000');
  assert.equal(resolverUrlBase('https://meu-backend.exemplo.com'), 'https://meu-backend.exemplo.com');
});

test('barra final, espaços e /api no fim não geram endereço duplicado', () => {
  assert.equal(resolverUrlBase(' https://meu-backend.exemplo.com/ '), 'https://meu-backend.exemplo.com');
  assert.equal(resolverUrlBase('https://meu-backend.exemplo.com/api'), 'https://meu-backend.exemplo.com');
  assert.equal(resolverUrlBase('http://localhost:8000/api/'), 'http://localhost:8000');
});

test('valor sem http(s) cai no padrão em vez de virar endereço relativo', () => {
  for (const ruim of ['127.0.0.1:8000', 'localhost:8000', '/api', 'ftp://x', 'abc']) assert.equal(resolverUrlBase(ruim), URL_PADRAO, ruim);
});
