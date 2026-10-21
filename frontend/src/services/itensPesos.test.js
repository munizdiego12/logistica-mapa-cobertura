import test from 'node:test';
import assert from 'node:assert/strict';
import {
  numeroDoPeso, validarNovoItem, corpoNovoItem, quantosVaoSerImportados, textoDoErroDeLinha, textoDoResultado, FORMULARIO_NOVO_ITEM,
} from './itensPesos.js';

const form = (extra = {}) => ({ ...FORMULARIO_NOVO_ITEM, id_sku: '90001', nome: 'Arroz 5kg', peso_kg: '5', ...extra });

test('peso com vírgula ou ponto decimal', () => {
  assert.equal(numeroDoPeso('1,5'), 1.5);
  assert.equal(numeroDoPeso('0.045'), 0.045);
  assert.equal(numeroDoPeso(' 2 kg '), 2);
  assert.equal(numeroDoPeso('1.234,5'), 1234.5);
  assert.equal(numeroDoPeso('abc'), null);
  assert.equal(numeroDoPeso(''), null);
});

test('novo item: código e nome obrigatórios; peso e demais campos opcionais', () => {
  assert.equal(validarNovoItem(form()).ok, true);
  assert.equal(validarNovoItem(form({ peso_kg: '' })).ok, true);
  assert.equal(validarNovoItem(form({ id_sku: '  ' })).erros.id_sku, 'Informe o código do item.');
  assert.match(validarNovoItem(form({ id_sku: 'a b' })).erros.id_sku, /até 40 letras, números/);
  assert.equal(validarNovoItem(form({ nome: '' })).erros.nome, 'Informe o nome do item.');
  assert.match(validarNovoItem(form({ reference_code: 'r'.repeat(61) })).erros.reference_code, /até 60/);
  assert.match(validarNovoItem(form({ fonte: 'f'.repeat(101) })).erros.fonte, /até 100/);
});

test('novo item: peso maior que 0 e até 1000, com vírgula decimal', () => {
  assert.equal(validarNovoItem(form({ peso_kg: '1,5' })).ok, true);
  assert.equal(validarNovoItem(form({ peso_kg: '1000' })).ok, true);
  for (const ruim of ['0', '-1', '1000,5', 'abc', '1,5,5']) {
    assert.match(validarNovoItem(form({ peso_kg: ruim })).erros.peso_kg, /maior que 0 e até 1000/, ruim);
  }
  assert.match(validarNovoItem(form({ confianca: 'altíssima' })).erros.confianca, /alta, média ou baixa/);
});

test('corpo do novo item: vazios viram null, confiança padrão média', () => {
  assert.deepEqual(corpoNovoItem(form({ id_sku: ' 90001 ', reference_code: ' ', peso_kg: '1,5', fonte: '' })),
    { id_sku: '90001', reference_code: null, nome: 'Arroz 5kg', peso_kg: '1,5', fonte: null, confianca: 'media' });
  assert.equal(corpoNovoItem(form({ peso_kg: '' })).peso_kg, null);
  assert.equal(FORMULARIO_NOVO_ITEM.confianca, 'media');
});

const RESUMO = { novos_com_peso: 10, novos_sem_peso: 4, existentes_atualizaveis: 6, existentes_atualizaveis_sem_peso: 2, existentes_preservados: 3 };

test('quantos itens a importação vai gravar com as opções marcadas', () => {
  assert.equal(quantosVaoSerImportados(RESUMO), 14); // padrão: incluir sem peso, não atualizar
  assert.equal(quantosVaoSerImportados(RESUMO, { incluirSemPeso: false }), 10);
  assert.equal(quantosVaoSerImportados(RESUMO, { atualizar: true, incluirSemPeso: true }), 20);
  assert.equal(quantosVaoSerImportados(RESUMO, { atualizar: true, incluirSemPeso: false }), 14); // linhas sem peso dos existentes ficam de fora
  assert.equal(quantosVaoSerImportados({ ...RESUMO, novos_com_peso: 0, novos_sem_peso: 0 }, { incluirSemPeso: true }), 0);
});

test('textos do relatório e do resultado', () => {
  assert.equal(textoDoErroDeLinha({ linha: 7, id: '99', motivos: ['nome vazio', 'peso inválido'] }), 'Linha 7 (código 99): nome vazio; peso inválido');
  assert.equal(textoDoErroDeLinha({ linha: 3, id: '', motivos: ['código vazio'] }), 'Linha 3: código vazio');
  const r = { novos: 8, novos_sem_peso: 4, atualizados: 1, preservados: 2, ja_existentes_ignorados: 0, sem_peso_ignorados: 0, invalidos: 3 };
  assert.equal(textoDoResultado(r), 'Importação concluída: 12 itens novos, 1 atualizado, 2 preservados (peso editado na tela), 3 linhas com erro ficaram de fora.');
  assert.equal(textoDoResultado({ novos: 1, novos_sem_peso: 0, atualizados: 0, preservados: 0, ja_existentes_ignorados: 5, sem_peso_ignorados: 1, invalidos: 1 }),
    'Importação concluída: 1 item novo, 5 já existentes ignorados, 1 sem peso ignorado, 1 linha com erro ficou de fora.');
});
