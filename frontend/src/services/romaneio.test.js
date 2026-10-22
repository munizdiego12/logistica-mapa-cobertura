import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  COLUNAS, COLUNAS_ANTIGAS, COLUNAS_NOVAS, BOM, SEPARADOR, neutralizarFormula, escaparCampo, linhasDoRomaneio, montarCsv, nomeDoArquivo, avisoDoRomaneio,
} from './romaneio.js';
import { relatorioDeJanelas } from './janelas.js';
import { rotasEfetivas } from './despacho.js';

const LOJA = { janela_manha_inicio: '08:00', janela_manha_fim: '13:00', janela_tarde_inicio: '13:00', janela_tarde_fim: '18:00', janela_noite_inicio: null, janela_noite_fim: null };
const parada = (id, extra = {}) => ({ id, Endereco: `Rua ${id}`, Numero: '10', Bairro: 'Centro', CEP: '01310100', Volume: 2, lat: -23.5505, lon: -46.6333, ...extra });
// Ana: 2 paradas (trechos de 10 e 20 min, volta de 15); Beto: 1 parada (10 min, volta de 10); 10 min por parada
const rota = (id, motorista, nome, modal, paradas, tempos, extra = {}) => ({
  id, motorista_id: motorista, motorista_base: nome, motorista: nome, modal, viagem_num: 1, qtd_pedidos: paradas.length, km_total: 10, paradas,
  tempos_trechos_s: tempos, distancias_trechos_km: tempos.map(() => 1), tempo_deslocamento_min: Math.round(tempos.reduce((a, b) => a + b, 0) / 60), ...extra,
});
const ROTAS = [
  rota(1, 1, 'Ana', 'Carro de passeio', [parada('P1'), parada('P2')], [600, 1200, 900]),
  rota(2, 2, 'Beto', 'Fiorino/Utilitário', [parada('P3')], [600, 600]),
];
const PEDIDOS = [{ id: 'P1', cliente: 'Maria Souza' }, { id: 'P2', cliente: 'João Álvares', janela_inicio: '08:00', janela_fim: '08:20' }, { id: 'P3', cliente: 'Zé' }];
const dados = (extra = {}) => ({
  rotas: ROTAS, pedidos: PEDIDOS, loja: LOJA, turno: 'manha',
  relatorio: relatorioDeJanelas({ rotas: ROTAS, pedidos: PEDIDOS, loja: LOJA, turno: 'manha', tempoPorParada: 10 }), ...extra,
});

test('colunas: as 10 antigas iguais e na mesma ordem, as 8 novas no fim, sem peso', () => {
  assert.deepEqual(COLUNAS_ANTIGAS, ['Rota', 'Motorista', 'Viagem', 'Veiculo', 'Ordem_Parada', 'Endereco', 'Numero', 'Bairro', 'CEP', 'Volume']);
  assert.deepEqual(COLUNAS_NOVAS, ['ID_Pedido', 'Cliente', 'Latitude', 'Longitude', 'Chegada_Estimada', 'Janela_Inicio', 'Janela_Fim', 'Fora_do_Prazo']);
  assert.deepEqual(COLUNAS, [...COLUNAS_ANTIGAS, ...COLUNAS_NOVAS]);
  assert.ok(!COLUNAS.some((c) => /peso|kg/i.test(c)));
  const cabecalho = montarCsv(dados()).split('\n')[0];
  assert.equal(cabecalho, `${BOM}Rota;Motorista;Viagem;Veiculo;Ordem_Parada;Endereco;Numero;Bairro;CEP;Volume;ID_Pedido;Cliente;Latitude;Longitude;Chegada_Estimada;Janela_Inicio;Janela_Fim;Fora_do_Prazo`);
});

test('uma linha por parada, na ordem das rotas e das paradas, com o mesmo jeito das colunas antigas', () => {
  const linhas = montarCsv(dados()).split('\n').slice(0, -1);
  assert.equal(linhas.length, 1 + 3);
  assert.ok(linhas[1].startsWith('Rota 1;"Ana";Viagem 1;"Carro de passeio";1;"Rua P1";"10";"Centro";"01310100";2;'));
  assert.ok(linhas[2].startsWith('Rota 1;"Ana";Viagem 1;"Carro de passeio";2;"Rua P2";'));
  assert.ok(linhas[3].startsWith('Rota 2;"Beto";Viagem 1;"Fiorino/Utilitário";1;"Rua P3";'));
});

test('cliente, id e coordenadas por pedido', () => {
  const linhas = linhasDoRomaneio(dados());
  assert.deepEqual(linhas.map((l) => [l[10], l[11], l[12], l[13]]), [
    ['"P1"', '"Maria Souza"', '-23,550500', '-46,633300'], ['"P2"', '"João Álvares"', '-23,550500', '-46,633300'], ['"P3"', '"Zé"', '-23,550500', '-46,633300'],
  ]);
});

test('pedido que não está no lote: cliente e janela do pedido vazios, sem erro', () => {
  const linhas = linhasDoRomaneio(dados({ pedidos: [] }));
  assert.equal(linhas[0][11], '""');
  assert.equal(linhas[1][11], '""');
  assert.deepEqual([linhas[1][15], linhas[1][16]], ['08:00', '13:00']); // sem a janela do pedido, cai na janela da loja
});

test('lat/lng ausentes ou inválidas ficam vazias', () => {
  const rotas = [rota(1, 1, 'Ana', 'Carro de passeio', [parada('P1', { lat: null, lon: undefined })], [600, 600])];
  const l = linhasDoRomaneio(dados({ rotas, relatorio: null }))[0];
  assert.deepEqual([l[12], l[13]], ['', '']);
});

test('chegada estimada e fora do prazo (Sim e Não)', () => {
  // manhã, saída 08:00: P1 chega 08:10 (janela da loja 08-13: Não); P2 chega 08:40, janela própria até 08:20: Sim; P3 (Beto) chega 08:10: Não
  const linhas = linhasDoRomaneio(dados());
  assert.deepEqual(linhas.map((l) => [l[14], l[17]]), [['08:10', 'Não'], ['08:40', 'Sim'], ['08:10', 'Não']]);
});

test('chegada depois da meia-noite mostra "(dia seguinte)"', () => {
  const rel = relatorioDeJanelas({ rotas: ROTAS, pedidos: PEDIDOS, loja: LOJA, turno: 'manha', horaDeSaida: '23:50', tempoPorParada: 10 });
  const linhas = linhasDoRomaneio(dados({ relatorio: rel }));
  assert.equal(linhas[0][14], '00:00 (dia seguinte)');
  assert.equal(linhas[0][17], 'Sim');
});

test('janela do pedido vence a da loja; pedido sem janela usa a da loja; sem nenhuma, vazias', () => {
  const linhas = linhasDoRomaneio(dados());
  assert.deepEqual([linhas[0][15], linhas[0][16]], ['08:00', '13:00']); // P1: da loja
  assert.deepEqual([linhas[1][15], linhas[1][16]], ['08:00', '08:20']); // P2: do pedido
  const semLoja = linhasDoRomaneio(dados({ loja: null, relatorio: null }));
  assert.deepEqual([semLoja[0][15], semLoja[0][16]], ['', '']);
  assert.deepEqual([semLoja[1][15], semLoja[1][16]], ['08:00', '08:20']);
  const semNoite = linhasDoRomaneio(dados({ turno: 'noite' }));
  assert.deepEqual([semNoite[0][15], semNoite[0][16]], ['', '']); // a loja não tem janela na noite
});

test('sem hora de saída: chegada e Fora_do_Prazo vazios, janelas preenchidas', () => {
  const lojaSemJanela = { ...LOJA, janela_manha_inicio: null, janela_manha_fim: null };
  const rel = relatorioDeJanelas({ rotas: ROTAS, pedidos: PEDIDOS, loja: lojaSemJanela, turno: 'manha' });
  assert.equal(rel.status, 'sem_saida');
  const linhas = linhasDoRomaneio(dados({ loja: lojaSemJanela, relatorio: rel }));
  assert.deepEqual(linhas.map((l) => [l[14], l[17]]), [['', ''], ['', ''], ['', '']]);
  assert.deepEqual([linhas[1][15], linhas[1][16]], ['08:00', '08:20']); // a janela do pedido aparece mesmo assim
});

test('sem nenhuma janela para avaliar, Fora_do_Prazo fica vazio mesmo com chegada', () => {
  const lote = [{ id: 'P1' }, { id: 'P2' }, { id: 'P3' }];
  const rel = relatorioDeJanelas({ rotas: ROTAS, pedidos: lote, loja: null, turno: 'manha', horaDeSaida: '08:00', tempoPorParada: 10 });
  const linhas = linhasDoRomaneio(dados({ pedidos: lote, loja: null, relatorio: rel }));
  assert.deepEqual(linhas.map((l) => [l[14], l[17]]), [['08:10', ''], ['08:40', ''], ['08:10', '']]);
});

test('motorista, veículo e viagem são os FINAIS depois de trocar o motorista de uma rota', () => {
  const motoristas = [{ id: 1, nome: 'Ana', tipo_veiculo: 'Carro de passeio', ativo: true }, { id: 2, nome: 'Beto', tipo_veiculo: 'Fiorino/Utilitário', ativo: true }];
  const trocadas = rotasEfetivas(ROTAS, { 1: 2 }, motoristas); // a rota 1 passa para o Beto, que fica com a 1 e a 2
  const rel = relatorioDeJanelas({ rotas: trocadas, pedidos: PEDIDOS, loja: LOJA, turno: 'manha', tempoPorParada: 10 });
  const linhas = linhasDoRomaneio({ rotas: trocadas, pedidos: PEDIDOS, relatorio: rel, loja: LOJA, turno: 'manha' });
  assert.deepEqual(linhas.map((l) => [l[0], l[1], l[2], l[3]]), [
    ['Rota 1', '"Beto"', 'Viagem 1', '"Fiorino/Utilitário"'], ['Rota 1', '"Beto"', 'Viagem 1', '"Fiorino/Utilitário"'], ['Rota 2', '"Beto"', 'Viagem 2', '"Fiorino/Utilitário"'],
  ]);
  // a 2ª viagem sai quando a 1ª volta (08:00 + 45 min de deslocamento + 2 paradas = 09:05) e chega 10 min depois
  assert.equal(linhas[2][14], '09:15');
});

test('neutralização de fórmula: = + - @ ganham apóstrofo; números e textos comuns ficam como estão', () => {
  assert.equal(neutralizarFormula('=1+1'), "'=1+1");
  assert.equal(neutralizarFormula('@SOMA(A1)'), "'@SOMA(A1)");
  assert.equal(neutralizarFormula('+55 11 99999'), "'+55 11 99999");
  assert.equal(neutralizarFormula('-cmd|calc'), "'-cmd|calc");
  assert.equal(neutralizarFormula('\t=1'), "'\t=1");
  assert.equal(neutralizarFormula('-5'), '-5');
  assert.equal(neutralizarFormula('+55'), '+55');
  assert.equal(neutralizarFormula('-23,55'), '-23,55');
  assert.equal(neutralizarFormula('Rua A = B'), 'Rua A = B');
  assert.equal(neutralizarFormula('João'), 'João');
  assert.equal(neutralizarFormula(null), '');
  assert.equal(neutralizarFormula(10), '10');
});

test('o romaneio neutraliza cliente, endereço e bairro, e a latitude negativa continua número', () => {
  const rotas = [rota(1, 1, 'Ana', 'Carro de passeio', [parada('P1', { Endereco: '=HYPERLINK("x")', Bairro: '@bairro', Numero: '-5' })], [600, 600])];
  const linhas = linhasDoRomaneio(dados({ rotas, pedidos: [{ id: 'P1', cliente: '+cliente' }], relatorio: null }));
  assert.equal(linhas[0][5], '"\'=HYPERLINK(""x"")"');
  assert.equal(linhas[0][7], '"\'@bairro"');
  assert.equal(linhas[0][6], '"-5"');
  assert.equal(linhas[0][11], '"\'+cliente"');
  assert.equal(linhas[0][12], '-23,550500');
});

test('escape de vírgula, aspas, quebra de linha e espaços nas pontas', () => {
  assert.equal(escaparCampo('a,b'), '"a,b"');
  assert.equal(escaparCampo('Rua A; casa 2'), '"Rua A; casa 2"');
  assert.equal(escaparCampo('diz "oi"'), '"diz ""oi"""');
  assert.equal(escaparCampo('linha1\nlinha2'), '"linha1\nlinha2"');
  assert.equal(escaparCampo('a\r\nb'), '"a\r\nb"');
  assert.equal(escaparCampo(' espaço'), '" espaço"');
  assert.equal(escaparCampo('simples'), 'simples');
  assert.equal(escaparCampo('simples', true), '"simples"');
  assert.equal(escaparCampo(null), '');
});

test('arquivo: ";", vírgula, aspas e quebra de linha no texto continuam um registro só; acentos em UTF-8; \\n no fim; BOM uma vez só', () => {
  const rotas = [rota(1, 1, 'Ana', 'Carro de passeio', [parada('P1', { Endereco: 'Rua "Ação", 5; casa 2\nfundos' })], [600, 600])];
  const csv = montarCsv(dados({ rotas, pedidos: [{ id: 'P1', cliente: 'José, "Zé"; Ávila' }], relatorio: null }));
  assert.ok(csv.includes('"Rua ""Ação"", 5; casa 2\nfundos"'));
  assert.ok(csv.includes('"José, ""Zé""; Ávila"'));
  assert.ok(csv.endsWith('\n'));
  assert.ok(csv.startsWith(BOM));
  assert.ok(!csv.slice(1).includes(BOM)); // o BOM aparece uma vez só
  assert.ok(!csv.slice(BOM.length).startsWith(BOM));
  const bytes = new TextEncoder().encode(csv);
  assert.deepEqual([...bytes.slice(0, 3)], [0xef, 0xbb, 0xbf]); // BOM UTF-8
  assert.equal(new TextDecoder('utf-8', { ignoreBOM: true }).decode(bytes), csv); // ida e volta em UTF-8 sem perder acentos
  // o mesmo arquivo dentro de um Blob text/csv;charset=utf-8 continua com um único BOM
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  assert.equal(blob.type, 'text/csv;charset=utf-8');
  assert.equal(blob.size, bytes.length);
  // um leitor de CSV simples com ";" (aspas e quebra de linha dentro de campo) enxerga 1 cabeçalho + 1 registro de 18 campos
  const registros = [];
  let campo = '';
  let campos = [];
  let aspas = false;
  const texto = csv.slice(BOM.length);
  for (let i = 0; i < texto.length; i += 1) {
    const c = texto[i];
    if (aspas) {
      if (c === '"' && texto[i + 1] === '"') { campo += '"'; i += 1; } else if (c === '"') aspas = false; else campo += c;
    } else if (c === '"') aspas = true;
    else if (c === SEPARADOR) { campos.push(campo); campo = ''; } else if (c === '\n') { campos.push(campo); registros.push(campos); campos = []; campo = ''; } else campo += c;
  }
  assert.equal(registros.length, 2);
  assert.ok(registros.every((r) => r.length === COLUNAS.length));
  assert.equal(registros[0][0], 'Rota');
  assert.equal(registros[1][5], 'Rua "Ação", 5; casa 2\nfundos');
  assert.equal(registros[1][11], 'José, "Zé"; Ávila');
});

test('separador é ponto e vírgula; latitude e longitude saem com vírgula decimal, sem aspas nem apóstrofo', () => {
  assert.equal(SEPARADOR, ';');
  const csv = montarCsv(dados());
  const primeira = csv.split('\n')[1].split(';');
  assert.equal(primeira.length, COLUNAS.length); // nenhum campo desta linha tem ";" dentro
  assert.equal(primeira[12], '-23,550500');
  assert.equal(primeira[13], '-46,633300');
  assert.ok(!/["']/.test(primeira[12] + primeira[13]));
  assert.equal(primeira[4], '1'); // Ordem_Parada número
  assert.equal(primeira[9], '2'); // Volume número
});

test('endereço com ";" não desloca as colunas e a linha antiga com vírgula continua bem escapada', () => {
  const rotas = [rota(1, 1, 'Ana', 'Carro de passeio', [parada('P1', { Endereco: 'Rua A; casa 2', Bairro: 'Centro, zona 1' })], [600, 600])];
  const linha = linhasDoRomaneio(dados({ rotas, relatorio: null }))[0];
  assert.equal(linha[5], '"Rua A; casa 2"');
  assert.equal(linha[7], '"Centro, zona 1"');
  assert.equal(linha.length, COLUNAS.length);
});

test('nome do arquivo continua o mesmo e o aviso deixa claro que a chegada é estimativa', () => {
  assert.equal(nomeDoArquivo('2026-10-22'), 'romaneio_expedicao_zubale_2026-10-22.csv');
  const rel = relatorioDeJanelas({ rotas: ROTAS, pedidos: PEDIDOS, loja: LOJA, turno: 'manha', tempoPorParada: 10 });
  assert.equal(avisoDoRomaneio(rel, 10), 'A chegada no arquivo é uma estimativa (saída às 08:00, 10 min por parada). O arquivo inclui o nome dos clientes.');
  const sem = relatorioDeJanelas({ rotas: ROTAS, pedidos: PEDIDOS, loja: null, turno: 'manha' });
  assert.match(avisoDoRomaneio(sem, 10), /em branco até você informar a hora de saída/);
  assert.match(avisoDoRomaneio(null, 10), /em branco/);
});

test('o código do romaneio não envia nada para fora nem fala de peso', () => {
  const fonte = readFileSync(new URL('./romaneio.js', import.meta.url), 'utf8');
  assert.doesNotMatch(fonte, /fetch\(|axios|localStorage|sessionStorage|console\./);
  assert.doesNotMatch(fonte.replace(/\/\/.*$/gm, ''), /peso/i);
});

test('coordenadas: vírgula decimal com 6 casas, negativas sem apóstrofo, arredondamento e campo vazio quando falta', () => {
  const rotas = [rota(1, 1, 'Ana', 'Carro de passeio', [
    parada('P1', { lat: -23.57674, lon: -46.710225 }), parada('P2', { lat: 23.5, lon: 46 }), parada('P3', { lat: -23.5767404999, lon: -46.7102259999 }),
    parada('P4', { lat: 0, lon: -0.0000004 }), parada('P5', { lat: null, lon: '' }), parada('P6', { lat: 'abc', lon: undefined }),
  ], [600, 600, 600, 600, 600, 600, 600])];
  const l = linhasDoRomaneio(dados({ rotas, relatorio: null }));
  assert.deepEqual(l.map((x) => [x[12], x[13]]), [
    ['-23,576740', '-46,710225'], ['23,500000', '46,000000'], ['-23,576740', '-46,710226'], ['0,000000', '-0,000000'], ['', ''], ['', ''],
  ]);
  assert.ok(l.every((x) => !/^'/.test(x[12]) && !/^'/.test(x[13]))); // a neutralização de "-" não atinge as coordenadas
  assert.ok(l.every((x) => !/"/.test(x[12] + x[13])));
});

test('nenhuma linha de dados tem "." dentro de Latitude ou Longitude (nem aspas), e as demais colunas numéricas seguem inteiras', () => {
  const csv = montarCsv(dados());
  const linhasDeDados = csv.slice(BOM.length).split('\n').slice(1, -1);
  assert.equal(linhasDeDados.length, 3);
  for (const linha of linhasDeDados) {
    const campos = linha.split(SEPARADOR);
    assert.equal(campos.length, COLUNAS.length);
    for (const i of [COLUNAS.indexOf('Latitude'), COLUNAS.indexOf('Longitude')]) {
      assert.ok(!campos[i].includes('.'), campos[i]);
      assert.match(campos[i], /^-?\d+,\d{6}$/);
    }
    assert.match(campos[COLUNAS.indexOf('Ordem_Parada')], /^\d+$/);
    assert.match(campos[COLUNAS.indexOf('Volume')], /^\d+$/);
  }
});
