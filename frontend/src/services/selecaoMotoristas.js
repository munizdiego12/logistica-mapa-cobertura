// Escolha dos motoristas da roteirização e textos das rotas realizadas (singular/plural certos, linguagem do operador).
// Sem dependências, para ser testável com o `node --test` do Node.

export const MSG_MARQUE_MOTORISTA = 'Marque pelo menos um motorista para gerar as rotas.';

const plural = (n, singular, pluralTexto) => (n === 1 ? `${n} ${singular}` : `${n} ${pluralTexto}`);

/** "1 pedido", "10 pedidos". */
export function textoPedidos(n) {
  return plural(Number(n) || 0, 'pedido', 'pedidos');
}

/** "nenhuma rota hoje", "1 rota realizada hoje", "3 rotas realizadas hoje"; com os pedidos: "3 rotas realizadas hoje (12 pedidos)". */
export function textoRotasHoje(n, pedidos) {
  const total = Number(n) || 0;
  if (total <= 0) return 'nenhuma rota hoje';
  const base = `${plural(total, 'rota', 'rotas')} ${total === 1 ? 'realizada' : 'realizadas'} hoje`;
  return pedidos === undefined || pedidos === null ? base : `${base} (${textoPedidos(pedidos)})`;
}

function tipoCurto(tipo) {
  const texto = String(tipo ?? '');
  if (/passeio/i.test(texto)) return 'Passeio';
  if (/utilit/i.test(texto)) return 'Utilitário';
  return texto;
}

/** Item do campo de escolha: "João - Utilitário - 1 rota realizada hoje (5 pedidos)" (sem o total de pedidos, só as rotas). */
export function rotuloDoMotorista(motorista, rotasHoje, pedidosHoje) {
  return `${motorista.nome} - ${tipoCurto(motorista.tipo_veiculo)} - ${textoRotasHoje(rotasHoje, pedidosHoje)}`;
}

/** "3 rotas (2 motoristas)", "1 rota (1 motorista)". */
export function textoRotasEMotoristas(rotas, motoristas) {
  return `${plural(Number(rotas) || 0, 'rota', 'rotas')} (${plural(Number(motoristas) || 0, 'motorista', 'motoristas')})`;
}

/**
 * Linha mostrada ao confirmar: "João: +2 rotas (total hoje: 3)"; com os pedidos (Etapa 8b):
 * "João: +2 rotas, 10 pedidos (total hoje: 3 rotas, 14 pedidos)".
 */
export function linhaDeConfirmacao(nome, adicionadas, totalHoje, pedidosAdicionados, pedidosHoje) {
  const n = Number(adicionadas) || 0;
  if (pedidosAdicionados === undefined || pedidosAdicionados === null) return `${nome}: +${plural(n, 'rota', 'rotas')} (total hoje: ${Number(totalHoje) || 0})`;
  return `${nome}: +${plural(n, 'rota', 'rotas')}, ${textoPedidos(pedidosAdicionados)} (total hoje: ${plural(Number(totalHoje) || 0, 'rota', 'rotas')}, ${textoPedidos(pedidosHoje)})`;
}

/** Linha mostrada ao desfazer: "João: confirmação desfeita (total hoje: 1)"; com os pedidos: "(total hoje: 1 rota, 4 pedidos)". */
export function linhaDeDesfazer(nome, totalHoje, pedidosHoje) {
  if (pedidosHoje === undefined || pedidosHoje === null) return `${nome}: confirmação desfeita (total hoje: ${Number(totalHoje) || 0})`;
  return `${nome}: confirmação desfeita (total hoje: ${plural(Number(totalHoje) || 0, 'rota', 'rotas')}, ${textoPedidos(pedidosHoje)})`;
}

/**
 * Cartão "Rotas por motorista": "Ana: 2 rotas nesta roteirização (10 pedidos) • 1 rota realizada hoje (4 pedidos)".
 * Sem rotas nesta roteirização (ainda não gerou), só a parte de hoje.
 */
export function textoDoMotoristaNoCartao({ nome, rotas, pedidos }, rotasHoje, pedidosHoje) {
  const hoje = textoRotasHoje(rotasHoje, pedidosHoje);
  if (rotas === null || rotas === undefined) return `${nome} • ${hoje}`;
  return `${nome}: ${plural(rotas, 'rota', 'rotas')} nesta roteirização (${textoPedidos(pedidos)}) • ${hoje}`;
}

/** Por motorista: { rotas, pedidos } das rotas do resultado (Map id -> total). */
export function resumoPorMotorista(rotas) {
  const mapa = new Map();
  for (const r of rotas ?? []) {
    if (r.motorista_id === null || r.motorista_id === undefined) continue;
    const atual = mapa.get(r.motorista_id) ?? { rotas: 0, pedidos: 0 };
    atual.rotas += 1;
    atual.pedidos += Number(r.qtd_pedidos) || 0;
    mapa.set(r.motorista_id, atual);
  }
  return mapa;
}

/** "2 rotas, 10 pedidos" (só para o motorista com mais de uma viagem; senão null). */
export function textoResumoDoMotorista(resumo) {
  if (!resumo || resumo.rotas <= 1) return null;
  return `${plural(resumo.rotas, 'rota', 'rotas')}, ${textoPedidos(resumo.pedidos)}`;
}

/** Comparativo da rota personalizada: "10 pedidos; recomendado 5 por viagem". */
export function textoDaRotaPersonalizada(rota) {
  return `${textoPedidos(rota.qtd_pedidos)}; recomendado ${Number(rota.teto_recomendado) || 0} por viagem`;
}

/** Rotas desta roteirização por motorista: [{ motorista_id, nome, rotas }], na ordem em que aparecem. */
export function rotasPorMotoristaDoResultado(rotas) {
  const porId = new Map();
  for (const rota of rotas ?? []) {
    const id = rota.motorista_id;
    if (id === null || id === undefined) continue;
    const atual = porId.get(id) ?? { motorista_id: id, nome: rota.motorista_base || rota.motorista || `Motorista ${id}`, rotas: 0, pedidos: 0 };
    atual.rotas += 1;
    atual.pedidos += Number(rota.qtd_pedidos) || 0;
    porId.set(id, atual);
  }
  return [...porId.values()];
}

/** Mantém marcados só os motoristas que continuam ativos na lista (ex.: depois de desativar um na tela "Motoristas"). */
export function manterSomenteAtivos(selecionados, ativos) {
  const ids = new Set((ativos ?? []).map((m) => m.id));
  return (selecionados ?? []).filter((id) => ids.has(id));
}

/** Alterna a marcação de um motorista, sem repetir ids. */
export function alternarMarcacao(selecionados, id) {
  return selecionados.includes(id) ? selecionados.filter((x) => x !== id) : [...selecionados, id];
}

/** Os motoristas marcados (na ordem da lista de ativos). */
export function motoristasMarcados(ativos, selecionados) {
  return (ativos ?? []).filter((m) => (selecionados ?? []).includes(m.id));
}

/** O botão de executar só habilita com pelo menos um motorista marcado. */
export function podeExecutarComMotoristas(selecionados) {
  return Array.isArray(selecionados) && selecionados.length > 0;
}

/** Marca vários de uma vez (ex.: "Marcar todos desta loja"), mantendo quem já estava marcado e sem repetir ids. */
export function marcarVarios(selecionados, ids) {
  const atuais = selecionados ?? [];
  const novos = (ids ?? []).filter((id) => !atuais.includes(id));
  return novos.length === 0 ? atuais : [...atuais, ...novos];
}

/** Etiqueta do motorista marcado: "João · MOT-0001" (sem código: só o nome). */
export function etiquetaDoMotorista(motorista) {
  return motorista.codigo ? `${motorista.nome} · ${motorista.codigo}` : motorista.nome;
}
