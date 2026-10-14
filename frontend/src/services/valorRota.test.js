import test from 'node:test';
import assert from 'node:assert/strict';
import {
  rotuloDoTipo, validarValorRota, primeiroErroDeValores, montarValoresPorRota, dicaValorBase, rotuloDaOrigem, corDaOrigem, formatarReais,
} from './valorRota.js';

test('campo vazio é válido e fica fora do que vai para o servidor (vale o valor base)', () => {
  assert.deepEqual(validarValorRota(''), { ok: true, vazio: true, mensagem: '' });
  assert.equal(validarValorRota('   ').vazio, true);
  assert.equal(validarValorRota(undefined).ok, true);
  assert.deepEqual(montarValoresPorRota({ 'Carro de passeio': '', 'Fiorino/Utilitário': '  ' }), {});
});

test('aceita vírgula decimal, ponto decimal e zero digitado de propósito', () => {
  for (const texto of ['130', '130,50', '130.5', '0', '0,00', ' 300 ']) {
    assert.equal(validarValorRota(texto).ok, true, texto);
    assert.equal(validarValorRota(texto).vazio, false, texto);
  }
  assert.deepEqual(montarValoresPorRota({ 'Carro de passeio': '', 'Fiorino/Utilitário': ' 300,5 ', X: '0' }), { 'Fiorino/Utilitário': '300,5', X: '0' });
});

test('negativo e texto são recusados com mensagem em linguagem do operador', () => {
  const negativo = validarValorRota('-10');
  assert.equal(negativo.ok, false);
  assert.match(negativo.mensagem, /não pode ser negativo/);
  for (const texto of ['abc', 'R$ 10', '1,2,3', '10 reais']) {
    const r = validarValorRota(texto);
    assert.equal(r.ok, false, texto);
    assert.match(r.mensagem, /em reais/);
  }
  assert.doesNotMatch(`${negativo.mensagem} ${validarValorRota('abc').mensagem}`, /json|api|null|undefined|nan/i);
});

test('o erro de um tipo não depende do outro e indica qual campo está errado', () => {
  assert.equal(primeiroErroDeValores({ 'Carro de passeio': '', 'Fiorino/Utilitário': '300,5' }), '');
  assert.match(primeiroErroDeValores({ 'Carro de passeio': '', 'Fiorino/Utilitário': '-1' }), /^Utilitário: .*negativo/);
  assert.match(primeiroErroDeValores({ 'Carro de passeio': 'abc', 'Fiorino/Utilitário': '10' }), /^Passeio: /);
});

test('rótulos curtos dos tipos de veículo', () => {
  assert.equal(rotuloDoTipo('Carro de passeio'), 'Passeio');
  assert.equal(rotuloDoTipo('Fiorino/Utilitário'), 'Utilitário');
  assert.equal(rotuloDoTipo('Van'), 'Van');
});

test('dica do campo mostra o valor base como "padrão R$ ..."', () => {
  assert.match(dicaValorBase(260), /^padrão R\$\s260,00$/);
  assert.match(dicaValorBase('130.5'), /^padrão R\$\s130,50$/);
  assert.equal(dicaValorBase(undefined), 'valor base');
});

test('a origem exibida: informado nesta roteirização, valor do motorista ou padrão', () => {
  assert.equal(rotuloDaOrigem('informado'), 'informado nesta roteirização');
  assert.equal(rotuloDaOrigem('motorista'), 'valor do motorista');
  assert.equal(rotuloDaOrigem('padrão'), 'padrão');
  assert.equal(rotuloDaOrigem(undefined), 'padrão');
  assert.doesNotMatch(['informado', 'motorista', 'padrão'].map(rotuloDaOrigem).join(' '), /json|api|null|undefined/i);
});

test('cada origem tem uma cor e o padrão é o discreto', () => {
  assert.notEqual(corDaOrigem('informado'), corDaOrigem('motorista'));
  assert.notEqual(corDaOrigem('motorista'), corDaOrigem('padrão'));
  assert.equal(corDaOrigem(undefined), corDaOrigem('padrão'));
});

test('valor em reais ao lado do campo, vazio quando não há valor', () => {
  assert.match(formatarReais(130), /^R\$\s130,00$/);
  assert.match(formatarReais('260.5'), /^R\$\s260,50$/);
  assert.equal(formatarReais(null), '');
  assert.equal(formatarReais(''), '');
  assert.equal(formatarReais('abc'), '');
});

test('valor próprio do motorista: vazio usa o base, vírgula decimal vale, negativo e texto não', () => {
  assert.equal(validarValorRota('').vazio, true);
  assert.equal(validarValorRota('150,5').ok, true);
  assert.equal(validarValorRota('-1').ok, false);
  assert.equal(validarValorRota('abc').ok, false);
});
