import test from 'node:test';
import assert from 'node:assert/strict';
import {
  numeroPtBr, classificarCoordenadas, validarCoordenadas, linhasDoHover, enderecoParaExibir, interpretarRaio, validarFormularioLoja,
  corpoDaLoja, formularioDaLoja, nomeDoHub, FORMULARIO_VAZIO, UFS,
} from './lojas.js';

const formulario = (extra = {}) => ({ ...FORMULARIO_VAZIO, nome: 'Atacadão Guarujá', uf: 'SP', lat: '-23,9930', lng: '-46,2564', ...extra });

test('vírgula decimal e ponto decimal valem nas coordenadas', () => {
  assert.equal(numeroPtBr('-23,5614'), -23.5614);
  assert.equal(numeroPtBr('-23.5614'), -23.5614);
  assert.equal(numeroPtBr(' 1.234,5 '), 1234.5);
  for (const ruim of ['', 'abc', '-23,5,6', '-23.561.400', null, '12 graus']) assert.equal(numeroPtBr(ruim), null, String(ruim));
});

test('limites do Brasil e valores trocados', () => {
  assert.equal(classificarCoordenadas(-34, -74), 'ok');
  assert.equal(classificarCoordenadas(6, -34), 'ok');
  assert.equal(classificarCoordenadas(-34.0001, -50), 'fora_do_brasil');
  assert.equal(classificarCoordenadas(0, -33.9999), 'fora_do_brasil');
  assert.equal(classificarCoordenadas(-46.6333, -23.5505), 'trocadas');
  assert.equal(classificarCoordenadas(40.7, -74), 'fora_do_brasil');
});

test('validação das coordenadas devolve mensagem em linguagem do operador', () => {
  assert.deepEqual(validarCoordenadas('-23,5614', '-46,6333'), { ok: true, lat: -23.5614, lng: -46.6333 });
  assert.match(validarCoordenadas('abc', '-46').mensagem, /latitude precisa ser um número/);
  assert.match(validarCoordenadas('-23', '').mensagem, /longitude precisa ser um número/);
  assert.match(validarCoordenadas('-46,6333', '-23,5505').mensagem, /trocadas/);
  assert.match(validarCoordenadas('40', '-74').mensagem, /fora do Brasil/);
  const todas = ['abc', '-46,6333', '40'].map((v) => validarCoordenadas(v, '-46').mensagem).join(' ');
  assert.doesNotMatch(todas, /json|api|null|undefined|nan/i);
});

test('hover: nome, endereço e UF, uma informação por linha e só o que existir', () => {
  assert.deepEqual(linhasDoHover({ nome: 'Atacadão Guarujá', endereco: 'Av. Santos Dumont, 100', uf: 'SP' }), ['Atacadão Guarujá', 'Av. Santos Dumont, 100', 'SP']);
  assert.deepEqual(linhasDoHover({ nome: 'Atacadão Guarujá', endereco: null, uf: 'SP' }), ['Atacadão Guarujá', 'SP']);
  assert.deepEqual(linhasDoHover({ nome: 'Atacadão Guarujá', endereco: '  ', uf: undefined }), ['Atacadão Guarujá']);
  assert.deepEqual(linhasDoHover({ nome: 'X', filial: 'Guarujá', endereco: 'Rua', uf: 'SP' }), ['X', 'Rua', 'SP']); // filial não aparece
  assert.deepEqual(linhasDoHover(null), []);
});

test('raio do Raio X km: padrão 30, de 1 a 200 km, vírgula decimal', () => {
  assert.deepEqual(interpretarRaio(''), { ok: true, valor: 30 });
  assert.deepEqual(interpretarRaio('50'), { ok: true, valor: 50 });
  assert.deepEqual(interpretarRaio('12,5'), { ok: true, valor: 12.5 });
  assert.equal(interpretarRaio('1').ok, true);
  assert.equal(interpretarRaio('200').ok, true);
  for (const ruim of ['0', '-5', '201', 'abc', '0,5']) {
    const r = interpretarRaio(ruim);
    assert.equal(r.ok, false, ruim);
    assert.equal(r.mensagem, 'O raio precisa ficar entre 1 e 200 km.');
  }
});

test('formulário de loja: campos opcionais, nome e coordenadas obrigatórios', () => {
  assert.equal(validarFormularioLoja(formulario()).ok, true);
  assert.equal(validarFormularioLoja(formulario({ uf: '', endereco: '' })).ok, true);
  assert.match(validarFormularioLoja(formulario({ nome: '  ' })).erros.nome, /nome da loja/);
  assert.match(validarFormularioLoja(formulario({ uf: 'ZZ' })).erros.uf, /Estado inválido/);
  assert.match(validarFormularioLoja(formulario({ lat: '-46,6', lng: '-23,5' })).erros.lat, /trocadas/);
  assert.match(validarFormularioLoja(formulario({ lng: 'x' })).erros.lng, /longitude/);
  assert.match(validarFormularioLoja(formulario({ capacidade_peso: '-3' })).erros.capacidade_peso, /maior que zero/);
  assert.equal(validarFormularioLoja(formulario({ capacidade_volume: '1.500,5' })).ok, true);
  assert.match(validarFormularioLoja(formulario({ janela_manha_inicio: '14:00' })).erros.janela_manha, /início precisa ser antes do fim/);
  assert.match(validarFormularioLoja(formulario({ janela_tarde_fim: 'abc' })).erros.janela_tarde, /formato 08:00/);
  assert.equal(validarFormularioLoja(formulario({ usa_noite: false, janela_noite_inicio: '', janela_noite_fim: '' })).ok, true);
  assert.match(validarFormularioLoja(formulario({ janela_noite_inicio: '22:00' })).erros.janela_noite, /noite/);
});

test('corpo enviado: sem coluna filial, vazios viram null, noite desligada some', () => {
  const corpo = corpoDaLoja(formulario({ endereco: '', uf: 'sp', usa_noite: false }));
  assert.equal(corpo.uf, 'SP');
  assert.equal(corpo.endereco, null);
  assert.equal(corpo.janela_noite_inicio, null);
  assert.equal(corpo.usa_noite, false);
  assert.equal(corpo.lat, '-23,9930');
  assert.equal('filial' in corpo, false);
});

test('formulário a partir da loja do servidor (vírgula decimal e noite)', () => {
  const f = formularioDaLoja({ nome: 'Loja', uf: null, endereco: null, lat: -23.5614, lng: -46.6, capacidade_peso: 1500.5, janela_noite_inicio: null, usa_noite: false, ativo: true });
  assert.equal(f.lat, '-23,5614');
  assert.equal(f.capacidade_peso, '1500,5');
  assert.equal(f.uf, '');
  assert.equal(f.usa_noite, false);
  assert.equal(f.janela_manha_inicio, '08:00');
});

test('nome do hub para arquivos: a loja (já com a filial) ou o logradouro', () => {
  assert.equal(nomeDoHub({ nome: 'Atacadão Guarujá' }, { rua: 'Av. Paulista' }, 'Santos'), 'Atacadão Guarujá');
  assert.equal(nomeDoHub(null, { rua: 'Av. Paulista' }, 'Santos'), 'Av. Paulista');
  assert.equal(nomeDoHub(null, { rua: '' }, 'Santos'), 'Santos');
  assert.equal(nomeDoHub(null, null, ''), 'hub');
  assert.equal(UFS.length, 27);
});

test('hover: o endereço sai sem o ", Brazil" ou ", Brasil" do final, sem mexer no dado', () => {
  assert.equal(enderecoParaExibir('Av. Santos Dumont, 100, Guarujá, SP, Brazil'), 'Av. Santos Dumont, 100, Guarujá, SP');
  assert.equal(enderecoParaExibir('Rua A, 5, Brasil'), 'Rua A, 5');
  assert.equal(enderecoParaExibir('Rua A, 5 ,BRASIL.'), 'Rua A, 5');
  assert.equal(enderecoParaExibir('Avenida do Brasil'), 'Avenida do Brasil');
  assert.equal(enderecoParaExibir('Rua Brasil, 5'), 'Rua Brasil, 5');
  assert.equal(enderecoParaExibir('Brazil'), '');
  assert.equal(enderecoParaExibir(null), '');
  const loja = { nome: 'Atacadão Guarujá', endereco: 'Av. Santos Dumont, 100, Brazil', uf: 'SP' };
  assert.deepEqual(linhasDoHover(loja), ['Atacadão Guarujá', 'Av. Santos Dumont, 100', 'SP']);
  assert.equal(loja.endereco, 'Av. Santos Dumont, 100, Brazil');
  assert.deepEqual(linhasDoHover({ nome: 'X', endereco: 'Brazil', uf: 'SP' }), ['X', 'SP']);
});

test('cidade é opcional no formulário e vai (ou não) no corpo enviado', () => {
  assert.equal(validarFormularioLoja(formulario({ cidade: 'Guarujá' })).ok, true);
  assert.equal(validarFormularioLoja(formulario({ cidade: '' })).ok, true);
  assert.match(validarFormularioLoja(formulario({ cidade: 'x'.repeat(121) })).erros.cidade, /cidade/);
  assert.equal(corpoDaLoja(formulario({ cidade: ' Guarujá ' })).cidade, 'Guarujá');
  assert.equal(corpoDaLoja(formulario({ cidade: '  ' })).cidade, null);
  assert.equal(formularioDaLoja({ nome: 'L', cidade: 'Santos', lat: -23.9, lng: -46.3 }).cidade, 'Santos');
  assert.equal(formularioDaLoja({ nome: 'L', cidade: null, lat: -23.9, lng: -46.3 }).cidade, '');
});
