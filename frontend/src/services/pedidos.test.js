import test from 'node:test';
import assert from 'node:assert/strict';
import {
  pedidoDaLoja, datasDoLote, temPedidoSemData, pedidoNaData, pedidoCasaBusca, filtrarPedidos, alternarMarca, marcarVisiveis,
  desmarcarVisiveis, todosVisiveisMarcados, pedidosParaRoteirizar, pedidoParaRoteirizacao, idsSemEndereco, corrigirEndereco, paginar,
  dataParaExibir, textoDoErro, temErroDeEndereco, TODAS_AS_DATAS, SEM_DATA, TAMANHO_PAGINA, MSG_ERRO_ENDERECO,
} from './pedidos.js';

const pedido = (id, extra = {}) => ({
  id: String(id), loja_id: null, cliente: 'Maria Souza', endereco: 'Avenida Paulista', numero: '1500', bairro: 'Bela Vista', cidade: 'São Paulo', uf: 'SP',
  cep: '01310-100', data_entrega: '2026-10-21', volume: 1, ...extra,
});

const LOTE = [
  pedido(1, { loja_id: 10 }),
  pedido(2, { loja_id: 10, data_entrega: '2026-10-22', cliente: 'João Álvares', endereco: 'Rua Augusta' }),
  pedido(3, { loja_id: 20, data_entrega: '2026-10-21' }),
  pedido(4, { loja_id: null, data_entrega: null, cliente: null, endereco: 'Rua da Consolação' }),
  pedido(5, { loja_id: 10, data_entrega: '2026-10-22' }),
];

test('mensagem de erro de endereço é a combinada', () => {
  assert.equal(MSG_ERRO_ENDERECO, 'Erro ao tentar encontrar endereço do pedido');
});

test('pedido sem loja no arquivo vale para qualquer loja; sem loja escolhida vale tudo', () => {
  assert.equal(pedidoDaLoja(pedido(1, { loja_id: 10 }), 10), true);
  assert.equal(pedidoDaLoja(pedido(1, { loja_id: 10 }), 20), false);
  assert.equal(pedidoDaLoja(pedido(1), 20), true);
  assert.equal(pedidoDaLoja(pedido(1, { loja_id: 10 }), null), true);
});

test('datas do lote em ordem, sem repetir; sem data nenhuma a lista vem vazia', () => {
  assert.deepEqual(datasDoLote(LOTE), ['2026-10-21', '2026-10-22']);
  assert.deepEqual(datasDoLote([pedido(1, { data_entrega: null })]), []);
  assert.equal(temPedidoSemData(LOTE), true);
  assert.equal(temPedidoSemData([pedido(1)]), false);
});

test('filtro por data: uma data, sem data e todas', () => {
  assert.equal(pedidoNaData(pedido(1), '2026-10-21'), true);
  assert.equal(pedidoNaData(pedido(1), '2026-10-22'), false);
  assert.equal(pedidoNaData(pedido(1, { data_entrega: null }), SEM_DATA), true);
  assert.equal(pedidoNaData(pedido(1), SEM_DATA), false);
  assert.equal(pedidoNaData(pedido(1, { data_entrega: null }), TODAS_AS_DATAS), true);
});

test('filtro por loja avisa quantos ficaram de fora', () => {
  const r = filtrarPedidos(LOTE, { lojaId: 10 });
  assert.deepEqual(r.visiveis.map((p) => p.id), ['1', '2', '4', '5']);
  assert.equal(r.foraDaLoja, 1);
  assert.equal(r.naLoja, 4);
  assert.equal(filtrarPedidos(LOTE, { lojaId: 20 }).foraDaLoja, 3);
  assert.equal(filtrarPedidos(LOTE, { lojaId: null }).foraDaLoja, 0);
});

test('filtro por loja e data juntos; sem datas no lote mostra tudo', () => {
  assert.deepEqual(filtrarPedidos(LOTE, { lojaId: 10, data: '2026-10-22' }).visiveis.map((p) => p.id), ['2', '5']);
  assert.deepEqual(filtrarPedidos(LOTE, { lojaId: 10, data: SEM_DATA }).visiveis.map((p) => p.id), ['4']);
  const semDatas = [pedido(1, { data_entrega: null }), pedido(2, { data_entrega: null })];
  assert.equal(filtrarPedidos(semDatas, { data: TODAS_AS_DATAS }).visiveis.length, 2);
});

test('busca por id, cliente ou endereço sem diferença de maiúsculas nem acentos', () => {
  assert.equal(pedidoCasaBusca(LOTE[1], 'joao alvares'), true);
  assert.equal(pedidoCasaBusca(LOTE[1], 'AUGUSTA'), true);
  assert.equal(pedidoCasaBusca(LOTE[1], '2'), true);
  assert.equal(pedidoCasaBusca(LOTE[1], 'paulista'), false);
  assert.equal(pedidoCasaBusca(LOTE[3], 'consolacao'), true);
  assert.equal(pedidoCasaBusca(LOTE[3], 'maria'), false); // cliente vazio
  assert.deepEqual(filtrarPedidos(LOTE, { busca: 'rua' }).visiveis.map((p) => p.id), ['2', '4']);
  assert.equal(filtrarPedidos(LOTE, { busca: '  ' }).visiveis.length, 5);
});

test('marcar e desmarcar todos os visíveis não mexe nos outros', () => {
  const visiveis = filtrarPedidos(LOTE, { lojaId: 10, data: '2026-10-22' }).visiveis;
  const marcados = marcarVisiveis(new Set(['3']), visiveis);
  assert.deepEqual([...marcados].sort(), ['2', '3', '5']);
  assert.equal(todosVisiveisMarcados(marcados, visiveis), true);
  assert.deepEqual([...desmarcarVisiveis(marcados, visiveis)], ['3']);
  assert.deepEqual([...alternarMarca(new Set(['1']), '1')], []);
  assert.deepEqual([...alternarMarca(new Set(['1']), '2')].sort(), ['1', '2']);
  assert.equal(todosVisiveisMarcados(new Set(), []), false);
});

test('pedido com erro de endereço não é marcado em massa e fica fora da roteirização', () => {
  const comErro = new Set(['2']);
  assert.equal(temErroDeEndereco(LOTE[1], comErro), true);
  const marcados = marcarVisiveis(new Set(), LOTE, comErro);
  assert.equal(marcados.has('2'), false);
  assert.equal(marcados.size, 4);
  // mesmo que alguém o tenha marcado antes, não entra
  const para = pedidosParaRoteirizar(LOTE, new Set(['1', '2']), { comErro });
  assert.deepEqual(para.map((p) => p.id), ['1']);
});

test('só os marcados, da loja e da data escolhidas, vão para a roteirização', () => {
  const marcados = new Set(['1', '2', '3', '4', '5']);
  assert.deepEqual(pedidosParaRoteirizar(LOTE, marcados, { lojaId: 10 }).map((p) => p.id), ['1', '2', '4', '5']);
  assert.deepEqual(pedidosParaRoteirizar(LOTE, marcados, { lojaId: 10, data: '2026-10-21' }).map((p) => p.id), ['1']);
  assert.deepEqual(pedidosParaRoteirizar(LOTE, new Set(['2']), { lojaId: 10 }).map((p) => p.id), ['2']);
  assert.deepEqual(pedidosParaRoteirizar(LOTE, new Set(), { lojaId: 10 }), []);
  // a busca digitada não tira pedidos marcados da roteirização
  assert.equal(pedidosParaRoteirizar(LOTE, marcados, { lojaId: 10 }).length, 4);
});

test('o pedido enviado à roteirização não leva cliente, complemento nem observação', () => {
  const enviado = pedidoParaRoteirizacao(pedido(7, { complemento: 'Apto 3', observacao: 'Deixar com o porteiro', cep: null, bairro: null, volume: 2 }));
  assert.deepEqual(enviado, { id: '7', Endereco: 'Avenida Paulista', Numero: '1500', Bairro: '', Cidade: 'São Paulo', UF: 'SP', CEP: '', Volume: 2 });
  assert.equal(JSON.stringify(enviado).includes('Maria Souza'), false);
});

test('ids sem endereço vêm do resultado da roteirização e a correção libera o pedido', () => {
  assert.deepEqual([...idsSemEndereco({ pedidos_sem_geocodificacao: [{ id: '2' }, { id: '5' }] })], ['2', '5']);
  assert.equal(idsSemEndereco(null).size, 0);
  const antes = new Set(['2', '5']);
  const { pedidos, comErro } = corrigirEndereco(LOTE, antes, '2', { endereco: ' Rua Nova ', numero: '10', cep: '01000-000', cliente: 'não deve mudar' });
  assert.equal(pedidos[1].endereco, 'Rua Nova');
  assert.equal(pedidos[1].cliente, 'João Álvares');
  assert.deepEqual([...comErro], ['5']);
  assert.deepEqual([...antes], ['2', '5']); // não altera o conjunto original
  assert.equal(LOTE[1].endereco, 'Rua Augusta');
});

test('paginação de 50 em 50, com limites seguros', () => {
  const lista = Array.from({ length: 120 }, (_, i) => i);
  assert.equal(TAMANHO_PAGINA, 50);
  assert.deepEqual(paginar(lista, 1).itens.length, 50);
  assert.equal(paginar(lista, 3).itens.length, 20);
  assert.equal(paginar(lista, 3).totalPaginas, 3);
  assert.equal(paginar(lista, 99).pagina, 3);
  assert.equal(paginar(lista, 0).pagina, 1);
  assert.deepEqual(paginar([], 1), { itens: [], pagina: 1, totalPaginas: 1 });
});

test('textos de exibição', () => {
  assert.equal(dataParaExibir('2026-10-21'), '21/10/2026');
  assert.equal(dataParaExibir(null), '');
  assert.equal(textoDoErro({ linha: 12, id: '99', motivos: ['id repetido', 'CEP inválido'] }), 'Linha 12 (id 99): id repetido; CEP inválido');
  assert.equal(textoDoErro({ linha: 3, id: '', motivos: ['campo obrigatório vazio: id'] }), 'Linha 3: campo obrigatório vazio: id');
});

test('lote grande: filtro e paginação continuam rápidos e corretos', () => {
  const grande = Array.from({ length: 20000 }, (_, i) => pedido(i + 1, { loja_id: i % 2 ? 10 : 20 }));
  const r = filtrarPedidos(grande, { lojaId: 10, busca: 'paulista' });
  assert.equal(r.visiveis.length, 10000);
  assert.equal(paginar(r.visiveis, 2).itens[0].id, '102');
});
