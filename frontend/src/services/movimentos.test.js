import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  enderecoCurto, paradasDaRota, opcoesDeDestino, textoDoMovimento, corpoDoMovimento, erroDoMovimento, MSG_MOVER_TRAVADO, MSG_FALHA_AO_MOVER,
} from './movimentos.js';
import {
  rotasEfetivas, rotasComPedidos, rotaVazia, quantasMovidas, quantasAjustadas, corpoDaConfirmacao, avisosDoDespacho, linhasDoCartao,
} from './despacho.js';
import { relatorioDeJanelas } from './janelas.js';
import { linhasDoRomaneio } from './romaneio.js';
import { indexarItens, pesoPorViagem, pesoPorMotorista, pesoPorTipoDeVeiculo } from './pesoPedidos.js';

const CARRO = 'Carro de passeio';
const UTIL = 'Fiorino/Utilitário';
const mot = (id, nome, tipo = CARRO) => ({ id, nome, tipo_veiculo: tipo, codigo: `MOT-000${id}`, ativo: true, lojas: [] });
const ANA = mot(1, 'Ana');
const BETO = mot(2, 'Beto', UTIL);
const CAIO = mot(3, 'Caio');
const MOTORISTAS = [ANA, BETO, CAIO];
const LOJA = { janela_manha_inicio: '08:00', janela_manha_fim: '13:00', janela_tarde_inicio: '13:00', janela_tarde_fim: '18:00' };

const parada = (id, ordem) => ({ id, ordem, Endereco: `Rua ${id}`, Numero: '10', Bairro: 'Centro', CEP: '01310100', Volume: 1, lat: -23.5, lon: -46.6 });
const rota = (id, motorista, paradas, extra = {}) => ({
  id, motorista_id: motorista.id, motorista_base: motorista.nome, motorista: motorista.nome, viagem_num: 1, modal: motorista.tipo_veiculo, cor: '#fff',
  qtd_pedidos: paradas.length, km_total: 5 * paradas.length, paradas, setores: paradas.length ? ['N'] : [], violacoes_rotacao: [], teto_recomendado: 5,
  tempos_trechos_s: paradas.length ? [...paradas.map(() => 600), 600] : [], distancias_trechos_km: paradas.length ? [...paradas.map(() => 2), 2] : [],
  tempo_deslocamento_min: paradas.length ? (paradas.length + 1) * 10 : 0, ...extra,
});

// Como o servidor devolve depois de mover P3 (da 2ª viagem da Ana) para a 1ª viagem dela: a rota 2 fica vazia e a Ana passa a ter uma viagem só.
const DEPOIS = [
  rota(1, ANA, [parada('P1', 1), parada('P3', 2), parada('P2', 3)], { movida: true }),
  rota(2, ANA, [], { viagem_num: 2, movida: true }),
  rota(3, BETO, [parada('P4', 1)]),
];
const PEDIDOS = [{ id: 'P1', cliente: 'Maria' }, { id: 'P2', cliente: 'João', janela_inicio: '08:00', janela_fim: '08:05' }, { id: 'P3', cliente: 'Zé' }, { id: 'P4', cliente: 'Lia' }];

test('rota vazia: fica na matriz, mas fora do resto da tela', () => {
  assert.equal(rotaVazia(DEPOIS[1]), true);
  assert.equal(rotaVazia(DEPOIS[0]), false);
  assert.equal(rotaVazia({ id: 9, qtd_pedidos: 3 }), false); // rota sem a lista de paradas (formato antigo dos testes) não é vazia
  assert.deepEqual(rotasComPedidos(DEPOIS).map((r) => r.id), [1, 3]);
  assert.equal(quantasMovidas(DEPOIS), 2);
  assert.equal(quantasAjustadas(DEPOIS), 0);
});

test('trocar o motorista depois de mover: a rota vazia não conta viagem nem ganha "Viagem N"', () => {
  // Caio assume a rota 3 (do Beto) e a rota 2 (vazia): as viagens dele contam só a rota com pedidos.
  const efetivas = rotasEfetivas(DEPOIS, { 3: 3, 2: 3 }, MOTORISTAS);
  const porId = Object.fromEntries(efetivas.map((r) => [r.id, r]));
  assert.equal(porId[3].motorista, 'Caio');
  assert.equal(porId[3].viagem_num, 1);
  assert.equal(porId[2].motorista, 'Caio');
  assert.equal(porId[1].motorista, 'Ana');
  // o confirmar não leva a troca da rota vazia (ela não é confirmada) e leva a versão
  assert.deepEqual(corpoDaConfirmacao('exec-1', DEPOIS, { 3: 3, 2: 3 }, MOTORISTAS, 4), { execucao_id: 'exec-1', atribuicoes: { 3: 3 }, versao: 4 });
  assert.deepEqual(corpoDaConfirmacao('exec-1', DEPOIS, {}, MOTORISTAS), { execucao_id: 'exec-1' });
  assert.deepEqual(corpoDaConfirmacao('exec-1', DEPOIS, {}, MOTORISTAS, undefined), { execucao_id: 'exec-1' });
});

test('avisos: teto e carga desigual também avisam depois de mover (nunca bloqueiam; o peso não entra)', () => {
  const usadas = rotasComPedidos(rotasEfetivas(DEPOIS, {}, MOTORISTAS));
  const avisos = avisosDoDespacho({ avisosDoSolver: [], rotas: usadas, rotacao: null, capacidades: { [CARRO]: 2, [UTIL]: 10 }, marcados: [ANA, BETO], limitesKm: null });
  assert.ok(avisos.some((a) => a.tipo === 'teto_da_troca' && a.mensagem.startsWith('Rota 1:')));
  assert.ok(!avisos.some((a) => /Rota 2/.test(a.mensagem))); // a rota vazia não aparece
  assert.ok(!avisos.some((a) => /kg|peso/i.test(a.mensagem)));
  const semMover = avisosDoDespacho({ avisosDoSolver: [], rotas: usadas.map((r) => ({ ...r, movida: false })), rotacao: null, capacidades: { [CARRO]: 2 }, marcados: [ANA, BETO] });
  assert.equal(semMover.length, 0);
});

test('cartão "Rotas por Motorista" segue a nova divisão', () => {
  const linhas = linhasDoCartao(rotasComPedidos(rotasEfetivas(DEPOIS, {}, MOTORISTAS)), [ANA, BETO, CAIO]);
  assert.deepEqual(linhas.map((l) => [l.nome, l.rotas, l.pedidos]), [['Ana', 1, 3], ['Beto', 1, 1], ['Caio', 0, 0]]);
});

test('janelas: as chegadas seguem a nova ordem e a rota vazia não entra', () => {
  const rotas = rotasComPedidos(rotasEfetivas(DEPOIS, {}, MOTORISTAS));
  const relatorio = relatorioDeJanelas({ rotas, pedidos: PEDIDOS, loja: LOJA, turno: 'manha', tempoPorParada: 10 });
  assert.equal(relatorio.totalPedidos, 4);
  assert.deepEqual(relatorio.porParada[1].map((p) => [p.pedidoId, p.horaTexto]), [['P1', '08:10'], ['P3', '08:30'], ['P2', '08:50']]);
  assert.equal(relatorio.porParada[2], undefined);
  assert.equal(relatorio.foraDoPrazo, 1); // P2 agora chega às 08:50, depois do fim da janela dele (08:05)
});

test('peso por viagem, motorista e tipo segue a nova divisão', () => {
  const itens = indexarItens([{ id_pedido: 'P1', sku: 'A', quantidade: 1 }, { id_pedido: 'P3', sku: 'A', quantidade: 2 }, { id_pedido: 'P4', sku: 'A', quantidade: 1 }]);
  const pesos = { A: { peso_kg: 2, confianca: 'alta' } };
  const rotas = rotasComPedidos(rotasEfetivas(DEPOIS, {}, MOTORISTAS));
  const viagens = pesoPorViagem(rotas, itens, pesos);
  assert.equal(viagens[1].kg, 6);
  assert.equal(viagens[2], undefined);
  assert.deepEqual(pesoPorMotorista(rotas, itens, pesos).map((m) => [m.nome, m.viagens, m.pedidos, m.total.kg]), [['Ana', 1, 3, 6], ['Beto', 1, 1, 2]]);
  assert.deepEqual(pesoPorTipoDeVeiculo(rotas, itens, pesos).map((t) => [t.nome, t.viagens]), [[CARRO, 1], [UTIL, 1]]);
});

test('romaneio: uma linha por parada na nova ordem, sem a rota vazia', () => {
  const rotas = rotasComPedidos(rotasEfetivas(DEPOIS, {}, MOTORISTAS));
  const relatorio = relatorioDeJanelas({ rotas, pedidos: PEDIDOS, loja: LOJA, turno: 'manha', tempoPorParada: 10 });
  const linhas = linhasDoRomaneio({ rotas, pedidos: PEDIDOS, relatorio, loja: LOJA, turno: 'manha' });
  assert.deepEqual(linhas.map((l) => [l[0], l[1], l[2], l[4], l[10]]), [
    ['Rota 1', '"Ana"', 'Viagem 1', 1, '"P1"'], ['Rota 1', '"Ana"', 'Viagem 1', 2, '"P3"'], ['Rota 1', '"Ana"', 'Viagem 1', 3, '"P2"'], ['Rota 3', '"Beto"', 'Viagem 1', 1, '"P4"'],
  ]);
});

test('paradas da rota e endereço curto, sem cliente', () => {
  assert.equal(enderecoCurto({ Endereco: 'Rua A', Numero: '10', Bairro: 'Centro', Cliente: 'Fulano' }), 'Rua A, 10 - Centro');
  assert.equal(enderecoCurto({ Endereco: 'Rua A' }), 'Rua A');
  assert.equal(enderecoCurto({ Bairro: 'Centro' }), 'Centro');
  assert.equal(enderecoCurto(null), '');
  assert.deepEqual(paradasDaRota(DEPOIS[0]), [{ ordem: 1, id: 'P1', endereco: 'Rua P1, 10 - Centro' }, { ordem: 2, id: 'P3', endereco: 'Rua P3, 10 - Centro' }, { ordem: 3, id: 'P2', endereco: 'Rua P2, 10 - Centro' }]);
  assert.deepEqual(paradasDaRota({}), []);
});

test('opções de destino: as outras rotas, inclusive vazias e outra viagem do mesmo motorista, com pesquisa', () => {
  const rotas = rotasEfetivas(DEPOIS, {}, MOTORISTAS);
  const opcoes = opcoesDeDestino(rotas, 3);
  assert.deepEqual(opcoes.map((o) => [o.id, o.titulo, o.detalhe, o.vazia]), [
    [1, 'Rota 1 · Ana', '3 pedidos · 15,0 km', false], [2, 'Rota 2 · Ana', 'sem pedidos', true],
  ]);
  assert.deepEqual(opcoesDeDestino(rotas, 1).map((o) => o.id), [2, 3]);
  assert.deepEqual(opcoesDeDestino(rotas, 1, 'beto').map((o) => o.id), [3]);
  assert.deepEqual(opcoesDeDestino(rotas, 1, 'rota 2').map((o) => o.id), [2]);
});

test('resumo do movimento em linguagem do operador (só números de rota, pedidos e km)', () => {
  const texto = textoDoMovimento({ rota_origem: 2, rota_destino: 1, antes: { 1: { qtd_pedidos: 2, km_total: 12.4 }, 2: { qtd_pedidos: 1, km_total: 8 } }, depois: { 1: { qtd_pedidos: 3, km_total: 15.06 }, 2: { qtd_pedidos: 0, km_total: 0 } } });
  assert.equal(texto, 'Pedido movido da Rota 2 para a Rota 1. Rota 2: 1 → 0 pedidos, 8,0 → 0,0 km; Rota 1: 2 → 3 pedidos, 12,4 → 15,1 km.');
  assert.equal(textoDoMovimento(null), '');
});

test('corpo do movimento leva só id, rota e versão', () => {
  assert.deepEqual(corpoDoMovimento(123, '2', 5), { pedido_id: '123', rota_destino: 2, versao: 5 });
  assert.deepEqual(corpoDoMovimento('A', 2, undefined), { pedido_id: 'A', rota_destino: 2, versao: null });
});

test('erros do movimento: mensagem do servidor, recarregar só quando outra aba mudou a divisão', () => {
  const erro = (status, detail) => ({ response: { status, data: { detail } } });
  assert.deepEqual(erroDoMovimento(erro(409, 'As rotas foram alteradas em outra aba ou janela. Atualizei a tela com a divisão atual.')).recarregar, true);
  assert.deepEqual(erroDoMovimento(erro(409, MSG_MOVER_TRAVADO)), { mensagem: MSG_MOVER_TRAVADO, recarregar: false, expirado: false });
  const expirado = erroDoMovimento(erro(404, 'Este resultado não está mais disponível. Gere as rotas de novo.'));
  assert.equal(expirado.mensagem, 'Este resultado não está mais disponível. Gere as rotas de novo.');
  assert.equal(expirado.expirado, true);
  assert.equal(erroDoMovimento(new Error('rede')).mensagem, MSG_FALHA_AO_MOVER);
});

test('tela: "Mover para…" trava depois de confirmar e não mostra cliente', () => {
  const seletor = readFileSync(new URL('../components/SeletorRotaDestino.jsx', import.meta.url), 'utf8');
  assert.match(seletor, /disabled=\{desabilitado\}/);
  assert.ok(!/cliente/i.test(seletor.replace(/Nada de cliente aqui\./, '')));
  const app = readFileSync(new URL('../App.jsx', import.meta.url), 'utf8');
  assert.match(app, /desabilitado=\{confirmacao\.confirmada \|\| movimento\.enviando\}/);
  assert.match(app, /MSG_MOVER_TRAVADO/);
  assert.match(app, /rotas=\{resultado \? rotasUsadas : \[\]\}/); // o mapa não desenha a rota vazia
  const servico = readFileSync(new URL('./movimentos.js', import.meta.url), 'utf8');
  assert.ok(!/\.cliente|Cliente\b(?!\.)/.test(servico.replace(/Sem cliente aqui|Nunca o cliente|nada de endereço nem cliente/g, '')));
});
