import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Não há ambiente de tela nos testes (só node --test), então a verificação é sobre o código do campo: o teclado não pode remover etiquetas.
const codigo = readFileSync(new URL('../components/ComboboxMultiplo.jsx', import.meta.url), 'utf8');
const tratadorDeTeclas = codigo.slice(codigo.indexOf('const aoTeclar'), codigo.indexOf('const aoSairDoCampo'));

test('Backspace no campo vazio não remove nenhuma etiqueta', () => {
  assert.ok(tratadorDeTeclas.length > 50, 'o tratador de teclas foi encontrado');
  assert.doesNotMatch(tratadorDeTeclas, /Backspace|Delete/);
  assert.doesNotMatch(tratadorDeTeclas, /onRemover/);
});

test('as etiquetas continuam removíveis pelo botão "x" de cada uma', () => {
  assert.match(codigo, /onClick=\{\(\) => onRemover\(chip\.id\)\}/);
});
