// Lista de pedidos do lote (Etapa 7): filtro por loja, busca, seleção (caixa de marcar), paginação e o que vai para a
// roteirização. A data de entrega NÃO filtra nem muda nada (decisão do operador): é só informação opcional mostrada junto do pedido. Sem dependências, para ser testável com o `node --test`. O lote vive só na memória da tela (é temporário, descartado
// depois do uso). Cliente e endereço nunca vão para console, log nem mensagem: aqui só se filtra e se separa.
import { normalizarBusca } from './lojas.js';
import { estaJaRoteirizado } from './duplicidade.js';

export const MSG_ERRO_ENDERECO = 'Erro ao tentar encontrar endereço do pedido';
export const TAMANHO_PAGINA = 50;

/** O pedido vale para a loja escolhida? Sem loja escolhida, ou pedido sem loja no arquivo, vale para qualquer uma. */
export function pedidoDaLoja(pedido, lojaId) {
  if (lojaId === null || lojaId === undefined) return true;
  if (pedido.loja_id === null || pedido.loja_id === undefined) return true;
  return pedido.loja_id === lojaId;
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
 * Aplica a loja e a busca (o único filtro é o da loja). Devolve { visiveis, foraDaLoja, naLoja }: `foraDaLoja` conta os pedidos do
 * lote que ficaram de fora por serem de outra loja (para avisar o operador) e `naLoja` os que pertencem à loja escolhida.
 */
export function filtrarPedidos(pedidos, { lojaId = null, busca = '' } = {}) {
  const daLoja = pedidos.filter((p) => pedidoDaLoja(p, lojaId));
  return {
    visiveis: daLoja.filter((p) => pedidoCasaBusca(p, busca)),
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

/**
 * Marca todos os visíveis, menos os travados por erro de endereço e os que já estão em rota confirmada de hoje
 * (`jaRoteirizados`; esses só se marcam um a um, com a confirmação em duas etapas).
 */
export function marcarVisiveis(marcados, visiveis, comErro = new Set(), jaRoteirizados = null) {
  const novo = new Set(marcados);
  visiveis.forEach((p) => { if (!temErroDeEndereco(p, comErro) && !estaJaRoteirizado(jaRoteirizados, p.id)) novo.add(p.id); });
  return novo;
}

/** Quantos visíveis o "Marcar visíveis" deixa de fora por já estarem em rota de hoje (e ainda não estarem marcados). */
export function contarDeixadosDeFora(marcados, visiveis, comErro = new Set(), jaRoteirizados = null) {
  return visiveis.filter((p) => !marcados.has(p.id) && !temErroDeEndereco(p, comErro) && estaJaRoteirizado(jaRoteirizados, p.id)).length;
}

export function desmarcarVisiveis(marcados, visiveis) {
  const novo = new Set(marcados);
  visiveis.forEach((p) => novo.delete(p.id));
  return novo;
}

/** Todos os visíveis (que podem ser marcados) já estão marcados? */
export function todosVisiveisMarcados(marcados, visiveis, comErro = new Set(), jaRoteirizados = null) {
  const marcaveis = visiveis.filter((p) => !temErroDeEndereco(p, comErro) && (marcados.has(p.id) || !estaJaRoteirizado(jaRoteirizados, p.id)));
  return marcaveis.length > 0 && marcaveis.every((p) => marcados.has(p.id));
}

/**
 * Pedidos que entram no mapa e na roteirização: SÓ os marcados que valem para a loja escolhida (a busca não conta, a data nunca conta)
 * e que não estão travados por erro de endereço. Mantém a ordem do lote.
 */
export function pedidosParaRoteirizar(pedidos, marcados, { lojaId = null, comErro = new Set() } = {}) {
  return pedidos.filter((p) => marcados.has(p.id) && pedidoDaLoja(p, lojaId) && !temErroDeEndereco(p, comErro));
}

/**
 * Contador de marcados: `entram` (marcados que vão para a roteirização) e `foraDoFiltro` (marcados de OUTRA loja, que não entram).
 * Pedido travado por erro de endereço não conta como marcado.
 */
export function contarMarcados(pedidos, marcados, { lojaId = null, comErro = new Set() } = {}) {
  const marcadosValidos = pedidos.filter((p) => marcados.has(p.id) && !temErroDeEndereco(p, comErro));
  const entram = marcadosValidos.filter((p) => pedidoDaLoja(p, lojaId)).length;
  return { entram, foraDoFiltro: marcadosValidos.length - entram };
}

/** Texto do contador: "12 marcados" ou "12 marcados (3 fora do filtro atual)". */
export function textoDoContador({ entram, foraDoFiltro }) {
  return `${entram} marcado${entram === 1 ? '' : 's'}${foraDoFiltro > 0 ? ` (${foraDoFiltro} fora do filtro atual)` : ''}`;
}

/** Aviso curto antes de executar a roteirização quando há marcados de outra loja; null se não houver. */
export function avisoAntesDeExecutar(foraDoFiltro) {
  if (!foraDoFiltro) return null;
  return `${foraDoFiltro} pedido(s) marcado(s) são de outra loja e não entram nas rotas desta loja. Continuar mesmo assim?`;
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
