import test from 'node:test';
import assert from 'node:assert/strict';
import {
  TURNOS, rotuloDoTurno, interpretarTempoPorParada, podeExecutar, textoDeConfirmacao, formatarMinutos, textoDosSetores, avisosOrdenados,
  distanciasEmLinhaReta, MSG_TEMPO_POR_PARADA,
} from './roteirizacao.js';

const tudo = { hubDefinido: true, pedidos: 5, motoristas: 2, turno: 'manha', tempoPorParada: '10' };

test('três turnos, escolhidos à mão (sem padrão)', () => {
  assert.deepEqual(TURNOS.map((t) => t.valor), ['manha', 'tarde', 'noite']);
  assert.equal(rotuloDoTurno('manha'), 'Manhã');
  assert.equal(rotuloDoTurno(''), '');
});

test('tempo por parada: vazio vale 10, inteiro de 1 a 60', () => {
  assert.deepEqual(interpretarTempoPorParada(''), { ok: true, valor: 10 });
  assert.deepEqual(interpretarTempoPorParada(' 15 '), { ok: true, valor: 15 });
  for (const ruim of ['0', '61', 'abc', '2,5', '-3']) assert.deepEqual(interpretarTempoPorParada(ruim), { ok: false, mensagem: MSG_TEMPO_POR_PARADA });
});

test('o botão só habilita com loja, pedidos, motoristas e turno', () => {
  assert.deepEqual(podeExecutar(tudo), { ok: true, falta: [] });
  assert.deepEqual(podeExecutar({ ...tudo, turno: '' }), { ok: false, falta: ['o turno'] });
  assert.deepEqual(podeExecutar({ ...tudo, turno: 'madrugada' }).falta, ['o turno']);
  assert.deepEqual(podeExecutar({ ...tudo, hubDefinido: false }).falta, ['a loja']);
  assert.deepEqual(podeExecutar({ ...tudo, pedidos: 0 }).falta, ['os pedidos']);
  assert.deepEqual(podeExecutar({ ...tudo, motoristas: 0 }).falta, ['os motoristas']);
  assert.deepEqual(podeExecutar({ hubDefinido: false, pedidos: 0, motoristas: 0, turno: '' }).falta, ['a loja', 'os pedidos', 'os motoristas', 'o turno']);
  assert.equal(podeExecutar({ ...tudo, tempoPorParada: '99' }).ok, false);
  assert.equal(podeExecutar({ ...tudo, tempoPorParada: '' }).ok, true);
});

test('confirmação curta antes de rodar', () => {
  assert.equal(textoDeConfirmacao({ turno: 'manha', loja: 'Atacadão Mooca', pedidos: 12, motoristas: 3 }),
    'Gerar as rotas do turno da manhã para Atacadão Mooca com 12 pedidos e 3 motoristas?');
  assert.equal(textoDeConfirmacao({ turno: 'noite', loja: '', pedidos: 1, motoristas: 1 }),
    'Gerar as rotas do turno da noite para o endereço informado com 1 pedido e 1 motorista?');
});

test('tempos, setores e avisos', () => {
  assert.equal(formatarMinutos(45), '45 min');
  assert.equal(formatarMinutos(125), '2h 5m');
  assert.equal(formatarMinutos(null), '0 min');
  assert.equal(textoDosSetores(['N', 'NE']), 'N, NE');
  assert.equal(textoDosSetores([]), '—');
  const ordenados = avisosOrdenados([{ gravidade: 'info', tipo: 'a' }, { gravidade: 'atencao', tipo: 'b' }, { gravidade: 'info', tipo: 'c' }, { gravidade: 'atencao', tipo: 'd' }]);
  assert.deepEqual(ordenados.map((a) => a.tipo), ['b', 'd', 'a', 'c']);
  assert.deepEqual(avisosOrdenados(undefined), []);
  assert.equal(distanciasEmLinhaReta({ origem_distancias: 'linha_reta' }), true);
  assert.equal(distanciasEmLinhaReta({ origem_distancias: 'osrm' }), false);
  assert.equal(distanciasEmLinhaReta(null), false);
});
