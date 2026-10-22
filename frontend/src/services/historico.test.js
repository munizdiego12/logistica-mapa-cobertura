import test from 'node:test';
import assert from 'node:assert/strict';
import {
  rotuloDoDia, agruparHistorico, tituloDaRota, detalheDaRota, textoDoEndereco, linhaDoPedido, parametrosDoHistorico, juntarPaginas, resumoDoHistorico,
  textoSemDetalhe, TAMANHO_PAGINA_HISTORICO,
} from './historico.js';

const HOJE = '2026-10-22';
const rota = (id, dia, loja, numero, extra = {}) => ({
  id, dia, loja, numero, motorista: { id: 1, nome: 'Ana' }, turno: 'manha', hora: '10:30', qtd_pedidos: 2, km: 12.5, status: 'confirmada', operador: 'Maria',
  sem_detalhe: false, pedidos: [], ...extra,
});

test('rótulos Hoje, Ontem e a data', () => {
  assert.equal(rotuloDoDia('2026-10-22', HOJE), 'Hoje');
  assert.equal(rotuloDoDia('2026-10-21', HOJE), 'Ontem');
  assert.equal(rotuloDoDia('2026-10-20', HOJE), '20/10/2026');
  assert.equal(rotuloDoDia('2026-09-30', '2026-10-01'), 'Ontem'); // virada de mês
  assert.equal(rotuloDoDia('2026-12-31', '2027-01-01'), 'Ontem'); // virada de ano
});

test('agrupamento por dia, loja e rota, na ordem em que o servidor mandou', () => {
  const rotas = [
    rota(1, '2026-10-22', 'Atacadão Mooca', 1), rota(2, '2026-10-22', 'Atacadão Mooca', 2), rota(3, '2026-10-22', "Sam's Campinas", 1),
    rota(4, '2026-10-21', 'Atacadão Mooca', 1), rota(5, '2026-10-10', 'Atacadão Mooca', 1),
  ];
  const g = agruparHistorico(rotas, HOJE);
  assert.deepEqual(g.map((d) => d.rotulo), ['Hoje', 'Ontem', '10/10/2026']);
  assert.deepEqual(g[0].lojas.map((l) => [l.loja, l.rotas.map((r) => r.id)]), [['Atacadão Mooca', [1, 2]], ["Sam's Campinas", [3]]]);
  assert.deepEqual(g[1].lojas.map((l) => l.rotas.map((r) => r.id)), [[4]]);
  assert.deepEqual(agruparHistorico([], HOJE), []);
});

test('textos da rota: título, detalhe e pedidos', () => {
  assert.equal(tituloDaRota(rota(1, HOJE, 'L', 2)), 'Ana · Rota 2');
  assert.equal(detalheDaRota(rota(1, HOJE, 'L', 1)), 'Manhã · 10:30 · 2 pedidos · 12,5 km');
  assert.equal(detalheDaRota(rota(1, HOJE, 'L', 1, { qtd_pedidos: 1, km: 8, turno: 'noite', hora: null })), 'Noite · 1 pedido · 8 km');
  assert.equal(detalheDaRota(rota(1, HOJE, 'L', 1, { km: null })), 'Manhã · 10:30 · 2 pedidos');
  assert.equal(textoSemDetalhe, 'sem detalhe dos pedidos');
});

test('pedido: endereço, "endereço removido após 90 dias" e linha completa', () => {
  const comEndereco = { ordem: 1, id: 'P1', endereco: 'Rua A, 10 - Centro', endereco_apagado: false, cidade: 'Santos', uf: 'SP' };
  const apagado = { ordem: 2, id: 'P2', endereco: null, endereco_apagado: true, cidade: 'Santos', uf: 'SP' };
  assert.equal(textoDoEndereco(comEndereco), 'Rua A, 10 - Centro');
  assert.equal(textoDoEndereco(apagado), 'endereço removido após 90 dias');
  assert.equal(textoDoEndereco(apagado, 30), 'endereço removido após 30 dias');
  assert.equal(linhaDoPedido(comEndereco), '1. #P1 · Rua A, 10 - Centro · Santos/SP');
  assert.equal(linhaDoPedido(apagado), '2. #P2 · endereço removido após 90 dias · Santos/SP');
  assert.equal(linhaDoPedido({ ordem: 3, id: 'P3', endereco: null, endereco_apagado: false }), '3. #P3 · sem endereço');
});

test('filtros viram parâmetros: só o que foi preenchido', () => {
  assert.deepEqual(parametrosDoHistorico({}), { limite: TAMANHO_PAGINA_HISTORICO, deslocamento: 0 });
  assert.deepEqual(
    parametrosDoHistorico({ de: '2026-10-16', ate: '2026-10-22', loja: 'Atacadão Mooca', motoristaId: 7, operador: 'Maria', q: '  rua a ', desfeitas: true }, 50),
    { limite: 50, deslocamento: 50, de: '2026-10-16', ate: '2026-10-22', loja: 'Atacadão Mooca', motorista_id: 7, operador_nome: 'Maria', q: 'rua a', desfeitas: 1 },
  );
  assert.deepEqual(parametrosDoHistorico({ loja: '', operador: '', q: '   ', desfeitas: false, motoristaId: '' }), { limite: 50, deslocamento: 0 });
});

test('carregar mais: junta as páginas sem repetir rotas', () => {
  const a = [rota(1, HOJE, 'L', 1), rota(2, HOJE, 'L', 2)];
  const b = [rota(2, HOJE, 'L', 2), rota(3, HOJE, 'L', 3)];
  assert.deepEqual(juntarPaginas(a, b).map((r) => r.id), [1, 2, 3]);
  assert.deepEqual(juntarPaginas([], b).map((r) => r.id), [2, 3]);
});

test('resumo não conta rotas desfeitas', () => {
  const rotas = [rota(1, HOJE, 'L', 1), rota(2, HOJE, 'L', 2, { qtd_pedidos: 1 }), rota(3, HOJE, 'L', 3, { status: 'cancelada', qtd_pedidos: 9 })];
  assert.equal(resumoDoHistorico(rotas), '2 rotas · 3 pedidos');
  assert.equal(resumoDoHistorico([rota(1, HOJE, 'L', 1, { qtd_pedidos: 1 })]), '1 rota · 1 pedido');
  assert.equal(resumoDoHistorico([]), '0 rotas · 0 pedidos');
});
