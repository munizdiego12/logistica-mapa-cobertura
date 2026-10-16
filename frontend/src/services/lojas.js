// Lojas (Etapa 6a): conferências do formulário, texto do hover do marcador e raio do "Raio X km".
// Sem dependências, para ser testável com o `node --test` do Node. O servidor confere tudo de novo.
//
// A filial já faz parte do nome da loja (ex.: "Atacadão Guarujá"): não existe campo filial.

export const LAT_MIN = -34;
export const LAT_MAX = 6;
export const LNG_MIN = -74;
export const LNG_MAX = -34;
export const RAIO_PADRAO_KM = 30;
export const RAIO_MINIMO_KM = 1;
export const RAIO_MAXIMO_KM = 200;

export const UFS = [
  'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ',
  'RN', 'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO',
];

export const FORMULARIO_VAZIO = {
  nome: '', uf: '', endereco: '', cidade: '', lat: '', lng: '', capacidade_peso: '', capacidade_volume: '',
  janela_manha_inicio: '08:00', janela_manha_fim: '13:00', janela_tarde_inicio: '13:00', janela_tarde_fim: '18:00',
  usa_noite: true, janela_noite_inicio: '18:00', janela_noite_fim: '21:00', ativo: true,
};

/** Número com vírgula ou ponto decimal ("-23,5614"). Devolve null se não for número. */
export function numeroPtBr(texto) {
  const t = String(texto ?? '').replace('−', '-').trim().replace(/\s/g, '');
  if (!/^-?[0-9.,]+$/.test(t)) return null;
  let normal = t;
  if (t.includes(',') && t.includes('.')) {
    normal = t.lastIndexOf(',') > t.lastIndexOf('.') ? t.replace(/\./g, '').replace(',', '.') : t.replace(/,/g, '');
  } else if (t.includes(',')) {
    normal = t.replace(',', '.');
  } else if ((t.match(/\./g) || []).length > 1) {
    return null;
  }
  if (!/^-?\d+(\.\d+)?$/.test(normal)) return null;
  return Number(normal);
}

/** 'ok', 'trocadas' (só ficam no Brasil se trocadas entre si) ou 'fora_do_brasil'. */
export function classificarCoordenadas(lat, lng) {
  const noBrasil = (la, ln) => la >= LAT_MIN && la <= LAT_MAX && ln >= LNG_MIN && ln <= LNG_MAX;
  if (noBrasil(lat, lng)) return 'ok';
  if (noBrasil(lng, lat)) return 'trocadas';
  return 'fora_do_brasil';
}

/** Confere latitude e longitude digitadas: ilegíveis, fora do Brasil ou trocadas. */
export function validarCoordenadas(latTexto, lngTexto) {
  const lat = numeroPtBr(latTexto);
  if (lat === null) return { ok: false, campo: 'lat', mensagem: 'A latitude precisa ser um número, por exemplo -23,5614.' };
  const lng = numeroPtBr(lngTexto);
  if (lng === null) return { ok: false, campo: 'lng', mensagem: 'A longitude precisa ser um número, por exemplo -46,6333.' };
  const estado = classificarCoordenadas(lat, lng);
  if (estado === 'trocadas') {
    return {
      ok: false, campo: 'lat',
      mensagem: 'A latitude e a longitude parecem estar trocadas. No Brasil a latitude fica entre -34 e 6 e a longitude entre -74 e -34: troque os dois valores.',
    };
  }
  if (estado === 'fora_do_brasil') {
    return { ok: false, campo: 'lat', mensagem: 'A latitude e a longitude estão fora do Brasil (latitude entre -34 e 6 e longitude entre -74 e -34). Confira os valores.' };
  }
  return { ok: true, lat, lng };
}

/** Endereço para mostrar no hover: sem o ", Brazil" ou ", Brasil" do final, se existir (o dado guardado não muda). */
export function enderecoParaExibir(endereco) {
  const texto = String(endereco ?? '').trim().replace(/\s+/g, ' ');
  return texto.replace(/(^|\s*,)\s*(brasil|brazil)\s*\.?\s*$/i, '').replace(/^[\s,]+|[\s,]+$/g, '');
}

/** Linhas do hover do marcador: nome, endereço (sem o país no final) e UF, uma informação por linha e só o que existir. */
export function linhasDoHover(loja) {
  return [loja?.nome, enderecoParaExibir(loja?.endereco), loja?.uf].map((t) => String(t ?? '').trim()).filter(Boolean);
}

/** Raio do "Raio X km": vazio vale o padrão (30); precisa ficar entre 1 e 200. */
export function interpretarRaio(texto) {
  const bruto = String(texto ?? '').trim();
  if (bruto === '') return { ok: true, valor: RAIO_PADRAO_KM };
  const valor = numeroPtBr(bruto);
  if (valor === null || valor < RAIO_MINIMO_KM || valor > RAIO_MAXIMO_KM) {
    return { ok: false, mensagem: 'O raio precisa ficar entre 1 e 200 km.' };
  }
  return { ok: true, valor };
}

const HORA = /^([01]?\d|2[0-3]):[0-5]\d$/;

/** Confere o formulário de loja. Devolve { ok, erros: { campo: mensagem } } em linguagem do operador. */
export function validarFormularioLoja(form) {
  const erros = {};
  if (!String(form.nome ?? '').trim()) erros.nome = 'Informe o nome da loja.';
  if (String(form.cidade ?? '').trim().length > 120) erros.cidade = 'O nome da cidade pode ter até 120 letras.';
  if (String(form.uf ?? '').trim() && !UFS.includes(String(form.uf).trim().toUpperCase())) erros.uf = 'Estado inválido. Use a sigla (ex.: SP).';
  const coordenadas = validarCoordenadas(form.lat, form.lng);
  if (!coordenadas.ok) erros[coordenadas.campo] = coordenadas.mensagem;
  for (const [campo, rotulo] of [['capacidade_peso', 'peso'], ['capacidade_volume', 'volume']]) {
    const texto = String(form[campo] ?? '').trim();
    if (texto !== '') {
      const n = numeroPtBr(texto);
      if (n === null || n <= 0) erros[campo] = `A capacidade de ${rotulo} precisa ser um número maior que zero (ou deixe em branco).`;
    }
  }
  const turnos = [['manha', 'manhã'], ['tarde', 'tarde']];
  if (form.usa_noite) turnos.push(['noite', 'noite']);
  for (const [turno, rotulo] of turnos) {
    const inicio = String(form[`janela_${turno}_inicio`] ?? '').trim();
    const fim = String(form[`janela_${turno}_fim`] ?? '').trim();
    if (!HORA.test(inicio) || !HORA.test(fim)) {
      erros[`janela_${turno}`] = `Informe os horários da ${rotulo} no formato 08:00.`;
    } else if (inicio.padStart(5, '0') >= fim.padStart(5, '0')) {
      erros[`janela_${turno}`] = `Na janela da ${rotulo}, o início precisa ser antes do fim.`;
    }
  }
  return { ok: Object.keys(erros).length === 0, erros };
}

/** Corpo enviado ao servidor (campos vazios viram null; vírgula decimal segue como digitada, o servidor entende). */
export function corpoDaLoja(form) {
  const vazioParaNulo = (v) => (String(v ?? '').trim() === '' ? null : String(v).trim());
  return {
    nome: String(form.nome ?? '').trim(),
    uf: vazioParaNulo(form.uf) ? String(form.uf).trim().toUpperCase() : null,
    endereco: vazioParaNulo(form.endereco),
    cidade: vazioParaNulo(form.cidade),
    lat: String(form.lat ?? '').trim(),
    lng: String(form.lng ?? '').trim(),
    ativo: form.ativo !== false,
    capacidade_peso: vazioParaNulo(form.capacidade_peso),
    capacidade_volume: vazioParaNulo(form.capacidade_volume),
    janela_manha_inicio: form.janela_manha_inicio,
    janela_manha_fim: form.janela_manha_fim,
    janela_tarde_inicio: form.janela_tarde_inicio,
    janela_tarde_fim: form.janela_tarde_fim,
    usa_noite: Boolean(form.usa_noite),
    janela_noite_inicio: form.usa_noite ? form.janela_noite_inicio : null,
    janela_noite_fim: form.usa_noite ? form.janela_noite_fim : null,
  };
}

/** Formulário preenchido a partir de uma loja do servidor. */
export function formularioDaLoja(loja) {
  const texto = (v) => (v === null || v === undefined ? '' : String(v).replace('.', ','));
  return {
    nome: loja.nome ?? '', uf: loja.uf ?? '', endereco: loja.endereco ?? '', cidade: loja.cidade ?? '', lat: texto(loja.lat), lng: texto(loja.lng),
    capacidade_peso: texto(loja.capacidade_peso), capacidade_volume: texto(loja.capacidade_volume),
    janela_manha_inicio: loja.janela_manha_inicio ?? '08:00', janela_manha_fim: loja.janela_manha_fim ?? '13:00',
    janela_tarde_inicio: loja.janela_tarde_inicio ?? '13:00', janela_tarde_fim: loja.janela_tarde_fim ?? '18:00',
    usa_noite: loja.usa_noite !== false && Boolean(loja.janela_noite_inicio),
    janela_noite_inicio: loja.janela_noite_inicio ?? '18:00', janela_noite_fim: loja.janela_noite_fim ?? '21:00',
    ativo: loja.ativo !== false,
  };
}

/** Texto do hub escolhido para nomes de arquivo e avisos: a loja (nome já traz a filial) ou o logradouro digitado. */
export function nomeDoHub(loja, origem, cidade) {
  return (loja?.nome || origem?.rua || cidade || 'hub');
}

// ----------------------------------------------------------------------------------------------------------
// Pesquisa de lojas (campo com lista): normalização e filtro
// ----------------------------------------------------------------------------------------------------------
export const ROTULO_OUTRO_ENDERECO = 'Outro endereço';
const MARCAS_DE_ACENTO = /[̀-ͯ]/g;
const UFS_EM_MINUSCULAS = UFS.map((uf) => uf.toLowerCase());

/** Texto para comparar: sem acentos, em minúsculas e com espaços simples ("  Guarujá " -> "guaruja"). */
export function normalizarBusca(texto) {
  return String(texto ?? '').normalize('NFD').replace(MARCAS_DE_ACENTO, '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function palavras(textoNormalizado) {
  return textoNormalizado ? textoNormalizado.split(' ') : [];
}

const comecaUmaPalavra = (textoNormalizado, trecho) => palavras(textoNormalizado).some((p) => p.startsWith(trecho));

/**
 * Pontuação de UM termo da busca em uma loja, ou 0 se não casa. Casa por nome, cidade e UF:
 * a sigla do Estado (2 letras, ex.: "sp") vale como UF (ou início de palavra do nome/cidade), não como pedaço no meio de uma palavra.
 */
function pontosDoTermo(termo, nome, cidade, uf) {
  if (termo.length === 2 && UFS_EM_MINUSCULAS.includes(termo)) {
    if (uf === termo) return 4;
    if (comecaUmaPalavra(nome, termo)) return 3;
    if (comecaUmaPalavra(cidade, termo)) return 2;
    return 0;
  }
  if (comecaUmaPalavra(nome, termo)) return 3;
  if (comecaUmaPalavra(cidade, termo)) return 2;
  if (nome.includes(termo) || cidade.includes(termo)) return 1;
  return 0;
}

/**
 * Filtra as lojas pela busca (nome, cidade e UF; sem diferença de maiúsculas, acentos nem espaços extras). Todos os termos
 * digitados precisam casar. Devolve [{ loja, pontos }], as que casam melhor primeiro e, empatando, em ordem de nome.
 * Busca vazia devolve todas, em ordem de nome.
 */
export function filtrarLojas(lojas, busca) {
  const termos = palavras(normalizarBusca(busca));
  const comPontos = [];
  for (const loja of lojas ?? []) {
    const nome = normalizarBusca(loja.nome);
    const cidade = normalizarBusca(loja.cidade);
    const uf = normalizarBusca(loja.uf);
    let total = 0;
    let casou = true;
    for (const termo of termos) {
      const pontos = pontosDoTermo(termo, nome, cidade, uf);
      if (pontos === 0) { casou = false; break; }
      total += pontos;
    }
    if (casou) comPontos.push({ loja, pontos: total });
  }
  return comPontos.sort((a, b) => b.pontos - a.pontos || String(a.loja.nome).localeCompare(String(b.loja.nome), 'pt-BR'));
}

/** Linha pequena da lista: "Guarujá · SP" (só o que existir). */
export function cidadeEUf(loja) {
  return [loja?.cidade, loja?.uf].map((t) => String(t ?? '').trim()).filter(Boolean).join(' · ');
}

/**
 * Divide o texto em trechos [{ texto, destaque }] marcando as partes que casam com a busca (sem diferença de maiúsculas
 * nem acentos): "guaruja" em "Atacadão Guarujá" destaca "Guarujá".
 */
export function destacarTrechos(texto, busca) {
  const original = String(texto ?? '');
  const termos = palavras(normalizarBusca(busca));
  if (!original || termos.length === 0) return [{ texto: original, destaque: false }];
  let normal = '';
  const origem = []; // posição no texto original de cada letra do texto normalizado
  for (let i = 0; i < original.length; i += 1) {
    const base = original[i].normalize('NFD').replace(MARCAS_DE_ACENTO, '').toLowerCase();
    for (const letra of base) { normal += letra; origem.push(i); }
  }
  const eMarca = (caractere) => /[̀-ͯ]/.test(caractere);
  const faixas = [];
  for (const termo of termos) {
    let de = normal.indexOf(termo);
    while (de !== -1) {
      let fim = origem[de + termo.length - 1] + 1;
      while (fim < original.length && eMarca(original[fim])) fim += 1; // acento solto depois da letra
      faixas.push([origem[de], fim]);
      de = normal.indexOf(termo, de + 1);
    }
  }
  if (faixas.length === 0) return [{ texto: original, destaque: false }];
  faixas.sort((a, b) => a[0] - b[0]);
  const unidas = [faixas[0].slice()];
  for (const [inicio, fim] of faixas.slice(1)) {
    const ultima = unidas[unidas.length - 1];
    if (inicio <= ultima[1]) ultima[1] = Math.max(ultima[1], fim);
    else unidas.push([inicio, fim]);
  }
  const trechos = [];
  let cursor = 0;
  for (const [inicio, fim] of unidas) {
    if (inicio > cursor) trechos.push({ texto: original.slice(cursor, inicio), destaque: false });
    trechos.push({ texto: original.slice(inicio, fim), destaque: true });
    cursor = fim;
  }
  if (cursor < original.length) trechos.push({ texto: original.slice(cursor), destaque: false });
  return trechos;
}

/** Move o item em destaque da lista com as setas, dando a volta nas pontas. */
export function moverDestaque(indice, passo, total) {
  if (total <= 0) return -1;
  if (indice < 0) return passo > 0 ? 0 : total - 1;
  return (indice + passo + total) % total;
}
