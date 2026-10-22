// Relatório de janelas de entrega (Etapa 11): chegada estimada em cada parada e pedidos fora do prazo, por rota. Só funções puras, calculadas na tela, então
// recalculam na hora ao mudar a hora de saída ou o motorista de uma rota, sem rodar o solver. É INFORMATIVO: nunca muda o agrupamento, nunca bloqueia e nada é gravado.
// Usa o id do pedido só para mostrar na tela (como a lista de pedidos); nada daqui vai para o servidor, console ou armazenamento.
//
// Chegada na parada k = saída da viagem + tempo dos k primeiros trechos + (k-1) x tempo por parada. A 1ª viagem de cada motorista sai na hora de saída;
// a viagem seguinte sai quando a anterior volta à loja (deslocamento com a volta + o tempo de todas as paradas). Não considera rotas feitas antes hoje.

const TURNO_NO_TEXTO = { manha: 'manhã', tarde: 'tarde', noite: 'noite' };
export const MSG_INFORME_A_SAIDA = 'Informe a hora de saída para estimar as chegadas.';
export const MSG_HORA_INVALIDA = 'Digite a hora de saída no formato 08:00.';
export const MSG_SEM_LOJA = 'Sem loja escolhida (outro endereço): só as janelas dos pedidos foram conferidas.';

const DIA_EM_MIN = 24 * 60;

/** "13:20" -> 800; texto vazio ou fora do formato -> null. */
export function horaParaMinutos(texto) {
  const m = /^(\d{1,2}):(\d{2})(?::\d{2})?$/.exec(String(texto ?? '').trim());
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  return h > 23 || min > 59 ? null : h * 60 + min;
}

/** 800 -> "13:20"; depois da meia-noite: "00:20 (dia seguinte)". */
export function minutosParaHora(total) {
  const t = Math.round(total);
  const dentro = ((t % DIA_EM_MIN) + DIA_EM_MIN) % DIA_EM_MIN;
  const texto = `${String(Math.floor(dentro / 60)).padStart(2, '0')}:${String(dentro % 60).padStart(2, '0')}`;
  return t >= DIA_EM_MIN ? `${texto} (dia seguinte)` : texto;
}

/**
 * Hora digitada pelo operador -> "HH:MM". Aceita "8", "830", "1230", "8:30", "08h30" e "8h"; vazio = padrão do turno ({ ok: true, valor: '' }).
 * Inválida (25:00, abc, 12:60...) = { ok: false, valor: '', mensagem }, e quem chama não usa o valor.
 */
export function normalizarHoraDigitada(texto) {
  const limpo = String(texto ?? '').trim().toLowerCase().replace(/\s+/g, '');
  if (!limpo) return { ok: true, valor: '' };
  const invalida = { ok: false, valor: '', mensagem: MSG_HORA_INVALIDA };
  let h;
  let m = 0;
  let achou = /^(\d{1,2})(?:[:h.](\d{2})?)?$/.exec(limpo);
  if (achou) {
    h = Number(achou[1]);
    m = achou[2] === undefined ? 0 : Number(achou[2]);
  } else {
    achou = /^(\d{1,2})(\d{2})$/.exec(limpo);
    if (!achou) return invalida;
    h = Number(achou[1]);
    m = Number(achou[2]);
  }
  if (h > 23 || m > 59) return invalida;
  return { ok: true, valor: `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}` };
}

/** Soma `delta` minutos a uma hora "HH:MM" (ou ao `padraoMin`, em minutos, se vazia; 08:00 sem padrão), sem passar de 00:00 nem de 23:59. Devolve "HH:MM". */
export function somarMinutos(texto, delta, padraoMin = null) {
  const base = horaParaMinutos(texto) ?? padraoMin ?? 8 * 60;
  const total = Math.min(DIA_EM_MIN - 1, Math.max(0, base + delta));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

/** Linha de resumo da saída: "Saída às 12:30", "Saída às 08:00 (padrão do turno)" ou "Informe a hora de saída". */
export function resumoDaSaida(horaDeSaida, saidaPadraoMin) {
  const digitada = horaParaMinutos(horaDeSaida);
  if (digitada !== null) return `Saída às ${minutosParaHora(digitada)}`;
  if (saidaPadraoMin !== null && saidaPadraoMin !== undefined) return `Saída às ${minutosParaHora(saidaPadraoMin)} (padrão do turno)`;
  return 'Informe a hora de saída';
}

/** Janela da loja no turno, em minutos: { inicio, fim } ou null (loja sem janela para o turno, ex.: noite desligada). */
export function janelaDaLoja(loja, turno) {
  if (!loja || !TURNO_NO_TEXTO[turno]) return null;
  const inicio = horaParaMinutos(loja[`janela_${turno}_inicio`]);
  const fim = horaParaMinutos(loja[`janela_${turno}_fim`]);
  return inicio === null || fim === null ? null : { inicio, fim };
}

/** Hora de saída digitada: vazio = padrão ({ ok, valor: null }); inválida = { ok: false, mensagem }. */
export function interpretarHoraDeSaida(texto) {
  const limpo = String(texto ?? '').trim();
  if (!limpo) return { ok: true, valor: null };
  const valor = horaParaMinutos(limpo);
  return valor === null ? { ok: false, valor: null, mensagem: MSG_HORA_INVALIDA } : { ok: true, valor };
}

/** Tempo de cada trecho (ida a cada parada e a volta), em minutos. Sem `tempos_trechos_s` reparte o deslocamento pela distância dos trechos. */
export function temposDosTrechos(rota) {
  const n = (rota.paradas ?? []).length + 1;
  if (Array.isArray(rota.tempos_trechos_s) && rota.tempos_trechos_s.length === n) return rota.tempos_trechos_s.map((s) => (Number(s) || 0) / 60);
  const km = Array.isArray(rota.distancias_trechos_km) && rota.distancias_trechos_km.length === n ? rota.distancias_trechos_km.map((d) => Number(d) || 0) : Array(n).fill(0);
  const soma = km.reduce((a, b) => a + b, 0);
  const total = Number(rota.tempo_deslocamento_min) || 0;
  return km.map((d) => (soma > 0 ? (total * d) / soma : total / n));
}

/** Quanto dura a viagem (com a volta à loja e todas as paradas), em minutos. */
export function duracaoDaViagem(rota, tempoPorParada) {
  return temposDosTrechos(rota).reduce((a, b) => a + b, 0) + (rota.paradas ?? []).length * tempoPorParada;
}

/** Hora de saída de cada viagem: Map(id da rota -> minutos). Por motorista, na ordem das viagens; a seguinte sai quando a anterior volta. */
export function saidasDasViagens(rotas, saida, tempoPorParada) {
  const porMotorista = new Map();
  for (const r of rotas ?? []) porMotorista.set(r.motorista_id, [...(porMotorista.get(r.motorista_id) ?? []), r]);
  const saidas = new Map();
  for (const viagens of porMotorista.values()) {
    let sai = saida;
    [...viagens].sort((a, b) => (a.viagem_num ?? 1) - (b.viagem_num ?? 1) || a.id - b.id).forEach((r) => {
      saidas.set(r.id, sai);
      sai += duracaoDaViagem(r, tempoPorParada);
    });
  }
  return saidas;
}

/** Chegada em cada parada da viagem, em minutos (inteiros): [{ pedidoId, ordem, chegada }]. */
export function chegadasDaRota(rota, saida, tempoPorParada) {
  const trechos = temposDosTrechos(rota);
  let acumulado = 0;
  return (rota.paradas ?? []).map((p, i) => {
    acumulado += trechos[i];
    return { pedidoId: String(p.id), ordem: p.ordem ?? i + 1, chegada: Math.round(saida + acumulado + i * tempoPorParada) };
  });
}

function janelaDoPedido(pedido) {
  if (!pedido) return null;
  const inicio = horaParaMinutos(pedido.janela_inicio);
  const fim = horaParaMinutos(pedido.janela_fim);
  return inicio === null || fim === null ? null : { inicio, fim };
}

/** Janela que vale para o pedido (em minutos): a do PEDIDO quando ele trouxe as duas horas; senão a da LOJA no turno; null se não houver nenhuma. */
export function janelaEfetivaDoPedido(pedido, loja, turno) {
  return janelaDoPedido(pedido) ?? (loja ? janelaDaLoja(loja, turno) : null);
}

function avaliar(chegada, janelaLoja, janelaPedido, turno) {
  const hora = minutosParaHora(chegada);
  const nomeLoja = `a janela da ${TURNO_NO_TEXTO[turno]} da loja`;
  const fora = [];
  if (janelaLoja && chegada > janelaLoja.fim) fora.push(`${nomeLoja} termina às ${minutosParaHora(janelaLoja.fim)}`);
  if (janelaPedido && chegada > janelaPedido.fim) fora.push(`a janela do pedido termina às ${minutosParaHora(janelaPedido.fim)}`);
  if (fora.length > 0) return { tipo: 'fora', hora, texto: `chega às ${hora}; ${fora.join(' e ')}` };
  const antes = [];
  if (janelaLoja && chegada < janelaLoja.inicio) antes.push({ inicio: janelaLoja.inicio, nome: `da ${TURNO_NO_TEXTO[turno]} da loja` });
  if (janelaPedido && chegada < janelaPedido.inicio) antes.push({ inicio: janelaPedido.inicio, nome: 'do pedido' });
  if (antes.length > 0) {
    const decisiva = antes.reduce((a, b) => (b.inicio > a.inicio ? b : a));
    return { tipo: 'antes', hora, texto: `chega às ${hora}, antes do início da janela ${decisiva.nome} (${minutosParaHora(decisiva.inicio)})` };
  }
  return null;
}

/**
 * Relatório de janelas. `rotas`: as rotas efetivas (depois das trocas de motorista); `pedidos`: o lote da tela (para a janela de cada pedido, por id);
 * `loja`: a loja escolhida (ou null em "Outro endereço"); `turno`: o do resultado; `horaDeSaida`: texto digitado (vazio = início da janela da loja);
 * `tempoPorParada`: o enviado ao gerar. Devolve { status: 'ok' | 'sem_saida' | 'sem_rotas', mensagens, saidaPadrao, saidaUsada, totalPedidos, foraDoPrazo,
 * antesDoInicio, rotas: [{ rotaId, titulo, saida, total, fora: [...], antes: [...] }] } (só as rotas com algo a mostrar).
 */
export function relatorioDeJanelas({ rotas, pedidos, loja, turno, horaDeSaida = '', tempoPorParada = 10 }) {
  const mensagens = [];
  const base = { mensagens, saidaPadrao: null, saidaUsada: null, totalPedidos: 0, foraDoPrazo: 0, antesDoInicio: 0, rotas: [], porParada: {} };
  if (!rotas || rotas.length === 0) return { ...base, status: 'sem_rotas' };

  const janelaLoja = loja ? janelaDaLoja(loja, turno) : null;
  if (!loja) mensagens.push(MSG_SEM_LOJA);
  else if (!janelaLoja) mensagens.push(`A loja não tem janela para a ${TURNO_NO_TEXTO[turno] ?? 'este turno'}; só as janelas dos pedidos foram conferidas.`);

  const digitada = interpretarHoraDeSaida(horaDeSaida);
  if (!digitada.ok) mensagens.push(digitada.mensagem);
  const saidaPadrao = janelaLoja ? janelaLoja.inicio : null;
  const saidaUsada = digitada.valor ?? saidaPadrao;
  const resultado = { ...base, saidaPadrao, saidaUsada };
  if (saidaUsada === null) {
    mensagens.push(MSG_INFORME_A_SAIDA);
    return { ...resultado, status: 'sem_saida' };
  }

  const porId = new Map((pedidos ?? []).map((p) => [String(p.id), p]));
  const saidas = saidasDasViagens(rotas, saidaUsada, tempoPorParada);
  let total = 0;
  let foraDoPrazo = 0;
  let antesDoInicio = 0;
  const relatorioRotas = [];
  const porParada = {};
  for (const rota of rotas) {
    const fora = [];
    const antes = [];
    porParada[rota.id] = [];
    for (const c of chegadasDaRota(rota, saidas.get(rota.id), tempoPorParada)) {
      total += 1;
      const janelaProprio = janelaDoPedido(porId.get(c.pedidoId));
      const veredito = avaliar(c.chegada, janelaLoja, janelaProprio, turno);
      // por parada (usado no romaneio): chegada e se está fora do prazo (null = sem nenhuma janela para avaliar)
      porParada[rota.id].push({ pedidoId: c.pedidoId, ordem: c.ordem, chegada: c.chegada, horaTexto: minutosParaHora(c.chegada), fora: veredito?.tipo === 'fora' ? true : (janelaLoja || janelaProprio ? false : null) });
      if (!veredito) continue;
      (veredito.tipo === 'fora' ? fora : antes).push({ id: c.pedidoId, ordem: c.ordem, chegada: veredito.hora, texto: veredito.texto });
    }
    foraDoPrazo += fora.length;
    antesDoInicio += antes.length;
    if (fora.length > 0 || antes.length > 0) {
      relatorioRotas.push({ rotaId: rota.id, titulo: `Rota ${rota.id} · ${rota.motorista}`, saida: minutosParaHora(saidas.get(rota.id)), total: (rota.paradas ?? []).length, fora, antes });
    }
  }
  return { ...resultado, status: 'ok', totalPedidos: total, foraDoPrazo, antesDoInicio, rotas: relatorioRotas, porParada };
}

/** { id_da_rota: quantos pedidos chegam fora do prazo } só das rotas com algum (para o selo da Matriz de despacho). */
export function foraDoPrazoPorRota(relatorio) {
  return Object.fromEntries((relatorio?.rotas ?? []).filter((r) => r.fora.length > 0).map((r) => [r.rotaId, r.fora.length]));
}

/** Dica do selo: "3 pedidos chegam fora da janela". */
export const dicaDoSelo = (n) => `${n} ${n === 1 ? 'pedido chega' : 'pedidos chegam'} fora da janela`;

/** Resumo do bloco: "2 de 8 pedidos fora do prazo" (e quantos chegam antes do início). */
export function resumoDoRelatorio(r) {
  if (r.status !== 'ok') return '';
  const base = `${r.foraDoPrazo} de ${r.totalPedidos} ${r.totalPedidos === 1 ? 'pedido' : 'pedidos'} fora do prazo`;
  return r.antesDoInicio > 0 ? `${base}; ${r.antesDoInicio} ${r.antesDoInicio === 1 ? 'chega antes do início da janela' : 'chegam antes do início da janela'}` : base;
}
