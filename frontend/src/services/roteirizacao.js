// Roteirização (Etapa 8): turno escolhido pelo operador, regra do botão "Executar Roteirização", confirmação curta e leitura dos avisos.
// Sem dependências, para ser testável com o `node --test`. O turno é SEMPRE escolhido à mão (nunca inferido do relógio). O peso não entra.

export const TURNOS = [
  { valor: 'manha', rotulo: 'Manhã', janela: '08–13h' },
  { valor: 'tarde', rotulo: 'Tarde', janela: '13–18h' },
  { valor: 'noite', rotulo: 'Noite', janela: '18–21h' },
];
export const TEMPO_POR_PARADA_PADRAO_MIN = 10;
export const MSG_ESCOLHA_O_TURNO = 'Escolha o turno (manhã, tarde ou noite).';
export const MSG_TEMPO_POR_PARADA = 'O tempo por parada precisa ficar entre 1 e 60 minutos.';

export const rotuloDoTurno = (valor) => TURNOS.find((t) => t.valor === valor)?.rotulo ?? '';

/** Tempo por parada digitado: vazio vale 10; precisa ser inteiro de 1 a 60. Devolve { ok, valor } ou { ok: false, mensagem }. */
export function interpretarTempoPorParada(texto) {
  const bruto = String(texto ?? '').trim().replace(',', '.');
  if (bruto === '') return { ok: true, valor: TEMPO_POR_PARADA_PADRAO_MIN };
  const n = Number(bruto);
  if (!Number.isInteger(n) || n < 1 || n > 60) return { ok: false, mensagem: MSG_TEMPO_POR_PARADA };
  return { ok: true, valor: n };
}

/**
 * O botão só habilita com loja (ou hub), pedidos marcados, motoristas marcados E turno escolhido (e um tempo por parada válido).
 * Devolve { ok, falta: [..] } com o que ainda falta, em linguagem do operador.
 */
export function podeExecutar({ hubDefinido, pedidos, motoristas, turno, tempoPorParada = '' }) {
  const falta = [];
  if (!hubDefinido) falta.push('a loja');
  if (!pedidos) falta.push('os pedidos');
  if (!motoristas) falta.push('os motoristas');
  if (!TURNOS.some((t) => t.valor === turno)) falta.push('o turno');
  if (!interpretarTempoPorParada(tempoPorParada).ok) falta.push('o tempo por parada');
  return { ok: falta.length === 0, falta };
}

const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;

/** Confirmação curta antes de rodar: "Gerar as rotas do turno da manhã para Atacadão X com 12 pedidos e 3 motoristas?" */
export function textoDeConfirmacao({ turno, loja, pedidos, motoristas }) {
  const turnoTexto = { manha: 'da manhã', tarde: 'da tarde', noite: 'da noite' }[turno] ?? '';
  return `Gerar as rotas do turno ${turnoTexto} para ${loja || 'o endereço informado'} com ${plural(pedidos, 'pedido', 'pedidos')} e ${plural(motoristas, 'motorista', 'motoristas')}?`;
}

/** "45 min" ou "2h 5m". */
export function formatarMinutos(minutos) {
  const m = Math.max(0, Math.round(Number(minutos) || 0));
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m} min`;
}

/** Setores de uma rota para a tabela: "N, NE" (ou "—"). */
export const textoDosSetores = (setores) => (Array.isArray(setores) && setores.length ? setores.join(', ') : '—');

/** Avisos do resultado, os de atenção primeiro (a ordem original se mantém dentro de cada grupo). */
export function avisosOrdenados(avisos) {
  const lista = Array.isArray(avisos) ? avisos : [];
  return [...lista.filter((a) => a.gravidade === 'atencao'), ...lista.filter((a) => a.gravidade !== 'atencao')];
}

/** As distâncias desta execução vieram em linha reta (estimativa)? */
export const distanciasEmLinhaReta = (resultado) => resultado?.origem_distancias === 'linha_reta';
