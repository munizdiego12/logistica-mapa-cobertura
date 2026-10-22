import test from 'node:test';
import assert from 'node:assert/strict';
import {
  seloDeDuplicidade, estaJaRoteirizado, idsParaConsultar, aplicarDuplicidade, avisoDesmarcados, perguntasParaMarcarDeNovo, confirmarMarcarDeNovo,
  contarJaRoteirizados, textoJaRoteirizadosNaConfirmacao, avisoMarcarVisiveis, MSG_FALHA_DUPLICIDADE,
} from './duplicidade.js';
import { marcarVisiveis, contarDeixadosDeFora, todosVisiveisMarcados, pedidosParaRoteirizar } from './pedidos.js';
import { textoDeConfirmacao } from './roteirizacao.js';

const INFO = { rota: 2, motorista: 'Ana', turno: 'manha', loja: 'Atacadão Mooca', operador: 'Maria', hora: '10:30' };
const JA = { 2: INFO, 4: { ...INFO, rota: 1, motorista: 'Beto', turno: 'tarde', hora: '14:05' } };
const p = (id) => ({ id: String(id), loja_id: null, endereco: 'Rua', numero: '1', cidade: 'SP', uf: 'SP' });
const LOTE = [1, 2, 3, 4, 5].map(p);

test('selo: "já está na Rota N de [motorista] ([turno], hh:mm)"', () => {
  assert.equal(seloDeDuplicidade(INFO), 'já está na Rota 2 de Ana (manhã, 10:30)');
  assert.equal(seloDeDuplicidade(JA[4]), 'já está na Rota 1 de Beto (tarde, 14:05)');
  assert.equal(seloDeDuplicidade({ rota: 3 }), 'já está na Rota 3');
  assert.equal(seloDeDuplicidade(null), '');
});

test('estaJaRoteirizado: consulta nula (falha) nunca marca ninguém como já roteirizado', () => {
  assert.equal(estaJaRoteirizado(JA, '2'), true);
  assert.equal(estaJaRoteirizado(JA, '3'), false);
  assert.equal(estaJaRoteirizado(null, '2'), false);
  assert.equal(estaJaRoteirizado({}, 'toString'), false);
});

test('ids da consulta: todos os lotes, sem repetir, como texto', () => {
  assert.deepEqual(idsParaConsultar([{ pedidos: [p(1), p(2)] }, { pedidos: [p(2), { id: 7 }] }]), ['1', '2', '7']);
});

test('pedido já roteirizado entra DESMARCADO, com a contagem do aviso único', () => {
  const r = aplicarDuplicidade(new Set(LOTE.map((x) => x.id)), JA, new Set());
  assert.deepEqual([...r.marcados].sort(), ['1', '3', '5']);
  assert.equal(r.desmarcados, 2);
  assert.deepEqual([...r.tratados].sort(), ['2', '4']);
  assert.equal(avisoDesmarcados(r.desmarcados), '2 pedidos deste lote já estão em rotas de hoje e foram desmarcados; marque-os de novo só se for de propósito.');
  assert.equal(avisoDesmarcados(1), '1 pedido deste lote já está em rota de hoje e foi desmarcado; marque-o de novo só se for de propósito.');
  assert.equal(avisoDesmarcados(0), null);
});

test('cada pedido é desmarcado uma vez só: marcar de volta de propósito vale nas consultas seguintes (sem novo aviso)', () => {
  const primeira = aplicarDuplicidade(new Set(['1', '2', '3']), JA, new Set());
  const deVolta = new Set([...primeira.marcados, '2']); // o operador marcou o 2 de propósito
  const segunda = aplicarDuplicidade(deVolta, JA, primeira.tratados);
  assert.equal(segunda.desmarcados, 0);
  assert.equal(segunda.marcados.has('2'), true);
  assert.equal(avisoDesmarcados(segunda.desmarcados), null);
});

test('depois de "Confirmar rotas", os recém-confirmados saem da marcação (consulta refeita) sem mexer nos demais', () => {
  const marcados = new Set(['1', '2', '3']);
  const depois = aplicarDuplicidade(marcados, { 1: INFO, 3: INFO }, new Set());
  assert.deepEqual([...depois.marcados], ['2']);
  assert.equal(depois.desmarcados, 2);
  assert.deepEqual([...marcados].sort(), ['1', '2', '3']); // o conjunto recebido não é alterado
});

test('falha da consulta (resultado nulo) não desmarca nada', () => {
  const marcados = new Set(['1', '2']);
  const tratados = new Set();
  const r = aplicarDuplicidade(marcados, null, tratados);
  assert.equal(r.marcados, marcados);
  assert.equal(r.tratados, tratados);
  assert.equal(r.desmarcados, 0);
  assert.match(MSG_FALHA_DUPLICIDADE, /Não foi possível verificar/);
  assert.doesNotMatch(MSG_FALHA_DUPLICIDADE, /tabela|API|servidor|banco/i);
});

test('pedido já roteirizado e não marcado não conta como desmarcado', () => {
  const r = aplicarDuplicidade(new Set(['1']), JA, new Set());
  assert.equal(r.desmarcados, 0);
  assert.deepEqual([...r.tratados].sort(), ['2', '4']);
});

test('marcar de volta pede as duas confirmações em sequência (cancelar na 1ª ou na 2ª não marca)', () => {
  const [primeira, segunda] = perguntasParaMarcarDeNovo(INFO);
  assert.equal(primeira, 'Este pedido já está na Rota 2 de Ana hoje. Marcar mesmo assim?');
  assert.notEqual(primeira, segunda);

  let perguntas = [];
  assert.equal(confirmarMarcarDeNovo(INFO, (t) => { perguntas.push(t); return true; }), true);
  assert.deepEqual(perguntas, [primeira, segunda]);

  perguntas = [];
  assert.equal(confirmarMarcarDeNovo(INFO, (t) => { perguntas.push(t); return false; }), false);
  assert.deepEqual(perguntas, [primeira]); // cancelou na 1ª: nem pergunta a 2ª

  perguntas = [];
  assert.equal(confirmarMarcarDeNovo(INFO, (t) => { perguntas.push(t); return perguntas.length === 1; }), false);
  assert.equal(perguntas.length, 2); // aceitou a 1ª e cancelou a 2ª
});

test('"Marcar visíveis" não marca os já roteirizados e diz quantos ficaram de fora', () => {
  const marcados = marcarVisiveis(new Set(), LOTE, new Set(), JA);
  assert.deepEqual([...marcados].sort(), ['1', '3', '5']);
  assert.equal(contarDeixadosDeFora(new Set(), LOTE, new Set(), JA), 2);
  assert.equal(avisoMarcarVisiveis(2), '2 pedidos já roteirizados hoje ficaram de fora. Marque esses pedidos um a um, se for de propósito.');
  assert.equal(avisoMarcarVisiveis(1), '1 pedido já roteirizado hoje ficou de fora. Marque esse pedido um a um, se for de propósito.');
  assert.equal(avisoMarcarVisiveis(0), null);
});

test('"Marcar visíveis" mantém os já roteirizados que o operador marcou de propósito e não os conta como deixados', () => {
  const marcados = marcarVisiveis(new Set(['2']), LOTE, new Set(), JA);
  assert.equal(marcados.has('2'), true);
  assert.equal(contarDeixadosDeFora(new Set(['2']), LOTE, new Set(), JA), 1);
});

test('sem consulta (nula) "Marcar visíveis" se comporta como antes', () => {
  assert.deepEqual([...marcarVisiveis(new Set(), LOTE, new Set(), null)].sort(), ['1', '2', '3', '4', '5']);
  assert.equal(contarDeixadosDeFora(new Set(), LOTE, new Set(), null), 0);
});

test('o botão "Marcar visíveis" desabilita quando só restam já roteirizados desmarcados', () => {
  assert.equal(todosVisiveisMarcados(new Set(['1', '3', '5']), LOTE, new Set(), JA), true);
  assert.equal(todosVisiveisMarcados(new Set(['1', '3']), LOTE, new Set(), JA), false);
  assert.equal(todosVisiveisMarcados(new Set(['1', '3', '5']), LOTE, new Set(), null), false);
});

test('texto da confirmação de "Executar Roteirização" traz a contagem de marcados já roteirizados', () => {
  const marcados = new Set(['1', '2', '4']);
  const entram = pedidosParaRoteirizar(LOTE, marcados);
  const n = contarJaRoteirizados(entram, JA);
  assert.equal(n, 2);
  const base = 'Gerar as rotas do turno da manhã para Atacadão Mooca com 3 pedidos e 2 motoristas?';
  assert.equal(textoDeConfirmacao({ turno: 'manha', loja: 'Atacadão Mooca', pedidos: 3, motoristas: 2 }), base); // sem duplicados, texto igual ao de antes
  assert.equal(textoDeConfirmacao({ turno: 'manha', loja: 'Atacadão Mooca', pedidos: 3, motoristas: 2, jaRoteirizados: n }),
    `${base}\n\nAtenção: 2 pedidos marcados já estão em rotas confirmadas de hoje.`);
  assert.equal(textoJaRoteirizadosNaConfirmacao(1), '\n\nAtenção: 1 pedido marcado já está em rotas confirmadas de hoje.');
  assert.equal(textoJaRoteirizadosNaConfirmacao(0), '');
});
