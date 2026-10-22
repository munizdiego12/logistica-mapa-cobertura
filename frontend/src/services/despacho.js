// Matriz de despacho (Etapa 10): troca do motorista de cada rota, alternativas, selo de rotação, avisos e totais. Só funções puras, sem dependências de tela.
// O resultado da roteirização fica INTACTO como "sugestão do solver"; o ajuste do operador é um mapa { id_da_rota: motorista_id } por cima dele, e todas as
// telas (tabela, cartão, mapa, romaneio) leem as "rotas efetivas" calculadas aqui. Trocar nunca bloqueia: rotação, carga e teto só viram aviso. O peso não entra.
// Nada aqui guarda nem mostra telefone, pedido, endereço ou cliente.
import { textoRotasHoje, textoPedidos, motoristasMarcados, rotasPorMotoristaDoResultado } from './selecaoMotoristas.js';
import { motoristasDaLoja } from './motoristas.js';
import { normalizarBusca } from './lojas.js';

export const LIMITE_DE_ALTERNATIVAS = 60;
export const TITULO_MARCADOS = 'Marcados nesta roteirização';
export const TITULO_OUTROS_DA_LOJA = 'Outros motoristas desta loja';
export const MSG_TROCA_TRAVADA = 'Desfaça a confirmação para trocar o motorista.';
export const MSG_AJUSTES_E_REINICIO = 'Se o servidor reiniciar antes de confirmar, será preciso gerar as rotas de novo e os ajustes feitos à mão se perdem.';
export const MSG_SEM_ROTACAO = 'Não foi possível conferir agora as regiões que cada motorista já fez hoje; o selo de rotação não aparece.';

const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
const chave = (id) => String(id);
const numero = (valor) => Number(valor);

const listaDeRegioes = (regioes) => (regioes.length === 1
  ? `a região ${regioes[0]}`
  : `as regiões ${regioes.slice(0, -1).join(', ')} e ${regioes[regioes.length - 1]}`);

/** Regiões da rota que o motorista já fez hoje em outro turno. Sem a conferência (`rotacao` nulo), vale o que o solver já tinha marcado na rota. */
export function regioesRepetidas(rota, rotacao) {
  if (!rotacao) return [...(rota.violacoes_rotacao ?? [])];
  const feitas = rotacao[chave(rota.motorista_id)] ?? {};
  return (rota.setores ?? []).filter((s) => Object.prototype.hasOwnProperty.call(feitas, s));
}

/** "repete a região N em outro turno" / "repete as regiões N e NE em outro turno"; null se não repete. */
export function seloDeRotacao(regioes) {
  if (!regioes || regioes.length === 0) return null;
  return `repete ${listaDeRegioes(regioes)} em outro turno`;
}

/**
 * As rotas como valem depois dos ajustes: motorista, nome, veículo e título ("Ana • Viagem 2") do motorista final; `ajustada` marca a rota trocada.
 * Quem não foi tocado por nenhuma troca (nem para onde, nem de onde) fica exatamente como o solver devolveu. A marca "Rota personalizada" só vale
 * enquanto a rota está com o motorista sugerido. Não altera o que recebe.
 */
export function rotasEfetivas(rotas, atribuicoes, motoristas) {
  const porId = new Map((motoristas ?? []).map((m) => [m.id, m]));
  const ajustes = atribuicoes ?? {};
  const tocados = new Set();
  const trocadas = (rotas ?? []).map((rota) => {
    const novo = ajustes[chave(rota.id)];
    const destino = novo === undefined || novo === null ? undefined : porId.get(numero(novo));
    if (!destino || destino.id === rota.motorista_id) return { ...rota, ajustada: false, motorista_id_sugerido: rota.motorista_id };
    tocados.add(rota.motorista_id);
    tocados.add(destino.id);
    return {
      ...rota, ajustada: true, motorista_id_sugerido: rota.motorista_id, motorista_id: destino.id, motorista_base: destino.nome,
      modal: destino.tipo_veiculo ?? rota.modal, rota_personalizada: false, violacoes_rotacao: [],
    };
  });
  const contagem = new Map();
  trocadas.forEach((r) => contagem.set(r.motorista_id, (contagem.get(r.motorista_id) ?? 0) + 1));
  const vistas = new Map();
  return trocadas.map((r) => {
    if (!tocados.has(r.motorista_id)) return r;
    const viagem = (vistas.get(r.motorista_id) ?? 0) + 1;
    vistas.set(r.motorista_id, viagem);
    return { ...r, viagem_num: viagem, motorista: contagem.get(r.motorista_id) > 1 ? `${r.motorista_base} • Viagem ${viagem}` : r.motorista_base };
  });
}

/** Troca o motorista de uma rota; escolher o sugerido remove o ajuste. Devolve um mapa novo. */
export function trocarMotorista(atribuicoes, rotas, rotaId, motoristaId) {
  const novo = { ...(atribuicoes ?? {}) };
  const rota = (rotas ?? []).find((r) => r.id === rotaId);
  if (!rota || numero(motoristaId) === rota.motorista_id) delete novo[chave(rotaId)];
  else novo[chave(rotaId)] = numero(motoristaId);
  return novo;
}

/** "Voltar à sugestão": de uma rota (com `rotaId`) ou de todas (sem). Devolve um mapa novo. */
export function voltarASugestao(atribuicoes, rotaId = null) {
  if (rotaId === null || rotaId === undefined) return {};
  const novo = { ...(atribuicoes ?? {}) };
  delete novo[chave(rotaId)];
  return novo;
}

/** Só os ajustes que realmente mudam o motorista de uma rota existente para um motorista conhecido: { id_da_rota: motorista_id }. */
export function ajustesValidos(rotas, atribuicoes, motoristas) {
  const efetivas = rotasEfetivas(rotas, atribuicoes, motoristas);
  return Object.fromEntries(efetivas.filter((r) => r.ajustada).map((r) => [chave(r.id), r.motorista_id]));
}

export const quantasAjustadas = (rotas) => (rotas ?? []).filter((r) => r.ajustada).length;

/** Corpo do "Confirmar rotas": só leva `atribuicoes` quando há rota ajustada (senão fica igual ao formato antigo). */
export function corpoDaConfirmacao(execucaoId, rotas, atribuicoes, motoristas) {
  const ajustes = ajustesValidos(rotas, atribuicoes, motoristas);
  return Object.keys(ajustes).length > 0 ? { execucao_id: execucaoId, atribuicoes: ajustes } : { execucao_id: execucaoId };
}

/** "nenhuma rota nesta roteirização" ou "já tem 2 rotas nesta roteirização (10 pedidos)". */
export function textoNestaRoteirizacao(rotas, pedidos) {
  if (!rotas) return 'nenhuma rota nesta roteirização';
  return `já tem ${plural(rotas, 'rota', 'rotas')} nesta roteirização (${textoPedidos(pedidos)})`;
}

/**
 * Alternativas de motorista para uma rota, filtradas e ordenadas: grupo "Marcados nesta roteirização" (ativos marcados, mais o motorista atual) e, com loja
 * escolhida, "Outros motoristas desta loja" (ativos vinculados à loja e não marcados; nada é marcado sozinho). Dentro de cada grupo: o atual primeiro, depois
 * quem NÃO repete região, depois quem tem menos rotas (hoje + nesta roteirização) e por fim o nome. `busca` filtra por nome ou código; cada grupo mostra
 * no máximo LIMITE_DE_ALTERNATIVAS (`maisNaoMostrados` diz quantos ficaram de fora). Inativos nunca aparecem. Sem telefone no resultado.
 */
export function alternativasParaRota({ rota, rotas, motoristas, selecionados, lojaId = null, rotasHoje = {}, pedidosHoje = {}, rotacao = null, busca = '' }) {
  const ativos = (motoristas ?? []).filter((m) => m.ativo !== false);
  const marcados = motoristasMarcados(ativos, selecionados);
  const idsMarcados = new Set(marcados.map((m) => m.id));
  const outros = motoristasDaLoja(ativos, lojaId).filter((m) => !idsMarcados.has(m.id));
  const atual = ativos.find((m) => m.id === rota.motorista_id);
  const doGrupoMarcados = atual && !idsMarcados.has(atual.id) && !outros.some((m) => m.id === atual.id) ? [...marcados, atual] : marcados;
  const termo = normalizarBusca(busca);

  const monta = (m) => {
    const dele = (rotas ?? []).filter((r) => r.motorista_id === m.id && r.id !== rota.id);
    const pedidos = dele.reduce((s, r) => s + (Number(r.qtd_pedidos) || 0), 0);
    const hoje = Number(rotasHoje[chave(m.id)]) || 0;
    const regioes = regioesRepetidas({ ...rota, motorista_id: m.id, violacoes_rotacao: [] }, rotacao ?? {});
    return {
      id: m.id, nome: m.nome, codigo: m.codigo || '', tipo: m.tipo_veiculo || '', atual: m.id === rota.motorista_id, sugerido: m.id === rota.motorista_id_sugerido,
      textoHoje: textoRotasHoje(hoje, Number(pedidosHoje[chave(m.id)]) || 0), textoNesta: textoNestaRoteirizacao(dele.length, pedidos),
      selo: rotacao ? seloDeRotacao(regioes) : null, repete: rotacao ? regioes.length > 0 : false, carga: hoje + dele.length,
    };
  };
  const ordem = (a, b) => (Number(b.atual) - Number(a.atual)) || (Number(a.repete) - Number(b.repete)) || (a.carga - b.carga) || a.nome.localeCompare(b.nome, 'pt-BR');
  const grupo = (id, titulo, lista) => {
    const itens = lista
      .filter((m) => !termo || normalizarBusca(`${m.nome} ${m.codigo ?? ''}`).includes(termo))
      .map(monta).sort(ordem);
    return { chave: id, titulo, itens: itens.slice(0, LIMITE_DE_ALTERNATIVAS), maisNaoMostrados: Math.max(0, itens.length - LIMITE_DE_ALTERNATIVAS) };
  };
  return [grupo('marcados', TITULO_MARCADOS, doGrupoMarcados), grupo('outros', TITULO_OUTROS_DA_LOJA, outros)].filter((g) => g.itens.length > 0);
}

/** Cartão "Rotas por Motorista" depois dos ajustes: quem tem rota nesta roteirização e, com 0, os marcados que ficaram sem rota. */
export function linhasDoCartao(rotas, marcados) {
  const linhas = rotasPorMotoristaDoResultado(rotas);
  const ids = new Set(linhas.map((l) => l.motorista_id));
  const semRota = (marcados ?? []).filter((m) => !ids.has(m.id)).map((m) => ({ motorista_id: m.id, nome: m.nome, rotas: 0, pedidos: 0 }));
  return [...linhas, ...semRota];
}

/** Avisos de rotação (informativos) de todas as rotas, no mesmo texto que o servidor devolve ao confirmar. Sem a conferência (`rotacao` nulo), nenhum. */
export function avisosDeRotacao(rotas, rotacao) {
  if (!rotacao) return [];
  return (rotas ?? []).flatMap((r) => {
    const regioes = regioesRepetidas(r, rotacao);
    return regioes.length === 0 ? [] : [{ tipo: 'rotacao', gravidade: 'atencao', mensagem: `Rota ${r.id}: ${r.motorista_base || r.motorista} já fez ${listaDeRegioes(regioes)} em outro turno hoje.` }];
  });
}

/** Aviso (nunca bloqueio) quando, depois de trocas, a diferença de pedidos entre o motorista mais e o menos carregado passa de max(3, metade da média). */
export function avisoDeCargaDesigual(linhas) {
  if (!linhas || linhas.length < 2) return null;
  const media = linhas.reduce((s, l) => s + l.pedidos, 0) / linhas.length;
  const maior = linhas.reduce((a, b) => (b.pedidos > a.pedidos ? b : a));
  const menor = linhas.reduce((a, b) => (b.pedidos < a.pedidos ? b : a));
  if (maior.pedidos - menor.pedidos <= Math.max(3, media / 2)) return null;
  return { tipo: 'carga_desigual', gravidade: 'atencao', mensagem: `A carga ficou desigual: ${maior.nome} com ${textoPedidos(maior.pedidos)} e ${menor.nome} com ${textoPedidos(menor.pedidos)}.` };
}

/** Avisos do teto recomendado do tipo de veículo só para as rotas trocadas (a quantidade de pedidos, nunca o peso). `capacidades`: { tipo: pedidos por viagem }. */
export function avisosDeTeto(rotas, capacidades) {
  return (rotas ?? []).filter((r) => r.ajustada).flatMap((r) => {
    const teto = Number(capacidades?.[r.modal]);
    if (!teto || r.qtd_pedidos <= teto) return [];
    return [{ tipo: 'teto_da_troca', gravidade: 'atencao', mensagem: `Rota ${r.id}: ${textoPedidos(r.qtd_pedidos)}; o recomendado para ${r.modal} é ${teto} por viagem.` }];
  });
}

/**
 * Avisos da tela depois dos ajustes: os do solver (com a rotação recalculada quando a conferência está disponível) mais, só com rota trocada,
 * carga desigual e teto. Tudo informativo.
 */
export function avisosDoDespacho({ avisosDoSolver, rotas, rotacao, capacidades, marcados }) {
  const base = (avisosDoSolver ?? []).filter((a) => !(rotacao && a.tipo === 'rotacao'));
  const novos = [...avisosDeRotacao(rotas, rotacao)];
  if (quantasAjustadas(rotas) > 0) {
    novos.push(...avisosDeTeto(rotas, capacidades));
    const desigual = avisoDeCargaDesigual(linhasDoCartao(rotas, marcados));
    if (desigual) novos.push(desigual);
  }
  return [...base, ...novos];
}
