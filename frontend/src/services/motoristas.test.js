import test from 'node:test';
import assert from 'node:assert/strict';
import {
  validarTelefone, mascararTelefone, formatarTelefone, textoDeBuscaDoMotorista, casaComABusca, filtrarMotoristasDaTela, paginar,
  resumoDasLojas, motoristasDaLoja, agruparParaRoteirizacao, avisoDeLimite, POR_PAGINA, LIMITE_DA_LISTA,
  MSG_TELEFONE_INVALIDO, MSG_TELEFONE_SEM_DDD,
} from './motoristas.js';

const L1 = { id: 1, nome: 'Atacadão Guarujá', ativo: true };
const L2 = { id: 2, nome: 'Atacadão Campinas', ativo: true };
const M = (id, nome, codigo, extra = {}) => ({ id, nome, codigo, tipo_veiculo: 'Carro de passeio', ativo: true, lojas: [], ...extra });

// ------------------------------------------------------------------------------------------ telefone
test('telefone válido vira só dígitos (parênteses, traços, espaços, +55 e 0 do DDD)', () => {
  const casos = [
    ['(11) 91234-5678', '11912345678'], ['11 91234 5678', '11912345678'], ['11912345678', '11912345678'],
    ['+55 11 91234-5678', '11912345678'], ['55 (11) 91234-5678', '11912345678'], ['011 91234-5678', '11912345678'],
    ['(11) 3123-4567', '1131234567'], ['+55 (21) 2123-4567', '2121234567'], ['11.91234.5678', '11912345678'],
  ];
  for (const [entrada, esperado] of casos) {
    const r = validarTelefone(entrada);
    assert.equal(r.ok, true, entrada);
    assert.equal(r.digitos, esperado, entrada);
  }
});

test('telefone em branco é válido (é opcional)', () => {
  for (const vazio of ['', '   ', null, undefined]) {
    const r = validarTelefone(vazio);
    assert.deepEqual([r.ok, r.vazio, r.digitos, r.mensagem], [true, true, '', '']);
  }
});

test('telefone inválido ou sem DDD é recusado, sem repetir o número na mensagem', () => {
  for (const entrada of ['123', '(11) 1234-5678', '(11) 91234-567', '(00) 91234-5678', '(11) 81234-5678', 'abc', '11 9123x-5678', '1191234567890123']) {
    const r = validarTelefone(entrada);
    assert.equal(r.ok, false, entrada);
    assert.equal(r.mensagem, MSG_TELEFONE_INVALIDO, entrada);
    assert.equal(r.mensagem.includes(entrada), false);
  }
  for (const entrada of ['91234-5678', '3123-4567', '991234567']) {
    const r = validarTelefone(entrada);
    assert.equal(r.ok, false, entrada);
    assert.equal(r.mensagem, MSG_TELEFONE_SEM_DDD, entrada);
  }
});

test('telefone mascarado nas listas e formatado só na edição', () => {
  assert.equal(mascararTelefone('11912345678'), '(11) *****-5678');
  assert.equal(mascararTelefone('1131234567'), '(11) ****-4567');
  assert.equal(mascararTelefone(''), '');
  assert.equal(mascararTelefone(null), '');
  assert.equal(mascararTelefone('123'), '');
  assert.equal(formatarTelefone('11912345678'), '(11) 91234-5678');
  assert.equal(formatarTelefone('1131234567'), '(11) 3123-4567');
  assert.equal(formatarTelefone(null), '');
});

// ------------------------------------------------------------------------------------------ busca
test('busca por nome ou código sem acentos, maiúsculas, espaços nem traços', () => {
  const joao = M(1, 'João Silva', 'MOT-0001');
  for (const busca of ['joao', 'JOÃO', '  joao   silva ', 'joaosilva', 'silva joao', 'mot-0001', 'mot 0001', 'MOT0001', '0001', 'mot']) {
    assert.equal(casaComABusca(joao, busca), true, busca);
  }
  for (const busca of ['maria', 'mot-0002', '0002', 'joao pedro']) {
    assert.equal(casaComABusca(joao, busca), false, busca);
  }
  assert.equal(casaComABusca(joao, ''), true);
  assert.equal(casaComABusca(joao, '---'), false);
  assert.equal(casaComABusca(M(2, 'Sem Código', null), 'sem'), true);
  assert.match(textoDeBuscaDoMotorista(joao), /joao silva mot-0001 mot0001 joaosilva/);
});

test('a busca nunca olha o telefone', () => {
  const m = { ...M(1, 'Ana', 'MOT-1'), telefone: '11912345678', telefone_mascarado: '(11) *****-5678' };
  assert.equal(casaComABusca(m, '5678'), false);
  assert.equal(casaComABusca(m, '91234'), false);
});

// ------------------------------------------------------------------------------------------ filtros
const LISTA = [
  M(1, 'Ana', 'MOT-0001', { lojas: [L1] }),
  M(2, 'Beto', 'MOT-0002', { tipo_veiculo: 'Fiorino/Utilitário', lojas: [L1, L2] }),
  M(3, 'Carla', 'MOT-0003', { ativo: false, lojas: [L2] }),
  M(4, 'Davi', 'MOT-0004'),
];
const ids = (l) => l.map((m) => m.id);

test('filtros por tipo, loja e situação', () => {
  assert.deepEqual(ids(filtrarMotoristasDaTela(LISTA, {})), [1, 2, 3, 4]);
  assert.deepEqual(ids(filtrarMotoristasDaTela(LISTA, { tipo: 'Fiorino/Utilitário' })), [2]);
  assert.deepEqual(ids(filtrarMotoristasDaTela(LISTA, { lojaId: '1' })), [1, 2]);
  assert.deepEqual(ids(filtrarMotoristasDaTela(LISTA, { lojaId: 2 })), [2, 3]);
  assert.deepEqual(ids(filtrarMotoristasDaTela(LISTA, { situacao: 'ativos' })), [1, 2, 4]);
  assert.deepEqual(ids(filtrarMotoristasDaTela(LISTA, { situacao: 'desativados' })), [3]);
  assert.deepEqual(ids(filtrarMotoristasDaTela(LISTA, { busca: 'mot-0002', lojaId: '1', situacao: 'ativos' })), [2]);
  assert.deepEqual(ids(filtrarMotoristasDaTela(LISTA, { busca: 'carla', situacao: 'ativos' })), []);
  assert.deepEqual(ids(filtrarMotoristasDaTela(null, {})), []);
});

test('paginação de 50 em 50, com a página ajustada ao que existe', () => {
  const lista = Array.from({ length: 120 }, (_, i) => i + 1);
  const p1 = paginar(lista, 1);
  assert.deepEqual([p1.itens.length, p1.pagina, p1.totalPaginas, p1.total, p1.de, p1.ate], [POR_PAGINA, 1, 3, 120, 1, 50]);
  const p3 = paginar(lista, 3);
  assert.deepEqual([p3.itens.length, p3.de, p3.ate, p3.itens[0]], [20, 101, 120, 101]);
  assert.equal(paginar(lista, 99).pagina, 3);
  assert.equal(paginar(lista, 0).pagina, 1);
  assert.equal(paginar(lista, 'x').pagina, 1);
  const vazia = paginar([], 1);
  assert.deepEqual([vazia.itens.length, vazia.totalPaginas, vazia.de, vazia.ate], [0, 1, 0, 0]);
});

test('resumo das lojas da linha: as primeiras e "+N"', () => {
  assert.equal(resumoDasLojas([]), '');
  assert.equal(resumoDasLojas([L1]), 'Atacadão Guarujá');
  assert.equal(resumoDasLojas([L1, L2]), 'Atacadão Guarujá, Atacadão Campinas');
  assert.equal(resumoDasLojas([L1, L2, { id: 3, nome: 'C' }, { id: 4, nome: 'D' }]), 'Atacadão Guarujá, Atacadão Campinas +2');
});

// ------------------------------------------------------------------------------------------ roteirização
test('"Desta loja" primeiro e "Outros motoristas" depois; desativados nunca entram', () => {
  const r = agruparParaRoteirizacao(LISTA, 1, '');
  assert.deepEqual(r.grupos.map((g) => [g.titulo, ids(g.itens)]), [['Desta loja', [1, 2]], ['Outros motoristas', [4]]]);
  assert.deepEqual([r.total, r.mostrados, r.cortados], [3, 3, 0]);
  assert.deepEqual(ids(motoristasDaLoja(LISTA, 2)), [2]); // a Carla (desativada) não conta
  assert.deepEqual(motoristasDaLoja(LISTA, null), []);
});

test('a busca alcança os motoristas das outras lojas e respeita os grupos', () => {
  const r = agruparParaRoteirizacao(LISTA, 1, 'davi');
  assert.deepEqual(r.grupos.map((g) => [g.chave, ids(g.itens)]), [['outros', [4]]]);
  const porCodigo = agruparParaRoteirizacao(LISTA, 1, 'mot 0002');
  assert.deepEqual(porCodigo.grupos.map((g) => [g.chave, ids(g.itens)]), [['loja', [2]]]);
});

test('sem loja escolhida a lista é um grupo só', () => {
  for (const sem of [null, undefined, '']) {
    const r = agruparParaRoteirizacao(LISTA, sem, '');
    assert.deepEqual(r.grupos.map((g) => [g.chave, ids(g.itens)]), [['todos', [1, 2, 4]]]);
  }
});

test('a lista é limitada e o aviso diz quantos faltam (loja primeiro)', () => {
  const muitos = Array.from({ length: 500 }, (_, i) => M(i + 1, `Motorista ${i}`, `MOT-${String(i + 1).padStart(4, '0')}`, { lojas: i < 70 ? [L1] : [] }));
  const r = agruparParaRoteirizacao(muitos, 1, '');
  assert.deepEqual([r.total, r.mostrados, r.cortados], [500, LIMITE_DA_LISTA, 440]);
  assert.deepEqual(r.grupos.map((g) => [g.chave, g.itens.length]), [['loja', 60]]); // o limite gasta primeiro com a loja
  assert.equal(avisoDeLimite(r), 'Mostrando 60 de 500. Digite para refinar.');
  assert.equal(avisoDeLimite({ mostrados: 3, total: 3 }), '');
  const pequeno = agruparParaRoteirizacao(muitos, 1, 'motorista 3', 10);
  assert.equal(pequeno.mostrados <= 10, true);
});

test('desempenho: filtro, busca e agrupamento de 500 motoristas em poucos milissegundos', () => {
  const muitos = Array.from({ length: 500 }, (_, i) => M(i + 1, `Motorista ${i} Çãõ`, `MOT-${String(i + 1).padStart(4, '0')}`, { lojas: i % 5 === 0 ? [L1] : [L2] }));
  const inicio = performance.now();
  for (let i = 0; i < 100; i += 1) {
    filtrarMotoristasDaTela(muitos, { busca: 'motorista 49', lojaId: '1', situacao: 'ativos' });
    agruparParaRoteirizacao(muitos, 1, `mot ${i}`);
  }
  assert.ok(performance.now() - inicio < 2000, 'deveria levar bem menos que 2 segundos para 100 rodadas');
});
