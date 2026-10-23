import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  indexarItens, pesoDoPedido, formatarKg, textoDoPeso, pesoDosPedidos, textoDoTotal, detalheDoTotal, pesoPorViagem, pesoPorMotorista, pesoPorTipoDeVeiculo,
  pedidosComItens, skusDosItens, emBlocos, skusParaRegistrar, marcarComoRegistrados, substituirPesos, resumoDosItens, TAMANHO_BLOCO_SKUS_VISTOS,
} from './pesoPedidos.js';
import { rotasEfetivas } from './despacho.js';

const PESOS = { A: { peso_kg: 5, confianca: 'alta' }, B: { peso_kg: 0.2, confianca: 'media' }, C: { peso_kg: null, confianca: null } }; // D não existe no cadastro
const ITENS = indexarItens([
  { id_pedido: '1', sku: 'A', quantidade: 2 }, { id_pedido: '1', sku: 'B', quantidade: 1.5 },
  { id_pedido: '2', sku: 'A', quantidade: 1 }, { id_pedido: '2', sku: 'C', quantidade: 3 },
  { id_pedido: '3', sku: 'D', quantidade: 1 },
  // pedido 4 não tem itens no arquivo
]);

test('indexar os itens por pedido', () => {
  assert.deepEqual(ITENS['1'], [{ sku: 'A', quantidade: 2 }, { sku: 'B', quantidade: 1.5 }]);
  assert.equal(pedidosComItens(ITENS), 3);
  assert.deepEqual(skusDosItens(ITENS).sort(), ['A', 'B', 'C', 'D']);
  assert.deepEqual(indexarItens([]), {});
  assert.deepEqual(indexarItens(null), {});
});

test('peso do pedido completo: soma de quantidade x peso, com o selo "estimado"', () => {
  const p = pesoDoPedido(ITENS['1'], PESOS);
  assert.deepEqual(p, { estado: 'completo', kg: 10.3, faltam: 0 }); // 2 x 5 + 1,5 x 0,2
  assert.equal(textoDoPeso(p), '≈ 10,3 kg (estimado)');
  assert.equal(formatarKg(1234.5678), '1.234,57');
});

test('peso do pedido incompleto: "≥ X kg, faltam N itens", item sem peso e item fora do cadastro', () => {
  const sem = pesoDoPedido(ITENS['2'], PESOS); // C existe sem peso
  assert.deepEqual(sem, { estado: 'incompleto', kg: 5, faltam: 1 });
  assert.equal(textoDoPeso(sem), '≥ 5 kg, faltam 1 item (estimado)');
  const fora = pesoDoPedido(ITENS['3'], PESOS); // D não existe no cadastro
  assert.deepEqual(fora, { estado: 'incompleto', kg: 0, faltam: 1 });
  assert.equal(textoDoPeso(fora), '≥ 0 kg, faltam 1 item (estimado)');
  assert.equal(textoDoPeso(pesoDoPedido([{ sku: 'C', quantidade: 1 }, { sku: 'D', quantidade: 1 }], PESOS)), '≥ 0 kg, faltam 2 itens (estimado)');
});

test('pedido sem itens no arquivo: "sem itens informados", nunca 0 kg', () => {
  for (const vazio of [undefined, null, []]) {
    const p = pesoDoPedido(vazio, PESOS);
    assert.deepEqual(p, { estado: 'sem_itens', kg: null, faltam: 0 });
    assert.equal(textoDoPeso(p), 'sem itens informados');
    assert.ok(!/0 kg/.test(textoDoPeso(p)));
  }
});

test('peso aparece depois de o operador cadastrar o peso (recalcula)', () => {
  assert.equal(pesoDoPedido(ITENS['2'], PESOS).estado, 'incompleto');
  const novos = substituirPesos(PESOS, ['C'], { C: { peso_kg: 1, confianca: 'alta' } });
  assert.deepEqual(pesoDoPedido(ITENS['2'], novos), { estado: 'completo', kg: 8, faltam: 0 });
  assert.equal(PESOS.C.peso_kg, null); // não altera o que recebeu
  assert.equal(substituirPesos(PESOS, ['A'], {}).A, undefined); // o SKU consultado que sumiu deixa de existir
  assert.deepEqual(substituirPesos(PESOS, [], { Z: { peso_kg: 2, confianca: 'baixa' } }).Z, { peso_kg: 2, confianca: 'baixa' });
});

test('total dos marcados: completo (≈), mínimo (≥ com o que falta) e sem itens', () => {
  const completo = pesoDosPedidos(['1'], ITENS, PESOS);
  assert.equal(textoDoTotal(completo), '≈ 10,3 kg (estimado)');
  assert.equal(detalheDoTotal(completo), '');
  const minimo = pesoDosPedidos(['1', '2', '3', '4'], ITENS, PESOS);
  assert.deepEqual(minimo, { estado: 'minimo', kg: 15.3, faltamItens: 2, pedidosIncompletos: 2, pedidosSemItens: 1, pedidos: 4 });
  assert.equal(textoDoTotal(minimo), '≥ 15,3 kg (estimado)');
  assert.equal(detalheDoTotal(minimo), 'faltam 2 itens em 2 pedidos; 1 pedido sem itens informados');
  const soSemItens = pesoDosPedidos(['4', '5'], ITENS, PESOS);
  assert.equal(soSemItens.estado, 'sem_itens');
  assert.equal(textoDoTotal(soSemItens), 'sem itens informados');
  assert.equal(detalheDoTotal(pesoDosPedidos(['1', '4', '4'], ITENS, PESOS)), '2 pedidos sem itens informados');
  assert.equal(pesoDosPedidos([], ITENS, PESOS).kg, 0);
});

const parada = (id) => ({ id });
const rota = (id, motorista, nome, modal, ids) => ({ id, motorista_id: motorista, motorista_base: nome, motorista: nome, modal, viagem_num: 1, paradas: ids.map(parada) });
const ROTAS = [rota(1, 1, 'Ana', 'Carro de passeio', ['1']), rota(2, 1, 'Ana', 'Carro de passeio', ['2', '3']), rota(3, 2, 'Beto', 'Fiorino/Utilitário', ['4', '1x'])];

test('peso por viagem, motorista e tipo de veículo, sempre estimado', () => {
  const viagem = pesoPorViagem(ROTAS, ITENS, PESOS);
  assert.equal(textoDoTotal(viagem[1]), '≈ 10,3 kg (estimado)');
  assert.equal(textoDoTotal(viagem[2]), '≥ 5 kg (estimado)');
  assert.equal(detalheDoTotal(viagem[2]), 'faltam 2 itens em 2 pedidos');
  assert.equal(viagem[3].estado, 'sem_itens'); // pedidos 4 e 1x sem itens
  const motoristas = pesoPorMotorista(ROTAS, ITENS, PESOS);
  assert.deepEqual(motoristas.map((m) => [m.nome, m.viagens, m.pedidos, textoDoTotal(m.total)]), [['Ana', 2, 3, '≥ 15,3 kg (estimado)'], ['Beto', 1, 2, 'sem itens informados']]);
  const tipos = pesoPorTipoDeVeiculo(ROTAS, ITENS, PESOS);
  assert.deepEqual(tipos.map((t) => [t.nome, t.viagens, t.pedidos, t.total.estado]), [['Carro de passeio', 2, 3, 'minimo'], ['Fiorino/Utilitário', 1, 2, 'sem_itens']]);
});

test('trocar o motorista de uma rota move o peso dela por motorista e por tipo de veículo', () => {
  const motoristas = [{ id: 1, nome: 'Ana', tipo_veiculo: 'Carro de passeio', ativo: true }, { id: 2, nome: 'Beto', tipo_veiculo: 'Fiorino/Utilitário', ativo: true }];
  const trocadas = rotasEfetivas(ROTAS, { 1: 2 }, motoristas); // a rota 1 (pedido 1, 10,3 kg) passa da Ana (carro) para o Beto (utilitário)
  const porMotorista = Object.fromEntries(pesoPorMotorista(trocadas, ITENS, PESOS).map((m) => [m.nome, m]));
  assert.equal(porMotorista.Ana.total.kg, 5);
  assert.equal(porMotorista.Ana.pedidos, 2);
  assert.equal(porMotorista.Beto.total.kg, 10.3);
  assert.equal(porMotorista.Beto.pedidos, 3);
  const porTipo = Object.fromEntries(pesoPorTipoDeVeiculo(trocadas, ITENS, PESOS).map((t) => [t.nome, t]));
  assert.equal(porTipo['Carro de passeio'].total.kg, 5);
  assert.equal(porTipo['Fiorino/Utilitário'].total.kg, 10.3);
  // o total geral não muda com a troca
  assert.equal(pesoDosPedidos(trocadas.flatMap((r) => r.paradas.map((p) => p.id)), ITENS, PESOS).kg, 15.3);
});

test('SKUs para a fila "sem peso": só novos ou sem peso, ainda não registrados, com quantidade somada para cima e a primeira descrição', () => {
  const itens = [
    { id_pedido: '1', sku: 'A', quantidade: 2, descricao: 'Arroz' }, // tem peso: fora
    { id_pedido: '1', sku: 'C', quantidade: 1.2, descricao: 'Primeira' }, // sem peso
    { id_pedido: '2', sku: 'C', quantidade: 0.5, descricao: 'Segunda' },
    { id_pedido: '3', sku: 'D', quantidade: 0.1, descricao: null }, // novo, sem descrição, quantidade < 1 vira 1
    { id_pedido: '3', sku: 'E', quantidade: 3, descricao: 'x'.repeat(400) }, // novo, descrição cortada em 300
  ];
  const pesos = { A: { peso_kg: 5, confianca: 'alta' }, C: { peso_kg: null, confianca: null } };
  const lista = skusParaRegistrar(itens, pesos, []);
  assert.deepEqual(lista.map((s) => s.id_sku), ['C', 'D', 'E']);
  assert.deepEqual(lista[0], { id_sku: 'C', quantidade: 2, nome: 'Primeira' }); // 1,7 -> 2
  assert.deepEqual(lista[1], { id_sku: 'D', quantidade: 1 });
  assert.equal(lista[2].nome.length, 300);
  assert.ok(lista.every((s) => Object.keys(s).every((k) => ['id_sku', 'quantidade', 'nome'].includes(k)))); // nada de pedido, endereço ou cliente
});

test('"skus-vistos" soma a cada chamada: SKU já registrado no lote não vai de novo (aceitar de novo, reenviar o mesmo arquivo)', () => {
  const itens = [{ id_pedido: '1', sku: 'C', quantidade: 2 }, { id_pedido: '1', sku: 'D', quantidade: 1 }];
  const pesos = { C: { peso_kg: null, confianca: null } };
  const primeira = skusParaRegistrar(itens, pesos, []);
  assert.equal(primeira.length, 2);
  const registrados = marcarComoRegistrados([], primeira);
  assert.deepEqual(registrados.sort(), ['C', 'D']);
  assert.deepEqual(skusParaRegistrar(itens, pesos, registrados), []); // reenviar o mesmo arquivo: nada a registrar
  const maisUm = [...itens, { id_pedido: '2', sku: 'F', quantidade: 1 }];
  assert.deepEqual(skusParaRegistrar(maisUm, pesos, registrados).map((s) => s.id_sku), ['F']); // arquivo novo: só o SKU ainda não registrado
  assert.deepEqual(marcarComoRegistrados(registrados, []).sort(), ['C', 'D']);
  assert.deepEqual(registrados.sort(), ['C', 'D']); // o recebido não é alterado
});

test('blocos de até 5.000 para "skus-vistos"', () => {
  const lista = Array.from({ length: 12001 }, (_, i) => i);
  const blocos = emBlocos(lista, TAMANHO_BLOCO_SKUS_VISTOS);
  assert.deepEqual(blocos.map((b) => b.length), [5000, 5000, 2001]);
  assert.deepEqual(emBlocos([], 5000), []);
});

test('resumo dos itens', () => {
  assert.equal(resumoDosItens(ITENS), '3 pedidos com itens');
  assert.equal(resumoDosItens({ 1: [{ sku: 'A', quantidade: 1 }] }), '1 pedido com itens');
  assert.equal(resumoDosItens({}), '');
  assert.equal(resumoDosItens(null), '');
});

test('nada bloqueante: o módulo não fala de capacidade, aviso vermelho, solver nem peso de referência, e não envia nada para fora', () => {
  const fonte = readFileSync(new URL('./pesoPedidos.js', import.meta.url), 'utf8').replace(/\/\/.*$/gm, '');
  assert.doesNotMatch(fonte, /capacidade|capacity|bloque|solver|referencia|fetch\(|axios|localStorage|sessionStorage|console\./i);
  // as funções só devolvem números e textos; não existe nenhuma que devolva aviso, erro ou gravidade
  assert.doesNotMatch(fonte, /gravidade|alert\(|confirm\(/);
});
