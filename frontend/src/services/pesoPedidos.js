// Peso por pedido, por viagem, por motorista e por tipo de veículo (subetapa 3 do peso). Só funções puras, calculadas na tela.
// INFORMATIVO: sempre estimado, nunca bloqueia, nunca avisa por capacidade, nunca mexe no solver, no agrupamento nem na ordem das paradas, e o peso de
// referência do veículo não entra. Os itens (do arquivo opcional de itens) e os pesos (do cadastro) vivem só na memória da tela, junto do lote; nada daqui
// vai para console, log nem armazenamento do navegador.
//
// Formatos: itens = { [idDoPedido]: [{ sku, quantidade }] }; pesos = { [sku]: { peso_kg: número ou null, confianca } } (sku que não está em `pesos` não existe no cadastro).
// Peso do pedido = soma de quantidade x peso do item. Item sem peso (ou fora do cadastro) deixa o pedido "incompleto"; pedido sem nenhum item no arquivo
// é "sem itens" (peso desconhecido, NUNCA 0 kg).

export const TAMANHO_BLOCO_SKUS_VISTOS = 5000;
export const TAMANHO_BLOCO_CONSULTA = 5000;
export const TAMANHO_MAXIMO_NOME = 300;

const arredondar = (n) => Math.round(n * 10000) / 10000;
const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;

/** Itens válidos do relatório ({ id_pedido, sku, quantidade, descricao }) -> { [id_pedido]: [{ sku, quantidade }] }. */
export function indexarItens(lista) {
  const itens = {};
  for (const i of lista ?? []) {
    const id = String(i.id_pedido);
    (itens[id] = itens[id] ?? []).push({ sku: String(i.sku), quantidade: Number(i.quantidade) });
  }
  return itens;
}

/** Peso de um pedido: { estado: 'completo' | 'incompleto' | 'sem_itens', kg, faltam } (faltam = itens sem peso; kg = soma do que tem peso, nulo sem itens). */
export function pesoDoPedido(itensDoPedido, pesos) {
  if (!Array.isArray(itensDoPedido) || itensDoPedido.length === 0) return { estado: 'sem_itens', kg: null, faltam: 0 };
  let kg = 0;
  let faltam = 0;
  for (const item of itensDoPedido) {
    const peso = pesos?.[item.sku]?.peso_kg;
    if (typeof peso === 'number' && peso > 0) kg += item.quantidade * peso;
    else faltam += 1;
  }
  return { estado: faltam === 0 ? 'completo' : 'incompleto', kg: arredondar(kg), faltam };
}

/** "12,5" (até 2 casas, vírgula decimal). */
export const formatarKg = (kg) => Number(kg).toLocaleString('pt-BR', { maximumFractionDigits: 2 });

/** "≈ 12,5 kg (estimado)", "≥ 12,5 kg, faltam 2 itens (estimado)" ou "sem itens informados". */
export function textoDoPeso(peso) {
  if (peso.estado === 'sem_itens') return 'sem itens informados';
  if (peso.estado === 'completo') return `≈ ${formatarKg(peso.kg)} kg (estimado)`;
  return `≥ ${formatarKg(peso.kg)} kg, faltam ${plural(peso.faltam, 'item', 'itens')} (estimado)`;
}

/**
 * Peso de uma lista de pedidos (ids): { estado: 'completo' | 'minimo' | 'sem_itens', kg, faltamItens, pedidosIncompletos, pedidosSemItens, pedidos }.
 * É 'minimo' (≥) quando algum pedido está incompleto ou sem itens; 'sem_itens' quando NENHUM pedido da lista tem itens (peso desconhecido, não 0 kg).
 */
export function pesoDosPedidos(ids, itens, pesos) {
  const total = { estado: 'completo', kg: 0, faltamItens: 0, pedidosIncompletos: 0, pedidosSemItens: 0, pedidos: 0 };
  for (const id of ids ?? []) {
    const p = pesoDoPedido(itens?.[String(id)], pesos);
    total.pedidos += 1;
    if (p.estado === 'sem_itens') total.pedidosSemItens += 1;
    else {
      total.kg += p.kg;
      total.faltamItens += p.faltam;
      if (p.estado === 'incompleto') total.pedidosIncompletos += 1;
    }
  }
  total.kg = arredondar(total.kg);
  if (total.pedidos > 0 && total.pedidosSemItens === total.pedidos) total.estado = 'sem_itens';
  else if (total.pedidosIncompletos > 0 || total.pedidosSemItens > 0) total.estado = 'minimo';
  return total;
}

/** Texto principal do total: "≈ 120 kg (estimado)", "≥ 120 kg (estimado)" ou "sem itens informados". */
export function textoDoTotal(total) {
  if (total.estado === 'sem_itens') return 'sem itens informados';
  return `${total.estado === 'completo' ? '≈' : '≥'} ${formatarKg(total.kg)} kg (estimado)`;
}

/** Detalhe do que falta: "faltam 3 itens em 2 pedidos; 1 pedido sem itens informados" (vazio quando está completo). */
export function detalheDoTotal(total) {
  if (total.estado === 'completo' || total.estado === 'sem_itens') return '';
  const partes = [];
  if (total.faltamItens > 0) partes.push(`faltam ${plural(total.faltamItens, 'item', 'itens')} em ${plural(total.pedidosIncompletos, 'pedido', 'pedidos')}`);
  if (total.pedidosSemItens > 0) partes.push(`${plural(total.pedidosSemItens, 'pedido sem itens informados', 'pedidos sem itens informados')}`);
  return partes.join('; ');
}

/** Peso de cada rota (viagem), por id da rota: { [rotaId]: total }. As rotas são as efetivas (depois das trocas de motorista). */
export function pesoPorViagem(rotas, itens, pesos) {
  return Object.fromEntries((rotas ?? []).map((r) => [r.id, pesoDosPedidos((r.paradas ?? []).map((p) => p.id), itens, pesos)]));
}

function agrupar(rotas, chave, nome, itens, pesos) {
  const grupos = new Map();
  for (const r of rotas ?? []) {
    const k = chave(r);
    const atual = grupos.get(k) ?? { chave: k, nome: nome(r), ids: [], viagens: 0 };
    atual.ids.push(...(r.paradas ?? []).map((p) => p.id));
    atual.viagens += 1;
    grupos.set(k, atual);
  }
  return [...grupos.values()].map(({ ids, ...resto }) => ({ ...resto, pedidos: ids.length, total: pesoDosPedidos(ids, itens, pesos) }));
}

/** Peso por motorista (soma das viagens dele): [{ chave: motorista_id, nome, viagens, pedidos, total }], na ordem em que aparecem. */
export const pesoPorMotorista = (rotas, itens, pesos) => agrupar(rotas, (r) => r.motorista_id, (r) => r.motorista_base || r.motorista, itens, pesos);

/** Peso por tipo de veículo: [{ chave: modal, nome: modal, viagens, pedidos, total }]. */
export const pesoPorTipoDeVeiculo = (rotas, itens, pesos) => agrupar(rotas, (r) => r.modal, (r) => r.modal, itens, pesos);

/** Quantos pedidos do lote têm itens informados (para o resumo "N pedidos com itens"). */
export const pedidosComItens = (itens) => Object.keys(itens ?? {}).length;

/** SKUs (únicos) dos itens do lote, para consultar os pesos de novo. */
export const skusDosItens = (itens) => [...new Set(Object.values(itens ?? {}).flat().map((i) => i.sku))];

/** Divide uma lista em blocos de até `tamanho`. */
export function emBlocos(lista, tamanho) {
  const blocos = [];
  for (let i = 0; i < (lista ?? []).length; i += tamanho) blocos.push(lista.slice(i, i + tamanho));
  return blocos;
}

/**
 * SKUs que alimentam a fila "sem peso" ao aceitar o arquivo: os NOVOS (fora do cadastro) e os SEM PESO, que ainda NÃO foram registrados neste lote (`jaRegistrados`).
 * [{ id_sku, quantidade (soma das quantidades, arredondada para cima, no mínimo 1), nome? (primeira descrição do arquivo, até 300 caracteres) }]. Só aqui nasce o que vai
 * para `skus-vistos`: pedido, endereço e cliente nunca vão junto. A chamada soma unidades a cada vez: por isso só os ainda não registrados.
 */
export function skusParaRegistrar(itensValidos, pesos, jaRegistrados = []) {
  const ja = new Set(jaRegistrados);
  const porSku = new Map();
  for (const i of itensValidos ?? []) {
    const sku = String(i.sku);
    if (ja.has(sku)) continue;
    const cadastrado = pesos?.[sku];
    if (cadastrado && typeof cadastrado.peso_kg === 'number' && cadastrado.peso_kg > 0) continue; // já tem peso: não precisa da fila
    const atual = porSku.get(sku) ?? { id_sku: sku, quantidade: 0, nome: null };
    atual.quantidade += Number(i.quantidade) || 0;
    if (!atual.nome && i.descricao) atual.nome = String(i.descricao).trim().slice(0, TAMANHO_MAXIMO_NOME) || null;
    porSku.set(sku, atual);
  }
  return [...porSku.values()].map((s) => {
    const item = { id_sku: s.id_sku, quantidade: Math.max(1, Math.ceil(arredondar(s.quantidade))) };
    if (s.nome) item.nome = s.nome;
    return item;
  });
}

/** Junta ao conjunto de registrados os SKUs de um bloco enviado com sucesso (conjunto novo; o recebido não muda). */
export const marcarComoRegistrados = (jaRegistrados, enviados) => [...new Set([...(jaRegistrados ?? []), ...(enviados ?? []).map((i) => i.id_sku)])];

/** Pesos depois de consultar de novo: só os SKUs consultados são trocados (os que sumiram da resposta deixam de existir no cadastro). */
export function substituirPesos(pesosAtuais, skusConsultados, resposta) {
  const novo = { ...(pesosAtuais ?? {}) };
  for (const sku of skusConsultados ?? []) delete novo[sku];
  return { ...novo, ...(resposta ?? {}) };
}

/** Resumo do lote com itens: "12 pedidos com itens" (vazio se não há itens). */
export function resumoDosItens(itens) {
  const n = pedidosComItens(itens);
  return n === 0 ? '' : `${plural(n, 'pedido com itens', 'pedidos com itens')}`;
}

export const DICA_SEM_ITENS = 'Para ver o peso estimado dos pedidos, envie o arquivo de itens (opcional).';
