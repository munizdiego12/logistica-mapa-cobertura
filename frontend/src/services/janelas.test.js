import test from 'node:test';
import assert from 'node:assert/strict';
import {
  horaParaMinutos, minutosParaHora, janelaDaLoja, interpretarHoraDeSaida, temposDosTrechos, saidasDasViagens, chegadasDaRota, relatorioDeJanelas,
  foraDoPrazoPorRota, dicaDoSelo, resumoDoRelatorio, MSG_INFORME_A_SAIDA, MSG_SEM_LOJA, normalizarHoraDigitada, somarMinutos, resumoDaSaida, MSG_HORA_INVALIDA,
} from './janelas.js';
import { rotasEfetivas } from './despacho.js';

const LOJA = {
  janela_manha_inicio: '08:00', janela_manha_fim: '13:00', janela_tarde_inicio: '13:00', janela_tarde_fim: '18:00', janela_noite_inicio: '18:00', janela_noite_fim: '21:00',
};
const SEM_NOITE = { ...LOJA, janela_noite_inicio: null, janela_noite_fim: null };

const parada = (id, ordem) => ({ id, ordem });
// Viagem de 3 paradas: trechos de 10, 20, 5 min e volta de 15 min (50 min de deslocamento) + 3 x 10 min de parada = 80 min de duração.
const rota = (id, motorista, extra = {}) => ({
  id, motorista_id: motorista, motorista_base: `M${motorista}`, motorista: `M${motorista}`, viagem_num: 1, qtd_pedidos: 3, km_total: 12,
  paradas: [parada('a', 1), parada('b', 2), parada('c', 3)], tempos_trechos_s: [600, 1200, 300, 900], distancias_trechos_km: [2, 4, 1, 3], tempo_deslocamento_min: 50, tempo_min: 80, ...extra,
});
const pedidos = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];

test('hora e minutos, com virada de meia-noite', () => {
  assert.equal(horaParaMinutos('13:20'), 800);
  assert.equal(horaParaMinutos('8:05'), 485);
  assert.equal(horaParaMinutos('13:20:00'), 800);
  for (const ruim of ['', null, 'abc', '25:00', '12:60']) assert.equal(horaParaMinutos(ruim), null);
  assert.equal(minutosParaHora(800), '13:20');
  assert.equal(minutosParaHora(1460), '00:20 (dia seguinte)');
  assert.equal(minutosParaHora(0), '00:00');
});

test('janela da loja por turno; loja sem janela no turno (noite desligada) = null', () => {
  assert.deepEqual(janelaDaLoja(LOJA, 'tarde'), { inicio: 780, fim: 1080 });
  assert.deepEqual(janelaDaLoja(LOJA, 'noite'), { inicio: 1080, fim: 1260 });
  assert.equal(janelaDaLoja(SEM_NOITE, 'noite'), null);
  assert.equal(janelaDaLoja(null, 'manha'), null);
  assert.equal(janelaDaLoja(LOJA, 'madrugada'), null);
});

test('hora de saída digitada: vazia vale o padrão, inválida avisa sem bloquear', () => {
  assert.deepEqual(interpretarHoraDeSaida(''), { ok: true, valor: null });
  assert.deepEqual(interpretarHoraDeSaida(' 14:30 '), { ok: true, valor: 870 });
  const ruim = interpretarHoraDeSaida('quatro');
  assert.equal(ruim.ok, false);
  assert.match(ruim.mensagem, /formato 08:00/);
});

test('tempos dos trechos: exatos quando vêm do resultado e proporcionais à distância como reserva', () => {
  assert.deepEqual(temposDosTrechos(rota(1, 1)), [10, 20, 5, 15]);
  const sem = rota(1, 1, { tempos_trechos_s: undefined });
  assert.deepEqual(temposDosTrechos(sem), [10, 20, 5, 15]); // 50 min repartidos por 2, 4, 1 e 3 km
  const semTudo = rota(1, 1, { tempos_trechos_s: undefined, distancias_trechos_km: undefined });
  assert.deepEqual(temposDosTrechos(semTudo), [12.5, 12.5, 12.5, 12.5]);
});

test('chegada por parada = saída + trechos acumulados + tempo das paradas anteriores', () => {
  const c = chegadasDaRota(rota(1, 1), 8 * 60, 10);
  assert.deepEqual(c.map((x) => [x.pedidoId, x.chegada]), [['a', 490], ['b', 520], ['c', 535]]); // 08:10, 08:40, 08:55
  assert.deepEqual(chegadasDaRota(rota(1, 1), 8 * 60, 15).map((x) => x.chegada), [490, 525, 545]); // tempo por parada editado
});

test('a 2ª viagem do motorista sai quando a 1ª volta à loja', () => {
  const rotas = [rota(1, 7), rota(2, 7, { viagem_num: 2 }), rota(3, 9)];
  const s = saidasDasViagens(rotas, 480, 10);
  assert.equal(s.get(1), 480);
  assert.equal(s.get(2), 480 + 80); // 50 min de deslocamento com a volta + 3 paradas de 10 min
  assert.equal(s.get(3), 480); // outro motorista sai na hora de saída
  assert.equal(saidasDasViagens(rotas, 480, 20).get(2), 480 + 50 + 60);
});

test('pedido fora do prazo pela janela da loja', () => {
  // saída 12:30, manhã termina 13:00: chegadas 12:40, 13:10 e 13:25
  const r = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos, loja: LOJA, turno: 'manha', horaDeSaida: '12:30', tempoPorParada: 10 });
  assert.equal(r.status, 'ok');
  assert.deepEqual(r.rotas[0].fora.map((f) => [f.id, f.texto]), [
    ['b', 'chega às 13:10; a janela da manhã da loja termina às 13:00'], ['c', 'chega às 13:25; a janela da manhã da loja termina às 13:00'],
  ]);
});

test('fora do prazo: só a da loja, só a do pedido e as duas, com o motivo em linguagem do operador', () => {
  // saída 13:00, tarde (13:00-18:00): chegadas 13:10, 13:40, 13:55
  const lote = [{ id: 'a' }, { id: 'b', janela_inicio: '13:00', janela_fim: '13:30' }, { id: 'c', janela_inicio: '13:00', janela_fim: '18:00' }];
  const tarde = { ...LOJA, janela_tarde_fim: '13:30' };
  const r = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos: lote, loja: tarde, turno: 'tarde', tempoPorParada: 10 });
  const por = Object.fromEntries(r.rotas[0].fora.map((f) => [f.id, f.texto]));
  assert.equal(por.a, undefined); // 13:10 está dentro
  assert.equal(por.b, 'chega às 13:40; a janela da tarde da loja termina às 13:30 e a janela do pedido termina às 13:30');
  assert.equal(por.c, 'chega às 13:55; a janela da tarde da loja termina às 13:30');
  assert.equal(r.foraDoPrazo, 2);
  assert.equal(r.totalPedidos, 3);
  assert.equal(resumoDoRelatorio(r), '2 de 3 pedidos fora do prazo');

  const soPedido = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos: [{ id: 'a' }, { id: 'b', janela_inicio: '13:00', janela_fim: '13:30' }, { id: 'c' }], loja: LOJA, turno: 'tarde' });
  assert.deepEqual(soPedido.rotas[0].fora.map((f) => [f.id, f.texto]), [['b', 'chega às 13:40; a janela do pedido termina às 13:30']]);
});

test('o pedido sem janela própria usa só a da loja; dentro das duas não aparece', () => {
  const r = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos, loja: LOJA, turno: 'tarde' });
  assert.equal(r.status, 'ok');
  assert.equal(r.foraDoPrazo, 0);
  assert.deepEqual(r.rotas, []);
  assert.equal(resumoDoRelatorio(r), '0 de 3 pedidos fora do prazo');
});

test('pedido de janela só com um dos horários é tratado como sem janela', () => {
  const r = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos: [{ id: 'a', janela_inicio: '13:00' }, { id: 'b' }, { id: 'c' }], loja: LOJA, turno: 'tarde' });
  assert.equal(r.foraDoPrazo, 0);
});

test('chegada ANTES do início é só informação, separada, e a decisiva é a janela que começa mais tarde', () => {
  // saída 12:00 com hora digitada; tarde começa 13:00; chegadas 12:10, 12:40, 12:55
  const lote = [{ id: 'a', janela_inicio: '12:30', janela_fim: '18:00' }, { id: 'b' }, { id: 'c' }];
  const r = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos: lote, loja: LOJA, turno: 'tarde', horaDeSaida: '12:00' });
  assert.equal(r.foraDoPrazo, 0);
  assert.equal(r.antesDoInicio, 3);
  assert.deepEqual(r.rotas[0].fora, []);
  assert.equal(r.rotas[0].antes.find((x) => x.id === 'a').texto, 'chega às 12:10, antes do início da janela da tarde da loja (13:00)');
  assert.equal(resumoDoRelatorio(r), '0 de 3 pedidos fora do prazo; 3 chegam antes do início da janela');
  const soPedido = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos: [{ id: 'a', janela_inicio: '14:00', janela_fim: '18:00' }, { id: 'b' }, { id: 'c' }], loja: LOJA, turno: 'tarde' });
  assert.equal(soPedido.rotas[0].antes.find((x) => x.id === 'a').texto, 'chega às 13:10, antes do início da janela do pedido (14:00)');
});

test('loja sem janela no turno: só avalia as dos pedidos e exige a hora de saída', () => {
  const sem = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos, loja: SEM_NOITE, turno: 'noite' });
  assert.equal(sem.status, 'sem_saida');
  assert.ok(sem.mensagens.some((m) => /não tem janela para a noite/.test(m)));
  assert.ok(sem.mensagens.includes(MSG_INFORME_A_SAIDA));
  const com = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos: [{ id: 'a' }, { id: 'b', janela_inicio: '19:00', janela_fim: '19:30' }, { id: 'c' }], loja: SEM_NOITE, turno: 'noite', horaDeSaida: '19:00' });
  assert.equal(com.status, 'ok');
  assert.deepEqual(com.rotas[0].fora.map((f) => f.id), ['b']);
});

test('sem loja ("outro endereço"): janelas só dos pedidos, com a frase curta', () => {
  const r = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos, loja: null, turno: 'manha', horaDeSaida: '08:00' });
  assert.equal(r.status, 'ok');
  assert.ok(r.mensagens.includes(MSG_SEM_LOJA));
  assert.equal(relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos, loja: null, turno: 'manha' }).status, 'sem_saida');
});

test('hora de saída editável muda o resultado, e a padrão é o início da janela do turno', () => {
  const lote = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  const padrao = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos: lote, loja: LOJA, turno: 'manha', tempoPorParada: 10 });
  assert.equal(padrao.saidaUsada, 480);
  assert.equal(padrao.saidaPadrao, 480);
  assert.equal(padrao.foraDoPrazo, 0);
  const tarde = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos: lote, loja: LOJA, turno: 'manha', horaDeSaida: '12:30', tempoPorParada: 10 });
  assert.equal(tarde.saidaUsada, 750);
  assert.deepEqual(tarde.rotas[0].fora.map((f) => f.id), ['b', 'c']); // chegadas 12:40, 13:10 e 13:25
  const invalida = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos: lote, loja: LOJA, turno: 'manha', horaDeSaida: 'xx' });
  assert.equal(invalida.saidaUsada, 480); // inválida volta ao padrão e avisa
  assert.ok(invalida.mensagens.some((m) => /formato 08:00/.test(m)));
});

test('a 2ª viagem entra no relatório com o horário em que o motorista volta', () => {
  const rotas = [rota(1, 7), rota(2, 7, { viagem_num: 2, motorista: 'M7 • Viagem 2', paradas: [parada('d', 1)], tempos_trechos_s: [600, 600], distancias_trechos_km: [1, 1], tempo_deslocamento_min: 20 })];
  const lote = [...pedidos, { id: 'd' }];
  // manhã sai 08:00; viagem 1 dura 80 min (volta 09:20); chegada do 'd' = 09:20 + 10 = 09:30; janela da manhã termina 13:00 -> dentro
  const dentro = relatorioDeJanelas({ rotas, pedidos: lote, loja: LOJA, turno: 'manha' });
  assert.equal(dentro.foraDoPrazo, 0);
  const cedo = { ...LOJA, janela_manha_fim: '09:25' };
  const r = relatorioDeJanelas({ rotas, pedidos: lote, loja: cedo, turno: 'manha' });
  const viagem2 = r.rotas.find((x) => x.rotaId === 2);
  assert.equal(viagem2.saida, '09:20');
  assert.deepEqual(viagem2.fora.map((f) => [f.id, f.chegada]), [['d', '09:30']]);
});

test('recalcula depois de trocar o motorista de uma rota', () => {
  const mot = (id, nome) => ({ id, nome, tipo_veiculo: 'Carro de passeio', ativo: true });
  const rotas = [rota(1, 1), rota(2, 2, { paradas: [parada('d', 1)], tempos_trechos_s: [600, 600], distancias_trechos_km: [1, 1], tempo_deslocamento_min: 20 })];
  const lote = [...pedidos, { id: 'd' }];
  const cedo = { ...LOJA, janela_manha_fim: '09:25' };
  const antes = relatorioDeJanelas({ rotas: rotasEfetivas(rotas, {}, [mot(1, 'Ana'), mot(2, 'Beto')]), pedidos: lote, loja: cedo, turno: 'manha' });
  assert.equal(antes.rotas.find((x) => x.rotaId === 2), undefined); // Beto sai 08:00 e chega 08:10 ao 'd'
  const trocado = relatorioDeJanelas({ rotas: rotasEfetivas(rotas, { 2: 1 }, [mot(1, 'Ana'), mot(2, 'Beto')]), pedidos: lote, loja: cedo, turno: 'manha' });
  const viagem2 = trocado.rotas.find((x) => x.rotaId === 2); // agora é a 2ª viagem da Ana: sai quando a 1ª volta
  assert.equal(viagem2.saida, '09:20');
  assert.deepEqual(viagem2.fora.map((f) => f.id), ['d']);
  assert.match(viagem2.titulo, /Rota 2 · Ana/);
});

test('sem rotas não há relatório; selo e textos', () => {
  assert.equal(relatorioDeJanelas({ rotas: [], pedidos, loja: LOJA, turno: 'manha' }).status, 'sem_rotas');
  const r = relatorioDeJanelas({ rotas: [rota(1, 1)], pedidos, loja: LOJA, turno: 'manha', horaDeSaida: '12:30' });
  assert.deepEqual(foraDoPrazoPorRota(r), { 1: 2 });
  assert.equal(dicaDoSelo(3), '3 pedidos chegam fora da janela');
  assert.equal(dicaDoSelo(1), '1 pedido chega fora da janela');
  assert.equal(foraDoPrazoPorRota(null).constructor, Object);
});

test('hora digitada: "8", "830", "1230", "8:30", "08h30" e "8h" viram HH:MM', () => {
  const casos = { '8': '08:00', '830': '08:30', '1230': '12:30', '8:30': '08:30', '08h30': '08:30', '8h': '08:00', '8H30': '08:30', ' 12:05 ': '12:05', '0': '00:00', '23:59': '23:59', '9.15': '09:15' };
  for (const [digitado, esperado] of Object.entries(casos)) assert.deepEqual(normalizarHoraDigitada(digitado), { ok: true, valor: esperado }, digitado);
});

test('hora digitada vazia vale o padrão; inválida avisa e não devolve valor', () => {
  for (const vazio of ['', '   ', null, undefined]) assert.deepEqual(normalizarHoraDigitada(vazio), { ok: true, valor: '' });
  for (const ruim of ['25:00', 'abc', '12:60', '2460', '8:3', '1:2:3', '-8', '8h5', '123456']) {
    assert.deepEqual(normalizarHoraDigitada(ruim), { ok: false, valor: '', mensagem: MSG_HORA_INVALIDA }, ruim);
  }
  assert.equal(MSG_HORA_INVALIDA, 'Digite a hora de saída no formato 08:00.');
});

test('passo de 15 minutos para cima e para baixo, a partir do valor ou do padrão, sem passar de 00:00 nem de 23:59', () => {
  assert.equal(somarMinutos('12:30', 15), '12:45');
  assert.equal(somarMinutos('12:30', -15), '12:15');
  assert.equal(somarMinutos('12:50', 15), '13:05');
  assert.equal(somarMinutos('', 15, 480), '08:15'); // vazio parte do padrão do turno
  assert.equal(somarMinutos('', -15, 480), '07:45');
  assert.equal(somarMinutos('', 15), '08:15'); // sem padrão parte de 08:00
  assert.equal(somarMinutos('00:10', -15), '00:00');
  assert.equal(somarMinutos('00:00', -15), '00:00');
  assert.equal(somarMinutos('23:50', 15), '23:59');
  assert.equal(somarMinutos('23:59', 15), '23:59');
});

test('resumo da saída: digitada, padrão do turno ou pedir a hora', () => {
  assert.equal(resumoDaSaida('12:30', 480), 'Saída às 12:30');
  assert.equal(resumoDaSaida('', 480), 'Saída às 08:00 (padrão do turno)');
  assert.equal(resumoDaSaida('', null), 'Informe a hora de saída');
  assert.equal(resumoDaSaida('xx', 480), 'Saída às 08:00 (padrão do turno)');
});
