import test from 'node:test';
import assert from 'node:assert/strict';
import {
  numeroPtBr, classificarCoordenadas, validarCoordenadas, linhasDoHover, enderecoParaExibir, interpretarRaio, validarFormularioLoja,
  corpoDaLoja, formularioDaLoja, nomeDoHub, FORMULARIO_VAZIO, UFS,
  normalizarBusca, filtrarLojas, cidadeEUf, destacarTrechos, moverDestaque, ROTULO_OUTRO_ENDERECO,
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

test('nome de operação e código externo: opcionais, com limite, enviados e preservados na edição', () => {
  assert.equal(validarFormularioLoja(formulario({ nome_operacao: 'SDA Mooca', codigo_externo: 'S-1' })).ok, true);
  assert.match(validarFormularioLoja(formulario({ nome_operacao: 'x'.repeat(121) })).erros.nome_operacao, /nome de operação/);
  assert.match(validarFormularioLoja(formulario({ codigo_externo: 'x'.repeat(41) })).erros.codigo_externo, /código externo/);
  const corpo = corpoDaLoja(formulario({ nome_operacao: ' SDA Mooca ', codigo_externo: '  ' }));
  assert.equal(corpo.nome_operacao, 'SDA Mooca');
  assert.equal(corpo.codigo_externo, null);
  // editar uma loja que já tem os dois campos não pode apagá-los ao salvar (nem ao desativar)
  const form = formularioDaLoja({ nome: 'L', nome_operacao: 'SDA Mooca', codigo_externo: 'S-1', lat: -23.9, lng: -46.3 });
  assert.deepEqual([form.nome_operacao, form.codigo_externo], ['SDA Mooca', 'S-1']);
  const corpoSalvo = corpoDaLoja(form);
  assert.deepEqual([corpoSalvo.nome_operacao, corpoSalvo.codigo_externo], ['SDA Mooca', 'S-1']);
  assert.deepEqual([formularioDaLoja({ nome: 'L', lat: -23.9, lng: -46.3 }).nome_operacao, FORMULARIO_VAZIO.codigo_externo], ['', '']);
});

// ---------------------------------------------------------------- pesquisa de lojas (campo com lista)
const LOJAS = [
  { id: 1, nome: 'Atacadão Guarujá', cidade: 'Guarujá', uf: 'SP' },
  { id: 2, nome: 'Atacadão Campinas', cidade: 'Campinas', uf: 'SP' },
  { id: 3, nome: 'Atacadão Rio Branco', cidade: 'Rio de Janeiro', uf: 'RJ' },
  { id: 4, nome: 'Atacadão Aspen', cidade: 'Niterói', uf: 'RJ' },
  { id: 5, nome: 'Atacadão Zona Sul', cidade: 'Santos', uf: 'SP' },
  { id: 6, nome: 'Atacadão São José', cidade: 'São José dos Campos', uf: 'SP' },
  { id: 7, nome: 'Atacadão Cuiabá', cidade: 'Cuiabá', uf: 'MT' },
  { id: 8, nome: 'Atacadão Sem Cidade', cidade: null, uf: null },
];
const nomes = (resultado) => resultado.map((r) => r.loja.nome);

test('normalizar a busca: sem acento, minúsculas e espaços simples', () => {
  assert.equal(normalizarBusca('  Atacadão   GUARUJÁ '), 'atacadao guaruja');
  assert.equal(normalizarBusca('São José'), 'sao jose');
  assert.equal(normalizarBusca(null), '');
  assert.equal(normalizarBusca('Ç ã ü'), 'c a u');
});

test('"guaruja" acha "Atacadão Guarujá" (sem acento, maiúsculas ou espaços extras)', () => {
  for (const busca of ['guaruja', 'GUARUJÁ', '  guaruja  ', 'Guarujá', 'ataca guaruja', 'atacadao   guaruja']) {
    assert.deepEqual(nomes(filtrarLojas(LOJAS, busca)), ['Atacadão Guarujá'], busca);
  }
});

test('digitar com acento acha nome sem acento e o contrário', () => {
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'cuiabá')), ['Atacadão Cuiabá']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'cuiaba')), ['Atacadão Cuiabá']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'sao jose')), ['Atacadão São José']);
  assert.equal(filtrarLojas([{ nome: 'Atacadao Maringa', cidade: 'Maringa', uf: 'PR' }], 'maringá').length, 1);
});

test('a busca também olha a cidade (a loja pode ter nome diferente da cidade)', () => {
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'santos')), ['Atacadão Zona Sul']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'niteroi')), ['Atacadão Aspen']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'niterói')), ['Atacadão Aspen']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'rio de janeiro')), ['Atacadão Rio Branco']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'campos')), ['Atacadão São José']); // "São José dos Campos"
});

test('"sp" lista as lojas de SP (a sigla vale como UF, não como pedaço no meio de uma palavra)', () => {
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'sp')), ['Atacadão Campinas', 'Atacadão Guarujá', 'Atacadão São José', 'Atacadão Zona Sul']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'SP')), nomes(filtrarLojas(LOJAS, 'sp')));
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'rj')), ['Atacadão Aspen', 'Atacadão Rio Branco']);
  assert.equal(nomes(filtrarLojas(LOJAS, 'sp')).includes('Atacadão Aspen'), false); // "Aspen" tem "sp" no meio: não entra
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'mt')), ['Atacadão Cuiabá']);
});

test('vários termos precisam casar todos (nome + UF, nome + cidade)', () => {
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'atacadao sp')), ['Atacadão Campinas', 'Atacadão Guarujá', 'Atacadão São José', 'Atacadão Zona Sul']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'atacadao rj')), ['Atacadão Aspen', 'Atacadão Rio Branco']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'zona santos')), ['Atacadão Zona Sul']);
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'guaruja rj')), []);
});

test('sem resultado devolve lista vazia', () => {
  assert.deepEqual(filtrarLojas(LOJAS, 'xyzxyz'), []);
  assert.deepEqual(filtrarLojas(LOJAS, 'guaruja sp campinas'), []);
  assert.deepEqual(filtrarLojas([], 'sp'), []);
  assert.deepEqual(filtrarLojas(undefined, 'sp'), []);
});

test('busca vazia ou só com espaços devolve todas as lojas em ordem de nome', () => {
  const todas = nomes(filtrarLojas(LOJAS, ''));
  assert.equal(todas.length, LOJAS.length);
  assert.deepEqual(todas, [...todas].sort((a, b) => a.localeCompare(b, 'pt-BR')));
  assert.equal(filtrarLojas(LOJAS, '   ').length, LOJAS.length);
});

test('quem começa com o que foi digitado vem antes de quem só contém', () => {
  const lojas = [{ nome: 'Loja Anassul', cidade: 'Z', uf: 'RS' }, { nome: 'Sul Atacado', cidade: 'Y', uf: 'RS' }, { nome: 'Loja Parque Sul', cidade: 'X', uf: 'SP' }];
  assert.deepEqual(nomes(filtrarLojas(lojas, 'sul')), ['Loja Parque Sul', 'Sul Atacado', 'Loja Anassul']);
});

test('loja sem cidade e sem UF continua achável pelo nome', () => {
  assert.deepEqual(nomes(filtrarLojas(LOJAS, 'sem cidade')), ['Atacadão Sem Cidade']);
});

test('linha pequena da lista: cidade e UF, só o que existir', () => {
  assert.equal(cidadeEUf({ cidade: 'Guarujá', uf: 'SP' }), 'Guarujá · SP');
  assert.equal(cidadeEUf({ cidade: null, uf: 'SP' }), 'SP');
  assert.equal(cidadeEUf({ cidade: 'Guarujá', uf: '' }), 'Guarujá');
  assert.equal(cidadeEUf({}), '');
});

test('destaque da parte que casou (sem diferença de acento ou maiúsculas)', () => {
  assert.deepEqual(destacarTrechos('Atacadão Guarujá', 'guaruja'), [{ texto: 'Atacadão ', destaque: false }, { texto: 'Guarujá', destaque: true }]);
  assert.deepEqual(destacarTrechos('Atacadão Guarujá', 'ATACADAO'), [{ texto: 'Atacadão', destaque: true }, { texto: ' Guarujá', destaque: false }]);
  assert.deepEqual(destacarTrechos('São José', 'sao jose'), [{ texto: 'São', destaque: true }, { texto: ' ', destaque: false }, { texto: 'José', destaque: true }]);
  assert.deepEqual(destacarTrechos('Guarujá · SP', 'sp'), [{ texto: 'Guarujá · ', destaque: false }, { texto: 'SP', destaque: true }]);
  assert.deepEqual(destacarTrechos('Atacadão Guarujá', 'gua'), [{ texto: 'Atacadão ', destaque: false }, { texto: 'Gua', destaque: true }, { texto: 'rujá', destaque: false }]);
});

test('destaque sem busca, sem casamento e com termos que se sobrepõem', () => {
  assert.deepEqual(destacarTrechos('Atacadão Guarujá', ''), [{ texto: 'Atacadão Guarujá', destaque: false }]);
  assert.deepEqual(destacarTrechos('Atacadão Guarujá', 'xyz'), [{ texto: 'Atacadão Guarujá', destaque: false }]);
  assert.deepEqual(destacarTrechos('', 'sp'), [{ texto: '', destaque: false }]);
  assert.deepEqual(destacarTrechos('Guarujá', 'gua uaru'), [{ texto: 'Guaru', destaque: true }, { texto: 'já', destaque: false }]);
  assert.equal(destacarTrechos('Atacadão Guarujá', 'ata guaruja').map((t) => t.texto).join(''), 'Atacadão Guarujá'); // nunca perde letra
});

test('setas dão a volta nas pontas da lista', () => {
  assert.equal(moverDestaque(0, 1, 3), 1);
  assert.equal(moverDestaque(2, 1, 3), 0);
  assert.equal(moverDestaque(0, -1, 3), 2);
  assert.equal(moverDestaque(-1, 1, 3), 0);
  assert.equal(moverDestaque(-1, -1, 3), 2);
  assert.equal(moverDestaque(0, 1, 0), -1);
  assert.equal(ROTULO_OUTRO_ENDERECO, 'Outro endereço');
});
