// Lista de pedidos do lote (Etapa 7): filtro por loja e data, busca, seleção (caixa de marcar), paginação e o que vai para a
// roteirização. Sem dependências, para ser testável com o `node --test`. O lote vive só na memória da tela (é temporário, descartado
// depois do uso). Cliente e endereço nunca vão para console, log nem mensagem: aqui só se filtra e se separa.
import { normalizarBusca } from './lojas.js';

export const MSG_ERRO_ENDERECO = 'Erro ao tentar encontrar endereço do pedido';
export const TODAS_AS_DATAS = '';
export const SEM_DATA = '__sem_data__';
export const TAMANHO_PAGINA = 50;

/** O pedido vale para a loja escolhida? Sem loja escolhida, ou pedido sem loja no arquivo, vale para qualquer uma. */
export function pedidoDaLoja(pedido, lojaId) {
  if (lojaId === null || lojaId === undefined) return true;
  if (pedido.loja_id === null || pedido.loja_id === undefined) return true;
  return pedido.loja_id === lojaId;
}

/** Datas de entrega do lote (ISO), em ordem. Sem nenhuma data, devolve lista vazia (e a tela mostra tudo). */
export function datasDoLote(pedidos) {
  return [...new Set(pedidos.map((p) => p.data_entrega).filter(Boolean))].sort();
}

/** Há pedidos sem data de entrega neste lote? (a tela oferece "Sem data" quando também há datas) */
export function temPedidoSemData(pedidos) {
  return pedidos.some((p) => !p.data_entrega);
}

export function pedidoNaData(pedido, data) {
  if (data === TODAS_AS_DATAS || data === null || data === undefined) return true;
  if (data === SEM_DATA) return !pedido.data_entrega;
  return pedido.data_entrega === data;
}

function textoDeBusca(pedido) {
  return normalizarBusca([pedido.id, pedido.cliente, pedido.endereco, pedido.numero, pedido.bairro, pedido.cidade].filter(Boolean).join(' '));
}

/** Busca por id, cliente ou endereço, sem diferença de maiúsculas nem acentos; todos os termos digitados precisam casar. */
export function pedidoCasaBusca(pedido, busca) {
  const termos = normalizarBusca(busca).split(' ').filter(Boolean);
  if (termos.length === 0) return true;
  const texto = textoDeBusca(pedido);
  return termos.every((t) => texto.includes(t));
}

/**
 * Aplica loja, data e busca. Devolve { visiveis, foraDaLoja, naLoja }: `foraDaLoja` conta os pedidos do lote que ficaram de fora
 * por serem de outra loja (para avisar o operador) e `naLoja` os que pertencem à loja escolhida.
 */
export function filtrarPedidos(pedidos, { lojaId = null, data = TODAS_AS_DATAS, busca = '' } = {}) {
  const daLoja = pedidos.filter((p) => pedidoDaLoja(p, lojaId));
  return {
    visiveis: daLoja.filter((p) => pedidoNaData(p, data) && pedidoCasaBusca(p, busca)),
    foraDaLoja: pedidos.length - daLoja.length,
    naLoja: daLoja.length,
  };
}

/** Pedido que a roteirização já não achou no mapa: fica fora (desmarcado e travado) até o operador corrigir o endereço. */
export const temErroDeEndereco = (pedido, comErro) => comErro instanceof Set && comErro.has(pedido.id);

export function alternarMarca(marcados, id) {
  const novo = new Set(marcados);
  if (novo.has(id)) novo.delete(id);
  else novo.add(id);
  return novo;
}

/** Marca todos os visíveis (menos os travados por erro de endereço). */
export function marcarVisiveis(marcados, visiveis, comErro = new Set()) {
  const novo = new Set(marcados);
  visiveis.forEach((p) => { if (!temErroDeEndereco(p, comErro)) novo.add(p.id); });
  return novo;
}

export function desmarcarVisiveis(marcados, visiveis) {
  const novo = new Set(marcados);
  visiveis.forEach((p) => novo.delete(p.id));
  return novo;
}

/** Todos os visíveis (que podem ser marcados) já estão marcados? */
export function todosVisiveisMarcados(marcados, visiveis, comErro = new Set()) {
  const marcaveis = visiveis.filter((p) => !temErroDeEndereco(p, comErro));
  return marcaveis.length > 0 && marcaveis.every((p) => marcados.has(p.id));
}

/**
 * Pedidos que entram no mapa e na roteirização: SÓ os marcados que valem para a loja e a data escolhidas (a busca não conta) e que
 * não estão travados por erro de endereço. Mantém a ordem do lote.
 */
export function pedidosParaRoteirizar(pedidos, marcados, { lojaId = null, data = TODAS_AS_DATAS, comErro = new Set() } = {}) {
  return pedidos.filter((p) => marcados.has(p.id) && pedidoDaLoja(p, lojaId) && pedidoNaData(p, data) && !temErroDeEndereco(p, comErro));
}

/** Formato que o servidor de roteirização espera. Não leva cliente, complemento nem observação: só o necessário para localizar a entrega. */
export function pedidoParaRoteirizacao(p) {
  return {
    id: p.id, Endereco: p.endereco, Numero: p.numero, Bairro: p.bairro || '', Cidade: p.cidade, UF: p.uf, CEP: p.cep || '', Volume: p.volume || 1,
  };
}

/** Ids dos pedidos que a roteirização não conseguiu localizar (resultado.pedidos_sem_geocodificacao). */
export function idsSemEndereco(resultado) {
  return new Set((resultado?.pedidos_sem_geocodificacao ?? []).map((p) => p.id));
}

/** Corrige o endereço de um pedido (só em memória) e o libera da trava; devolve o novo lote de pedidos e o novo conjunto de erros. */
export function corrigirEndereco(pedidos, comErro, id, campos) {
  const permitidos = ['endereco', 'numero', 'bairro', 'cidade', 'uf', 'cep'];
  const limpos = Object.fromEntries(permitidos.filter((c) => c in campos).map((c) => [c, String(campos[c] ?? '').trim()]));
  const novosErros = new Set(comErro);
  novosErros.delete(id);
  return { pedidos: pedidos.map((p) => (p.id === id ? { ...p, ...limpos } : p)), comErro: novosErros };
}

export function paginar(lista, pagina, tamanho = TAMANHO_PAGINA) {
  const totalPaginas = Math.max(1, Math.ceil(lista.length / tamanho));
  const atual = Math.min(Math.max(1, pagina), totalPaginas);
  return { itens: lista.slice((atual - 1) * tamanho, atual * tamanho), pagina: atual, totalPaginas };
}

/** '2026-10-21' -> '21/10/2026' (sem passar por Date, para não mudar o dia por fuso horário). */
export function dataParaExibir(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
  return m ? `${m[3]}/${m[2]}/${m[1]}` : '';
}

/** Motivos agrupados por linha para o relatório, em texto curto: "Linha 12 (id 99): motivo; motivo". */
export function textoDoErro(erro) {
  return `Linha ${erro.linha}${erro.id ? ` (id ${erro.id})` : ''}: ${erro.motivos.join('; ')}`;
}
