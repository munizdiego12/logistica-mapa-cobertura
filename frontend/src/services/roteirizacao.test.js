import test from 'node:test';
import assert from 'node:assert/strict';
import {
  TURNOS, rotuloDoTurno, interpretarTempoPorParada, podeExecutar, textoDeConfirmacao, formatarMinutos, textoDosSetores, avisosOrdenados,
  distanciasEmLinhaReta, MSG_TEMPO_POR_PARADA, OPCOES_DE_VIAGENS, recomendarRotas, textoRecomendado, corpoDasViagens, manterViagensDosMarcados, AVISO_VIAGENS,
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


test('opções de rotas por motorista: automático (recomendado) e 1 a 4', () => {
  assert.deepEqual(OPCOES_DE_VIAGENS.map((o) => o.valor), ['', '1', '2', '3', '4']);
  assert.equal(OPCOES_DE_VIAGENS[0].rotulo, 'Automático (recomendado)');
  assert.match(AVISO_VIAGENS, /Cada viagem conta como uma rota no dia/);
});

test('recomendado = ceil(pedidos / soma dos tetos dos motoristas marcados), mínimo 1', () => {
  const cap = { 'Carro de passeio': { capacidade: 5 }, 'Fiorino/Utilitário': { capacidade: 12 } };
  assert.equal(recomendarRotas(20, ['Carro de passeio', 'Carro de passeio'], cap), 2); // 20 / (5+5)
  assert.equal(recomendarRotas(10, ['Carro de passeio', 'Carro de passeio'], cap), 1);
  assert.equal(recomendarRotas(11, ['Carro de passeio', 'Carro de passeio'], cap), 2);
  assert.equal(recomendarRotas(24, ['Carro de passeio', 'Fiorino/Utilitário'], cap), 2); // tipos mistos: 24 / (5+12)
  assert.equal(recomendarRotas(0, ['Carro de passeio'], cap), 1); // mínimo 1
  assert.equal(recomendarRotas(30, [], cap), 1); // sem motorista marcado
  assert.equal(recomendarRotas(13, ['Tipo novo'], cap), 3); // tipo sem capacidade: 6 (como no servidor)
  assert.equal(recomendarRotas(10, ['Carro de passeio'], { 'Carro de passeio': 5 }), 2); // aceita {tipo: número}
});

test('texto do recomendado: singular e plural', () => {
  assert.equal(textoRecomendado(1), 'Recomendado: 1 rota com base na quantidade de pedidos');
  assert.equal(textoRecomendado(3), 'Recomendado: 3 rotas com base na quantidade de pedidos');
});

test('corpo das viagens: só os marcados com número de 1 a 4; automático fica de fora', () => {
  assert.deepEqual(corpoDasViagens([1, 2, 3], { 1: '2', 2: '', 3: '4', 9: '1' }), { 1: 2, 3: 4 });
  assert.deepEqual(corpoDasViagens([1], { 1: '7' }), {});
  assert.deepEqual(corpoDasViagens([1], { 1: 'abc' }), {});
  assert.deepEqual(corpoDasViagens(undefined, undefined), {});
  assert.deepEqual(manterViagensDosMarcados({ 1: '2', 2: '3' }, [2]), { 2: '3' });
});
