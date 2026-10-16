import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MSG_MARQUE_MOTORISTA, textoRotasHoje, rotuloDoMotorista, textoRotasEMotoristas, linhaDeConfirmacao, linhaDeDesfazer,
  rotasPorMotoristaDoResultado, manterSomenteAtivos, alternarMarcacao, motoristasMarcados, podeExecutarComMotoristas, marcarVarios, etiquetaDoMotorista,
} from './selecaoMotoristas.js';

test('rótulo do campo: nome - tipo - rotas de hoje, com singular e plural certos', () => {
  const joao = { nome: 'João', tipo_veiculo: 'Fiorino/Utilitário' };
  assert.equal(rotuloDoMotorista(joao, 1), 'João - Utilitário - 1 rota realizada hoje');
  assert.equal(rotuloDoMotorista(joao, 3), 'João - Utilitário - 3 rotas realizadas hoje');
  assert.equal(rotuloDoMotorista({ nome: 'Ana', tipo_veiculo: 'Carro de passeio' }, 0), 'Ana - Passeio - nenhuma rota hoje');
  assert.equal(rotuloDoMotorista(joao, undefined), 'João - Utilitário - nenhuma rota hoje');
  assert.equal(textoRotasHoje(2), '2 rotas realizadas hoje');
  assert.equal(textoRotasHoje(null), 'nenhuma rota hoje');
});

test('resumo "N rotas (M motoristas)" com singular e plural', () => {
  assert.equal(textoRotasEMotoristas(3, 2), '3 rotas (2 motoristas)');
  assert.equal(textoRotasEMotoristas(1, 1), '1 rota (1 motorista)');
  assert.equal(textoRotasEMotoristas(2, 1), '2 rotas (1 motorista)');
  assert.equal(textoRotasEMotoristas(0, 0), '0 rotas (0 motoristas)');
});

test('linha ao confirmar: "João: +2 rotas (total hoje: 3)" e ao desfazer', () => {
  assert.equal(linhaDeConfirmacao('João', 2, 3), 'João: +2 rotas (total hoje: 3)');
  assert.equal(linhaDeConfirmacao('Ana', 1, 1), 'Ana: +1 rota (total hoje: 1)');
  assert.equal(linhaDeDesfazer('João', 1), 'João: confirmação desfeita (total hoje: 1)');
});

test('rotas desta roteirização por motorista, contando as viagens de cada um', () => {
  const rotas = [
    { motorista_id: 1, motorista_base: 'João', motorista: 'João • Viagem 1' },
    { motorista_id: 2, motorista_base: 'Ana' },
    { motorista_id: 1, motorista_base: 'João', motorista: 'João • Viagem 2' },
    { motorista: 'sem id' },
  ];
  assert.deepEqual(rotasPorMotoristaDoResultado(rotas), [
    { motorista_id: 1, nome: 'João', rotas: 2 },
    { motorista_id: 2, nome: 'Ana', rotas: 1 },
  ]);
  assert.deepEqual(rotasPorMotoristaDoResultado(undefined), []);
});

test('marcar e desmarcar não repete e só os marcados valem', () => {
  const ativos = [{ id: 1, nome: 'João' }, { id: 2, nome: 'Ana' }, { id: 3, nome: 'Beto' }];
  let marcados = [];
  assert.equal(podeExecutarComMotoristas(marcados), false);
  marcados = alternarMarcacao(marcados, 2);
  marcados = alternarMarcacao(marcados, 1);
  assert.deepEqual(marcados, [2, 1]);
  assert.equal(podeExecutarComMotoristas(marcados), true);
  assert.deepEqual(motoristasMarcados(ativos, marcados).map((m) => m.nome), ['João', 'Ana']);
  marcados = alternarMarcacao(marcados, 2);
  assert.deepEqual(marcados, [1]);
  assert.equal(podeExecutarComMotoristas(alternarMarcacao(marcados, 1)), false);
});

test('motorista desativado some da marcação quando a lista de ativos é atualizada', () => {
  assert.deepEqual(manterSomenteAtivos([1, 2, 3], [{ id: 1 }, { id: 3 }]), [1, 3]);
  assert.deepEqual(manterSomenteAtivos([2], []), []);
  assert.deepEqual(manterSomenteAtivos(undefined, undefined), []);
});

test('a mensagem de motorista não marcado é clara e sem termo técnico', () => {
  assert.equal(MSG_MARQUE_MOTORISTA, 'Marque pelo menos um motorista para gerar as rotas.');
  assert.doesNotMatch(MSG_MARQUE_MOTORISTA, /id|api|json|null|erro/i);
});

test('marcar vários mantém quem já estava marcado e não repete', () => {
  assert.deepEqual(marcarVarios([5], [1, 2, 5]), [5, 1, 2]);
  assert.deepEqual(marcarVarios([], [1, 2]), [1, 2]);
  const atuais = [1, 2];
  assert.equal(marcarVarios(atuais, [2]), atuais); // nada novo: devolve o mesmo (sem render à toa)
  assert.deepEqual(marcarVarios(undefined, undefined), []);
});

test('etiqueta do motorista marcado: nome e código', () => {
  assert.equal(etiquetaDoMotorista({ nome: 'João', codigo: 'MOT-0001' }), 'João · MOT-0001');
  assert.equal(etiquetaDoMotorista({ nome: 'Ana', codigo: null }), 'Ana');
});
