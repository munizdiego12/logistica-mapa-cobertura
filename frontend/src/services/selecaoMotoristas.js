// Escolha dos motoristas da roteirização e textos das rotas realizadas (singular/plural certos, linguagem do operador).
// Sem dependências, para ser testável com o `node --test` do Node.

export const MSG_MARQUE_MOTORISTA = 'Marque pelo menos um motorista para gerar as rotas.';

const plural = (n, singular, pluralTexto) => (n === 1 ? `${n} ${singular}` : `${n} ${pluralTexto}`);

/** "nenhuma rota hoje", "1 rota realizada hoje", "3 rotas realizadas hoje". */
export function textoRotasHoje(n) {
  const total = Number(n) || 0;
  if (total <= 0) return 'nenhuma rota hoje';
  return `${plural(total, 'rota', 'rotas')} ${total === 1 ? 'realizada' : 'realizadas'} hoje`;
}

function tipoCurto(tipo) {
  const texto = String(tipo ?? '');
  if (/passeio/i.test(texto)) return 'Passeio';
  if (/utilit/i.test(texto)) return 'Utilitário';
  return texto;
}

/** Item do campo de escolha: "João - Utilitário - 1 rota realizada hoje". */
export function rotuloDoMotorista(motorista, rotasHoje) {
  return `${motorista.nome} - ${tipoCurto(motorista.tipo_veiculo)} - ${textoRotasHoje(rotasHoje)}`;
}

/** "3 rotas (2 motoristas)", "1 rota (1 motorista)". */
export function textoRotasEMotoristas(rotas, motoristas) {
  return `${plural(Number(rotas) || 0, 'rota', 'rotas')} (${plural(Number(motoristas) || 0, 'motorista', 'motoristas')})`;
}

/** Linha mostrada ao confirmar: "João: +2 rotas (total hoje: 3)". */
export function linhaDeConfirmacao(nome, adicionadas, totalHoje) {
  const n = Number(adicionadas) || 0;
  return `${nome}: +${plural(n, 'rota', 'rotas')} (total hoje: ${Number(totalHoje) || 0})`;
}

/** Linha mostrada ao desfazer a confirmação: "João: confirmação desfeita (total hoje: 1)". */
export function linhaDeDesfazer(nome, totalHoje) {
  return `${nome}: confirmação desfeita (total hoje: ${Number(totalHoje) || 0})`;
}

/** Rotas desta roteirização por motorista: [{ motorista_id, nome, rotas }], na ordem em que aparecem. */
export function rotasPorMotoristaDoResultado(rotas) {
  const porId = new Map();
  for (const rota of rotas ?? []) {
    const id = rota.motorista_id;
    if (id === null || id === undefined) continue;
    const atual = porId.get(id) ?? { motorista_id: id, nome: rota.motorista_base || rota.motorista || `Motorista ${id}`, rotas: 0 };
    atual.rotas += 1;
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
