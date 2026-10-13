import test from 'node:test';
import assert from 'node:assert/strict';
import { tratarErroDeSessao, instalarTratamento401, MENSAGEM_SESSAO_EXPIRADA } from './sessao.js';

function armazenamentoFalso(inicial = {}) {
  const dados = { ...inicial };
  return {
    dados,
    getItem: (k) => (k in dados ? dados[k] : null),
    removeItem: (k) => { delete dados[k]; },
  };
}
const erro401 = (url = '/upload') => ({ response: { status: 401 }, config: { url } });

test('401 em rota protegida limpa token e operador e avisa o app', () => {
  const arm = armazenamentoFalso({ token: 'abc', operador: '{"nome":"Maria"}' });
  let avisos = 0;
  assert.equal(tratarErroDeSessao(erro401(), () => { avisos += 1; }, arm), true);
  assert.deepEqual(arm.dados, {});
  assert.equal(avisos, 1);
});

test('várias respostas 401 seguidas avisam uma vez só', () => {
  const arm = armazenamentoFalso({ token: 'abc' });
  let avisos = 0;
  tratarErroDeSessao(erro401('/otimizar/status/1'), () => { avisos += 1; }, arm);
  tratarErroDeSessao(erro401('/otimizar/status/1'), () => { avisos += 1; }, arm);
  assert.equal(avisos, 1);
});

test('outros erros (400, 403, 404, 500 e falha de rede) não mexem na sessão', () => {
  for (const status of [400, 403, 404, 422, 500]) {
    const arm = armazenamentoFalso({ token: 'abc' });
    let avisos = 0;
    assert.equal(tratarErroDeSessao({ response: { status }, config: { url: '/upload' } }, () => { avisos += 1; }, arm), false);
    assert.equal(arm.dados.token, 'abc');
    assert.equal(avisos, 0);
  }
  assert.equal(tratarErroDeSessao(new Error('Network Error'), () => assert.fail(), armazenamentoFalso({ token: 'abc' })), false);
});

test('login e cadastro não são tratados como sessão vencida', () => {
  for (const url of ['/api/auth/login', '/api/auth/register']) {
    const arm = armazenamentoFalso({ token: 'abc' });
    assert.equal(tratarErroDeSessao(erro401(url), () => assert.fail(), arm), false);
    assert.equal(arm.dados.token, 'abc');
  }
});

test('o interceptor trata o 401 e repassa o erro para quem chamou', async () => {
  let tratador;
  const instancia = { interceptors: { response: { use: (_ok, falha) => { tratador = falha; return 7; } } } };
  const arm = armazenamentoFalso({ token: 'abc' });
  globalThis.localStorage = arm;
  let avisos = 0;
  assert.equal(instalarTratamento401(instancia, () => { avisos += 1; }), 7);
  const erro = erro401();
  await assert.rejects(() => tratador(erro), (e) => e === erro);
  assert.equal(avisos, 1);
  assert.deepEqual(arm.dados, {});
  delete globalThis.localStorage;
});

test('a mensagem para o operador não tem termo técnico', () => {
  assert.equal(MENSAGEM_SESSAO_EXPIRADA, 'Sua sessão expirou. Entre novamente.');
  assert.doesNotMatch(MENSAGEM_SESSAO_EXPIRADA, /token|401|jwt|api|servidor/i);
});
