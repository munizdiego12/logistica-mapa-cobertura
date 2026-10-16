// Motoristas (Etapa 6b): telefone (conferência e máscara), busca, filtros, paginação e a escolha da roteirização
// ("Desta loja" primeiro, "Outros motoristas" depois). Sem dependências, para ser testável com o `node --test`.
// O servidor confere tudo de novo. Telefone é dado pessoal: nenhuma mensagem daqui repete o número digitado.
import { normalizarBusca } from './lojas.js';

export const POR_PAGINA = 50;
export const LIMITE_DA_LISTA = 60;

export const MSG_TELEFONE_INVALIDO = 'O telefone não parece válido. Use o DDD e o número, por exemplo (11) 98765-4321.';
export const MSG_TELEFONE_SEM_DDD = 'O telefone precisa ter o DDD, por exemplo (11) 98765-4321.';

const DDDS_VALIDOS = new Set(
  ('11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 41 42 43 44 45 46 47 48 49 51 53 54 55 '
   + '61 62 63 64 65 66 67 68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89 91 92 93 94 95 96 97 98 99').split(' '),
);

/**
 * Confere o telefone digitado (mesma regra do servidor). Vazio é válido (telefone é opcional).
 * Devolve { ok, vazio, digitos, mensagem }; `digitos` já sem +55, 0 do DDD, parênteses, traços e espaços.
 */
export function validarTelefone(texto) {
  const bruto = String(texto ?? '').trim();
  if (bruto === '') return { ok: true, vazio: true, digitos: '', mensagem: '' };
  const invalido = { ok: false, vazio: false, digitos: '', mensagem: MSG_TELEFONE_INVALIDO };
  if (/[^\d\s()+\-.]/.test(bruto)) return invalido;
  let digitos = bruto.replace(/\D/g, '');
  if ((digitos.length === 12 || digitos.length === 13) && digitos.startsWith('55')) digitos = digitos.slice(2);
  else if ((digitos.length === 11 || digitos.length === 12) && digitos.startsWith('0')) digitos = digitos.slice(1);
  if (digitos.length === 8 || digitos.length === 9) return { ...invalido, mensagem: MSG_TELEFONE_SEM_DDD };
  if ((digitos.length !== 10 && digitos.length !== 11) || !DDDS_VALIDOS.has(digitos.slice(0, 2))) return invalido;
  const numero = digitos.slice(2);
  if (digitos.length === 11 && numero[0] !== '9') return invalido;
  if (digitos.length === 10 && !'2345'.includes(numero[0])) return invalido;
  return { ok: true, vazio: false, digitos, mensagem: '' };
}

/** "(11) *****-1234" (11 dígitos) ou "(11) ****-1234" (10 dígitos). Sem telefone: ''. */
export function mascararTelefone(telefone) {
  const digitos = String(telefone ?? '').replace(/\D/g, '');
  if (digitos.length !== 10 && digitos.length !== 11) return '';
  return `(${digitos.slice(0, 2)}) ${'*'.repeat(digitos.length - 6)}-${digitos.slice(-4)}`;
}

/** Telefone completo para mostrar só na tela de edição: "(11) 91234-5678". */
export function formatarTelefone(digitos) {
  const d = String(digitos ?? '').replace(/\D/g, '');
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return d;
}

// ---------------------------------------------------------------------------------------------- busca e filtros
const compacto = (texto) => normalizarBusca(texto).replace(/[^a-z0-9]/g, '');
const cacheDeTexto = new WeakMap();

/** Texto onde a busca procura: nome e código (sem acentos, maiúsculas, espaços nem traços). */
export function textoDeBuscaDoMotorista(motorista) {
  if (motorista && typeof motorista === 'object') {
    const guardado = cacheDeTexto.get(motorista);
    if (guardado !== undefined) return guardado;
  }
  const nome = normalizarBusca(motorista?.nome);
  const codigo = normalizarBusca(motorista?.codigo);
  const texto = `${nome} ${codigo} ${compacto(motorista?.codigo)} ${compacto(motorista?.nome)}`;
  if (motorista && typeof motorista === 'object') cacheDeTexto.set(motorista, texto);
  return texto;
}

/** Todos os termos digitados precisam aparecer no nome ou no código ("mot 0001" acha "MOT-0001"; "joaosilva" acha "João Silva"). */
export function casaComABusca(motorista, busca) {
  const normalizada = normalizarBusca(busca);
  if (!normalizada) return true;
  const texto = textoDeBuscaDoMotorista(motorista);
  const junto = compacto(busca);
  return normalizada.split(' ').every((termo) => texto.includes(termo)) || (junto !== '' && texto.includes(junto));
}

export const SITUACOES = ['todos', 'ativos', 'desativados'];

/** Filtros da tela: busca (nome ou código), tipo de veículo, loja (id) e situação (todos | ativos | desativados). */
export function filtrarMotoristasDaTela(motoristas, { busca = '', tipo = '', lojaId = '', situacao = 'todos' } = {}) {
  const idLoja = lojaId === '' || lojaId === null || lojaId === undefined ? null : Number(lojaId);
  return (motoristas ?? []).filter((m) => {
    if (situacao === 'ativos' && !m.ativo) return false;
    if (situacao === 'desativados' && m.ativo) return false;
    if (tipo && m.tipo_veiculo !== tipo) return false;
    if (idLoja !== null && !(m.lojas ?? []).some((l) => l.id === idLoja)) return false;
    return casaComABusca(m, busca);
  });
}

/** Página `pagina` (1, 2, ...) da lista; a página pedida é ajustada para o que existe. */
export function paginar(lista, pagina = 1, porPagina = POR_PAGINA) {
  const total = (lista ?? []).length;
  const totalPaginas = Math.max(1, Math.ceil(total / porPagina));
  const atual = Math.min(Math.max(1, Number(pagina) || 1), totalPaginas);
  const inicio = (atual - 1) * porPagina;
  const itens = (lista ?? []).slice(inicio, inicio + porPagina);
  return { itens, pagina: atual, totalPaginas, total, de: total === 0 ? 0 : inicio + 1, ate: inicio + itens.length };
}

/** Lojas do motorista para a lista: "Atacadão A, Atacadão B +3". */
export function resumoDasLojas(lojas, maximo = 2) {
  const nomes = (lojas ?? []).map((l) => l.nome);
  if (nomes.length <= maximo) return nomes.join(', ');
  return `${nomes.slice(0, maximo).join(', ')} +${nomes.length - maximo}`;
}

// ---------------------------------------------------------------------------------------------- roteirização
export const TITULO_DESTA_LOJA = 'Desta loja';
export const TITULO_OUTROS = 'Outros motoristas';

/** Os motoristas (ativos) vinculados à loja, na ordem recebida. */
export function motoristasDaLoja(motoristas, lojaId) {
  if (lojaId === null || lojaId === undefined || lojaId === '') return [];
  const id = Number(lojaId);
  return (motoristas ?? []).filter((m) => m.ativo !== false && (m.lojas ?? []).some((l) => l.id === id));
}

/**
 * Opções da escolha da roteirização, já filtradas pela busca e limitadas a `limite` itens (a lista nunca renderiza os 500).
 * Com loja escolhida: grupo "Desta loja" primeiro e "Outros motoristas" depois (a busca alcança todos). Sem loja: um grupo só.
 * Devolve { grupos: [{ chave, titulo, itens }], total, mostrados, cortados } — `total` é quantos casaram com a busca.
 */
export function agruparParaRoteirizacao(motoristas, lojaId, busca = '', limite = LIMITE_DA_LISTA) {
  const ativos = (motoristas ?? []).filter((m) => m.ativo !== false && casaComABusca(m, busca));
  const daLoja = motoristasDaLoja(ativos, lojaId);
  const ids = new Set(daLoja.map((m) => m.id));
  const brutos = lojaId === null || lojaId === undefined || lojaId === ''
    ? [{ chave: 'todos', titulo: '', itens: ativos }]
    : [{ chave: 'loja', titulo: TITULO_DESTA_LOJA, itens: daLoja }, { chave: 'outros', titulo: TITULO_OUTROS, itens: ativos.filter((m) => !ids.has(m.id)) }];
  let restante = limite;
  const grupos = [];
  for (const grupo of brutos) {
    const itens = grupo.itens.slice(0, Math.max(0, restante));
    restante -= itens.length;
    if (itens.length > 0) grupos.push({ ...grupo, itens });
  }
  const mostrados = grupos.reduce((soma, g) => soma + g.itens.length, 0);
  return { grupos, total: ativos.length, mostrados, cortados: ativos.length - mostrados };
}

/** Aviso do rodapé da lista quando há mais resultados do que cabem: "Mostrando 60 de 500; digite para refinar." */
export function avisoDeLimite({ mostrados, total }) {
  return total > mostrados ? `Mostrando ${mostrados} de ${total}. Digite para refinar.` : '';
}
