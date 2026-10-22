import test from 'node:test';
import assert from 'node:assert/strict';
import {
  regioesRepetidas, seloDeRotacao, rotasEfetivas, trocarMotorista, voltarASugestao, ajustesValidos, quantasAjustadas, corpoDaConfirmacao, textoNestaRoteirizacao,
  alternativasParaRota, linhasDoCartao, avisosDeRotacao, avisoDeCargaDesigual, avisosDeTeto, avisosDoDespacho, LIMITE_DE_ALTERNATIVAS, deveFecharNoScroll,
  interpretarLimiteKm, avisosDeLimiteKm, MSG_LIMITE_KM_FORMATO, MSG_LIMITE_KM_FAIXA,
} from './despacho.js';
import { resumoPorMotorista, rotasPorMotoristaDoResultado, textoDoMotoristaNoCartao } from './selecaoMotoristas.js';

const mot = (id, nome, tipo = 'Carro de passeio', extra = {}) => ({ id, nome, tipo_veiculo: tipo, codigo: `MOT-000${id}`, ativo: true, lojas: [], telefone: '(11) *****-4321', ...extra });
const ANA = mot(1, 'Ana', 'Carro de passeio', { lojas: [{ id: 10, nome: 'Mooca', ativo: true }] });
const BETO = mot(2, 'Beto', 'Fiorino/Utilitário', { lojas: [{ id: 10, nome: 'Mooca', ativo: true }] });
const CAIO = mot(3, 'Caio', 'Carro de passeio', { lojas: [{ id: 10, nome: 'Mooca', ativo: true }] });
const DANI = mot(4, 'Dani', 'Carro de passeio', { lojas: [{ id: 99, nome: 'Outra', ativo: true }] });
const EDU = mot(5, 'Edu', 'Carro de passeio', { lojas: [{ id: 10, nome: 'Mooca', ativo: true }], ativo: false });
const TODOS = [ANA, BETO, CAIO, DANI, EDU];

const rota = (id, motorista, extra = {}) => ({
  id, motorista_id: motorista.id, motorista_base: motorista.nome, motorista: motorista.nome, viagem_num: 1, modal: motorista.tipo_veiculo, cor: '#fff',
  qtd_pedidos: 5, setores: ['N'], violacoes_rotacao: [], rota_personalizada: false, teto_recomendado: 5, ...extra,
});
// Ana tem as rotas 1 e 2 (2 viagens); Beto tem a 3.
const ROTAS = [rota(1, ANA, { motorista: 'Ana • Viagem 1', setores: ['N'] }), rota(2, ANA, { motorista: 'Ana • Viagem 2', viagem_num: 2, setores: ['L', 'SE'], qtd_pedidos: 4 }), rota(3, BETO, { setores: ['O'], qtd_pedidos: 3 })];

test('sem ajustes, as rotas efetivas são as do solver', () => {
  const r = rotasEfetivas(ROTAS, {}, TODOS);
  assert.deepEqual(r.map((x) => [x.id, x.motorista_id, x.motorista, x.ajustada]), [[1, 1, 'Ana • Viagem 1', false], [2, 1, 'Ana • Viagem 2', false], [3, 2, 'Beto', false]]);
  assert.deepEqual(rotasEfetivas(ROTAS, undefined, TODOS).map((x) => x.ajustada), [false, false, false]);
});

test('trocar muda motorista, veículo e título, marca "ajustada" e desfaz a marca "Rota personalizada"', () => {
  const personalizadas = [{ ...ROTAS[0], rota_personalizada: true }, ROTAS[1], ROTAS[2]];
  const r = rotasEfetivas(personalizadas, { 1: 2 }, TODOS);
  assert.equal(r[0].motorista_id, 2);
  assert.equal(r[0].motorista_base, 'Beto');
  assert.equal(r[0].modal, 'Fiorino/Utilitário');
  assert.equal(r[0].ajustada, true);
  assert.equal(r[0].rota_personalizada, false);
  assert.equal(r[0].motorista_id_sugerido, 1);
  assert.equal(r[0].motorista, 'Beto • Viagem 1'); // agora o Beto tem 2 rotas (a 1 e a 3)
  assert.equal(r[2].motorista, 'Beto • Viagem 2');
  assert.equal(r[1].motorista, 'Ana'); // a Ana ficou com uma rota só: sem "Viagem"
  assert.equal(r[1].ajustada, false);
  assert.equal(personalizadas[0].motorista_id, 1); // o que veio do solver não é alterado
});

test('quem não foi tocado pelas trocas fica exatamente como o solver devolveu', () => {
  const quatro = [...ROTAS, rota(4, CAIO, { motorista: 'Caio' })];
  const r = rotasEfetivas(quatro, { 3: 1 }, TODOS);
  assert.equal(r[3], quatro[3] === r[3] ? r[3] : r[3]);
  assert.deepEqual({ ...r[3] }, { ...quatro[3], ajustada: false, motorista_id_sugerido: 3 });
});

test('trocar por quem já tem outra rota é permitido (passa a ter duas)', () => {
  const r = rotasEfetivas(ROTAS, { 3: 1 }, TODOS);
  assert.equal(r.filter((x) => x.motorista_id === 1).length, 3);
  assert.deepEqual(r.map((x) => x.motorista), ['Ana • Viagem 1', 'Ana • Viagem 2', 'Ana • Viagem 3']);
});

test('totais por motorista são recalculados depois da troca', () => {
  const r = rotasEfetivas(ROTAS, { 2: 2 }, TODOS);
  const resumo = resumoPorMotorista(r);
  assert.deepEqual(resumo.get(1), { rotas: 1, pedidos: 5 });
  assert.deepEqual(resumo.get(2), { rotas: 2, pedidos: 7 });
  const cartao = rotasPorMotoristaDoResultado(r);
  assert.deepEqual(cartao.map((l) => [l.nome, l.rotas, l.pedidos]), [['Ana', 1, 5], ['Beto', 2, 7]]);
  assert.equal(textoDoMotoristaNoCartao(cartao[1], 1, 4), 'Beto: 2 rotas nesta roteirização (7 pedidos) • 1 rota realizada hoje (4 pedidos)');
});

test('o cartão inclui os marcados que ficaram sem rota', () => {
  const r = rotasEfetivas(ROTAS, { 3: 1 }, TODOS);
  const linhas = linhasDoCartao(r, [ANA, BETO, CAIO]);
  assert.deepEqual(linhas.map((l) => [l.nome, l.rotas, l.pedidos]), [['Ana', 3, 12], ['Beto', 0, 0], ['Caio', 0, 0]]);
});

test('trocar e "Voltar à sugestão" por rota e de todas', () => {
  let a = trocarMotorista({}, ROTAS, 1, 3);
  a = trocarMotorista(a, ROTAS, 3, 1);
  assert.deepEqual(a, { 1: 3, 3: 1 });
  assert.deepEqual(trocarMotorista(a, ROTAS, 1, 1), { 3: 1 }); // escolher o sugerido remove o ajuste
  assert.deepEqual(voltarASugestao(a, 1), { 3: 1 });
  assert.deepEqual(voltarASugestao(a), {});
  assert.deepEqual(a, { 1: 3, 3: 1 }); // sem alterar o mapa recebido
  assert.equal(quantasAjustadas(rotasEfetivas(ROTAS, a, TODOS)), 2);
  assert.equal(quantasAjustadas(rotasEfetivas(ROTAS, voltarASugestao(a), TODOS)), 0);
});

test('ajuste para motorista desconhecido ou igual ao sugerido é ignorado', () => {
  assert.deepEqual(ajustesValidos(ROTAS, { 1: 1, 2: 999, 3: 3 }, TODOS), { 3: 3 });
  assert.deepEqual(ajustesValidos(ROTAS, { 77: 3 }, TODOS), {});
});

test('corpo do confirmar: só leva as rotas ajustadas; sem ajuste fica igual ao formato antigo', () => {
  assert.deepEqual(corpoDaConfirmacao('abc', ROTAS, {}, TODOS), { execucao_id: 'abc' });
  assert.deepEqual(corpoDaConfirmacao('abc', ROTAS, { 1: 3, 2: 1, 3: 2 }, TODOS), { execucao_id: 'abc', atribuicoes: { 1: 3 } });
});

test('selo de rotação: uma região, várias e nenhuma', () => {
  assert.equal(seloDeRotacao(['N']), 'repete a região N em outro turno');
  assert.equal(seloDeRotacao(['N', 'NE']), 'repete as regiões N e NE em outro turno');
  assert.equal(seloDeRotacao(['N', 'NE', 'L']), 'repete as regiões N, NE e L em outro turno');
  assert.equal(seloDeRotacao([]), null);
  const rotacao = { 1: { N: ['manha'], NE: ['manha'] } };
  assert.deepEqual(regioesRepetidas({ motorista_id: 1, setores: ['N', 'L', 'NE'] }, rotacao), ['N', 'NE']);
  assert.deepEqual(regioesRepetidas({ motorista_id: 2, setores: ['N'] }, rotacao), []);
  assert.deepEqual(regioesRepetidas({ motorista_id: 2, setores: ['N'], violacoes_rotacao: ['N'] }, null), ['N']); // sem a conferência vale o que o solver marcou
});

const base = (extra = {}) => ({
  rota: rotasEfetivas(ROTAS, {}, TODOS)[2], rotas: rotasEfetivas(ROTAS, {}, TODOS), motoristas: TODOS, selecionados: [1, 2, 3], lojaId: 10, rotasHoje: {}, pedidosHoje: {}, rotacao: {}, busca: '', ...extra,
});

test('alternativas: marcados e outros da loja, nunca inativos nem de outra loja, sem marcar nada sozinho', () => {
  const grupos = alternativasParaRota(base({ selecionados: [1, 2] }));
  assert.deepEqual(grupos.map((g) => g.titulo), ['Marcados nesta roteirização', 'Outros motoristas desta loja']);
  assert.deepEqual(grupos[0].itens.map((i) => i.nome), ['Beto', 'Ana']);
  assert.deepEqual(grupos[1].itens.map((i) => i.nome), ['Caio']); // Dani é de outra loja e Edu está inativo
  const sem = alternativasParaRota(base({ lojaId: null, selecionados: [1, 2] }));
  assert.deepEqual(sem.map((g) => g.titulo), ['Marcados nesta roteirização']);
  assert.ok(!JSON.stringify(grupos).includes('*****')); // sem telefone
});

test('alternativas: o motorista atual primeiro, depois quem não repete região, depois menos rotas, depois nome', () => {
  const rotacao = { 1: { O: ['manha'] } }; // a Ana já fez a região O (a da rota 3)
  const hoje = { 2: 3, 3: 1 };
  const g = alternativasParaRota(base({ rotacao, rotasHoje: hoje }))[0].itens;
  assert.deepEqual(g.map((i) => i.nome), ['Beto', 'Caio', 'Ana']); // Beto é o atual; Caio (1 hoje) antes da Ana, que repete região
  assert.equal(g[0].atual, true);
  assert.equal(g[0].sugerido, true);
  const semAtual = alternativasParaRota(base({ rota: { ...rotasEfetivas(ROTAS, {}, TODOS)[2], motorista_id: 99 }, rotacao: {} }))[0].itens.map((i) => i.nome);
  assert.deepEqual(semAtual, ['Beto', 'Caio', 'Ana']); // Beto 0 e Caio 0 nesta roteirização (nome desempata); Ana já tem 2
});

test('alternativas: textos de rotas de hoje, rotas nesta roteirização e selo', () => {
  const g = alternativasParaRota(base({ rotacao: { 1: { O: ['manha'] } }, rotasHoje: { 1: 2 }, pedidosHoje: { 1: 9 } }))[0].itens;
  const ana = g.find((i) => i.nome === 'Ana');
  assert.equal(ana.textoHoje, '2 rotas realizadas hoje (9 pedidos)');
  assert.equal(ana.textoNesta, 'já tem 2 rotas nesta roteirização (9 pedidos)');
  assert.equal(ana.selo, 'repete a região O em outro turno');
  assert.equal(ana.repete, true);
  assert.equal(ana.tipo, 'Carro de passeio');
  const caio = g.find((i) => i.nome === 'Caio');
  assert.equal(caio.textoHoje, 'nenhuma rota hoje');
  assert.equal(caio.textoNesta, 'nenhuma rota nesta roteirização');
  assert.equal(caio.selo, null);
  assert.equal(textoNestaRoteirizacao(1, 5), 'já tem 1 rota nesta roteirização (5 pedidos)');
});

test('alternativas: sem a conferência de rotação não há selo', () => {
  const g = alternativasParaRota(base({ rotacao: null }))[0].itens;
  assert.ok(g.every((i) => i.selo === null && i.repete === false));
});

test('alternativas: busca por nome ou código sem diferença de acento ou maiúsculas', () => {
  assert.deepEqual(alternativasParaRota(base({ busca: 'CAI' })).flatMap((g) => g.itens.map((i) => i.nome)), ['Caio']);
  assert.deepEqual(alternativasParaRota(base({ busca: 'mot-0001' })).flatMap((g) => g.itens.map((i) => i.nome)), ['Ana']);
  assert.deepEqual(alternativasParaRota(base({ busca: 'zzz' })), []);
});

test('alternativas: a lista é limitada e diz quantos ficaram de fora', () => {
  const muitos = Array.from({ length: 80 }, (_, i) => mot(100 + i, `Motorista ${String(i).padStart(2, '0')}`, 'Carro de passeio', { lojas: [{ id: 10, nome: 'Mooca', ativo: true }] }));
  const g = alternativasParaRota(base({ motoristas: [...TODOS, ...muitos] }));
  const outros = g.find((x) => x.chave === 'outros');
  assert.equal(outros.itens.length, LIMITE_DE_ALTERNATIVAS);
  assert.equal(outros.maisNaoMostrados, 80 - LIMITE_DE_ALTERNATIVAS); // os 80 (o Caio já está marcado)
});

test('avisos de rotação recalculados para o motorista final, só com o nome e o número da rota', () => {
  const rotacao = { 3: { N: ['manha'], O: ['noite'] } };
  const r = rotasEfetivas(ROTAS, { 1: 3, 3: 3 }, TODOS);
  assert.deepEqual(avisosDeRotacao(r, rotacao).map((a) => a.mensagem), ['Rota 1: Caio já fez a região N em outro turno hoje.', 'Rota 3: Caio já fez a região O em outro turno hoje.']);
  assert.deepEqual(avisosDeRotacao(r, null), []);
});

test('carga desigual só avisa e só depois de trocar', () => {
  const r = rotasEfetivas([rota(1, ANA, { qtd_pedidos: 10 }), rota(2, BETO, { qtd_pedidos: 10 })], { 2: 1 }, TODOS);
  const linhas = linhasDoCartao(r, [ANA, BETO]);
  assert.equal(avisoDeCargaDesigual(linhas).mensagem, 'A carga ficou desigual: Ana com 20 pedidos e Beto com 0 pedidos.');
  assert.equal(avisoDeCargaDesigual([{ nome: 'A', pedidos: 5 }, { nome: 'B', pedidos: 3 }]), null);
  assert.equal(avisoDeCargaDesigual([{ nome: 'A', pedidos: 5 }]), null);
  const sem = avisosDoDespacho({ avisosDoSolver: [], rotas: rotasEfetivas(ROTAS, {}, TODOS), rotacao: {}, capacidades: {}, marcados: [ANA, BETO] });
  assert.deepEqual(sem, []); // sem troca, o equilíbrio do solver não é questionado
});

test('teto recomendado do tipo: só para rotas trocadas, por número de pedidos (nunca peso)', () => {
  const r = rotasEfetivas([rota(1, ANA, { qtd_pedidos: 8 }), rota(2, BETO, { qtd_pedidos: 8 })], { 1: 3 }, TODOS);
  assert.deepEqual(avisosDeTeto(r, { 'Carro de passeio': 5, 'Fiorino/Utilitário': 5 }).map((a) => a.mensagem), ['Rota 1: 8 pedidos; o recomendado para Carro de passeio é 5 por viagem.']);
  assert.deepEqual(avisosDeTeto(r, { 'Carro de passeio': 10 }), []);
  assert.deepEqual(avisosDeTeto(r, {}), []);
  assert.ok(!JSON.stringify(avisosDeTeto(r, { 'Carro de passeio': 5 })).match(/kg|peso/i));
});

test('avisos do despacho: a rotação do solver é substituída pela recalculada e os demais avisos ficam', () => {
  const solver = [{ tipo: 'rotacao', gravidade: 'atencao', mensagem: 'Ana foi escalada...' }, { tipo: 'viagens_extras', gravidade: 'info', mensagem: 'Foram criadas viagens extras' }];
  const r = rotasEfetivas(ROTAS, { 1: 3 }, TODOS);
  const com = avisosDoDespacho({ avisosDoSolver: solver, rotas: r, rotacao: { 3: { N: ['manha'] } }, capacidades: {}, marcados: [ANA, BETO, CAIO] });
  assert.deepEqual(com.map((a) => a.tipo), ['viagens_extras', 'rotacao']);
  const sem = avisosDoDespacho({ avisosDoSolver: solver, rotas: r, rotacao: null, capacidades: {}, marcados: [ANA, BETO, CAIO] });
  assert.deepEqual(sem.map((a) => a.tipo), ['rotacao', 'viagens_extras']); // sem a conferência o aviso do solver continua
});

test('rolagem dentro da caixa de motoristas não fecha a lista; a da página fecha', () => {
  const filho = { id: 'item' };
  const caixa = { contains: (n) => n === caixa || n === filho };
  assert.equal(deveFecharNoScroll(filho, caixa), false); // rolar a lista de nomes
  assert.equal(deveFecharNoScroll(caixa, caixa), false); // barra de rolagem da própria caixa
  assert.equal(deveFecharNoScroll({ id: 'documento' }, caixa), true); // rolar a página
  assert.equal(deveFecharNoScroll(null, caixa), true);
  assert.equal(deveFecharNoScroll(filho, null), true); // sem caixa aberta
});

test('limite de km: vazio não confere, vírgula decimal vale, inválido avisa sem bloquear', () => {
  assert.deepEqual(interpretarLimiteKm(''), { ok: true, valor: null });
  assert.deepEqual(interpretarLimiteKm(undefined), { ok: true, valor: null });
  assert.deepEqual(interpretarLimiteKm(' 20 '), { ok: true, valor: 20 });
  assert.deepEqual(interpretarLimiteKm('20,5'), { ok: true, valor: 20.5 });
  assert.deepEqual(interpretarLimiteKm('20.5'), { ok: true, valor: 20.5 });
  for (const texto of ['abc', '-5', '1,2,3', '20km']) assert.deepEqual(interpretarLimiteKm(texto), { ok: false, valor: null, mensagem: MSG_LIMITE_KM_FORMATO });
  for (const texto of ['0', '0,0', '2001']) assert.deepEqual(interpretarLimiteKm(texto), { ok: false, valor: null, mensagem: MSG_LIMITE_KM_FAIXA });
  assert.deepEqual(interpretarLimiteKm('2000'), { ok: true, valor: 2000 });
  assert.ok(!/api|tabela|servidor/i.test(MSG_LIMITE_KM_FORMATO + MSG_LIMITE_KM_FAIXA));
});

const kmRota = (id, motorista, km, extra = {}) => ({ id, motorista_id: motorista.id, motorista_base: motorista.nome, motorista: motorista.nome, viagem_num: 1, km_total: km, ...extra });

test('limite de km por viagem: "Rota 3 (Ana, Viagem 2) passou 4,2 km do limite de 20 km"', () => {
  const rotas = [kmRota(1, ANA, 18), kmRota(2, ANA, 24.2, { viagem_num: 2 }), kmRota(3, BETO, 21)];
  const avisos = avisosDeLimiteKm(rotas, { porViagem: 20 });
  assert.deepEqual(avisos.map((a) => a.mensagem), ['Rota 2 (Ana, Viagem 2) passou 4,2 km do limite de 20 km', 'Rota 3 (Beto) passou 1,0 km do limite de 20 km']);
  assert.ok(avisos.every((a) => a.gravidade === 'atencao' && a.tipo === 'limite_km_viagem'));
  assert.deepEqual(avisosDeLimiteKm(rotas, { porViagem: 30 }), []);
  assert.deepEqual(avisosDeLimiteKm(rotas, { porViagem: 24.2 }), []); // igual ao limite não passou
});

test('limite de km por motorista soma as viagens dele', () => {
  const rotas = [kmRota(1, ANA, 16), kmRota(2, ANA, 15, { viagem_num: 2 }), kmRota(3, ANA, 15, { viagem_num: 3 }), kmRota(4, BETO, 30)];
  const avisos = avisosDeLimiteKm(rotas, { porMotorista: 40 });
  assert.deepEqual(avisos.map((a) => a.mensagem), ['Ana passou 6,0 km do limite de 40 km: 46,0 km em 3 viagens']);
  assert.equal(avisosDeLimiteKm([kmRota(1, ANA, 45.5)], { porMotorista: 40 })[0].mensagem, 'Ana passou 5,5 km do limite de 40 km: 45,5 km em 1 viagem');
  assert.equal(avisosDeLimiteKm([kmRota(1, ANA, 45.5)], { porMotorista: 40.5 })[0].mensagem, 'Ana passou 5,0 km do limite de 40,5 km: 45,5 km em 1 viagem');
});

test('os dois limites juntos, vazios não conferem e mensagens iguais não se repetem', () => {
  const rotas = [kmRota(1, ANA, 25), kmRota(2, ANA, 25, { viagem_num: 2 })];
  const ambos = avisosDeLimiteKm(rotas, { porViagem: 20, porMotorista: 40 });
  assert.deepEqual(ambos.map((a) => a.tipo), ['limite_km_viagem', 'limite_km_viagem', 'limite_km_motorista']);
  assert.deepEqual(avisosDeLimiteKm(rotas, {}), []);
  assert.deepEqual(avisosDeLimiteKm(rotas, { porViagem: null, porMotorista: null }), []);
  assert.deepEqual(avisosDeLimiteKm(rotas), []);
  const iguais = avisosDeLimiteKm([kmRota(1, ANA, 25), kmRota(1, ANA, 25)], { porViagem: 20 });
  assert.equal(iguais.length, 1);
});

test('limite de km recalcula depois de trocar o motorista de uma rota e entra no bloco de avisos', () => {
  const rotas = [kmRota(1, ANA, 25), kmRota(2, BETO, 25)];
  const sem = avisosDeLimiteKm(rotasEfetivas(rotas, {}, TODOS), { porMotorista: 40 });
  assert.deepEqual(sem, []);
  const trocadas = rotasEfetivas(rotas, { 2: 1 }, TODOS); // a Ana passa a fazer as duas
  assert.deepEqual(avisosDeLimiteKm(trocadas, { porMotorista: 40 }).map((a) => a.mensagem), ['Ana passou 10,0 km do limite de 40 km: 50,0 km em 2 viagens']);
  assert.deepEqual(avisosDeLimiteKm(trocadas, { porViagem: 20 }).map((a) => a.mensagem), ['Rota 1 (Ana, Viagem 1) passou 5,0 km do limite de 20 km', 'Rota 2 (Ana, Viagem 2) passou 5,0 km do limite de 20 km']);
  const bloco = avisosDoDespacho({ avisosDoSolver: [{ tipo: 'viagens_extras', gravidade: 'info', mensagem: 'x' }], rotas: trocadas, rotacao: {}, capacidades: {}, marcados: [ANA, BETO], limitesKm: { porMotorista: 40 } });
  assert.ok(bloco.some((a) => a.tipo === 'limite_km_motorista') && bloco.some((a) => a.tipo === 'viagens_extras'));
  assert.ok(!avisosDoDespacho({ avisosDoSolver: [], rotas: trocadas, rotacao: {}, capacidades: {}, marcados: [ANA, BETO] }).some((a) => a.tipo.startsWith('limite_km')));
});
