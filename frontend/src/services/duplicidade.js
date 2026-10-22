// Controle de duplicidade (Etapa 9): pedidos que já estão em rota CONFIRMADA de hoje. É sempre aviso, nunca bloqueio.
// O servidor devolve { id: { rota, motorista, turno, loja, operador, hora } } só para os já roteirizados. Nada aqui vai para console nem armazenamento.

const TURNO_NO_SELO = { manha: 'manhã', tarde: 'tarde', noite: 'noite' };

export const MSG_FALHA_DUPLICIDADE = 'Não foi possível verificar agora quais pedidos já estão em rotas de hoje. Confira com atenção antes de executar.';

const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;

/** "já está na Rota 2 de Ana (manhã, 10:30)"; partes ausentes são omitidas. */
export function seloDeDuplicidade(info) {
  if (!info) return '';
  const quando = [TURNO_NO_SELO[info.turno] ?? info.turno, info.hora].filter(Boolean).join(', ');
  return `já está na Rota ${info.rota}${info.motorista ? ` de ${info.motorista}` : ''}${quando ? ` (${quando})` : ''}`;
}

/** O pedido está em rota confirmada de hoje? `jaRoteirizados` nulo (consulta falhou ou ainda não respondeu) = não. */
export const estaJaRoteirizado = (jaRoteirizados, id) => Boolean(jaRoteirizados && Object.prototype.hasOwnProperty.call(jaRoteirizados, id));

/** Ids (texto) dos pedidos de todos os lotes, sem repetir, para a consulta ao servidor. */
export function idsParaConsultar(lotes) {
  const ids = new Set();
  lotes.forEach((l) => l.pedidos.forEach((p) => ids.add(String(p.id))));
  return [...ids];
}

/**
 * Desmarca os já roteirizados que ainda não foram tratados neste lote. Cada pedido é tratado no máximo uma vez: se o operador
 * marcar de volta de propósito, as consultas seguintes não o desmarcam de novo. Resultado nulo (a consulta falhou) não muda nada.
 * Devolve { marcados, tratados, desmarcados } (conjuntos novos; os recebidos não são alterados).
 */
export function aplicarDuplicidade(marcados, jaRoteirizados, tratados = new Set()) {
  if (!jaRoteirizados) return { marcados, tratados, desmarcados: 0 };
  const novosMarcados = new Set(marcados);
  const novosTratados = new Set(tratados);
  let desmarcados = 0;
  Object.keys(jaRoteirizados).forEach((id) => {
    if (novosTratados.has(id)) return;
    novosTratados.add(id);
    if (novosMarcados.delete(id)) desmarcados += 1;
  });
  return { marcados: novosMarcados, tratados: novosTratados, desmarcados };
}

/** Aviso único e curto depois de desmarcar; null se nada foi desmarcado. */
export function avisoDesmarcados(n) {
  if (!n) return null;
  const sujeito = n === 1 ? '1 pedido deste lote já está em rota de hoje e foi desmarcado' : `${n} pedidos deste lote já estão em rotas de hoje e foram desmarcados`;
  return `${sujeito}; marque-${n === 1 ? 'o' : 'os'} de novo só se for de propósito.`;
}

/** As duas perguntas, em sequência, para marcar de volta um pedido já roteirizado. */
export function perguntasParaMarcarDeNovo(info) {
  const onde = `Rota ${info.rota}${info.motorista ? ` de ${info.motorista}` : ''}`;
  return [
    `Este pedido já está na ${onde} hoje. Marcar mesmo assim?`,
    'Tem certeza? Ele pode sair duas vezes para entrega. Marque só se for de propósito.',
  ];
}

/** Pede as duas confirmações (função `confirmar` devolve true/false, como window.confirm); só marca se as duas forem aceitas. */
export function confirmarMarcarDeNovo(info, confirmar) {
  const [primeira, segunda] = perguntasParaMarcarDeNovo(info);
  return Boolean(confirmar(primeira)) && Boolean(confirmar(segunda));
}

/** Quantos dos pedidos (por exemplo, os marcados que vão para a roteirização) já estão em rota confirmada de hoje. */
export function contarJaRoteirizados(pedidos, jaRoteirizados) {
  return pedidos.filter((p) => estaJaRoteirizado(jaRoteirizados, p.id)).length;
}

/** Texto extra da confirmação de "Executar Roteirização"; vazio se nenhum marcado já foi roteirizado. */
export function textoJaRoteirizadosNaConfirmacao(n) {
  if (!n) return '';
  return `\n\nAtenção: ${plural(n, 'pedido marcado já está', 'pedidos marcados já estão')} em rotas confirmadas de hoje.`;
}

/** Aviso do "Marcar visíveis" quando já roteirizados ficaram de fora; null se nenhum. */
export function avisoMarcarVisiveis(n) {
  if (!n) return null;
  return `${plural(n, 'pedido já roteirizado hoje ficou', 'pedidos já roteirizados hoje ficaram')} de fora. Marque ${n === 1 ? 'esse pedido' : 'esses pedidos'} um a um, se for de propósito.`;
}
