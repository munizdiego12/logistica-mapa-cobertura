// Roteirização (Etapa 8): turno escolhido pelo operador, regra do botão "Executar Roteirização", confirmação curta e leitura dos avisos.
// Sem dependências, para ser testável com o `node --test`. O turno é SEMPRE escolhido à mão (nunca inferido do relógio). O peso não entra.
import { textoJaRoteirizadosNaConfirmacao } from './duplicidade.js';

export const TURNOS = [
  { valor: 'manha', rotulo: 'Manhã', janela: '08–13h' },
  { valor: 'tarde', rotulo: 'Tarde', janela: '13–18h' },
  { valor: 'noite', rotulo: 'Noite', janela: '18–21h' },
];
export const TEMPO_POR_PARADA_PADRAO_MIN = 10;
export const MSG_ESCOLHA_O_TURNO = 'Escolha o turno (manhã, tarde ou noite).';
export const MSG_TEMPO_POR_PARADA = 'O tempo por parada precisa ficar entre 1 e 60 minutos.';

// Etapa 8b: quantas rotas (viagens) cada motorista faz. Automático é o padrão (recomendado); 1 a 4 definem a rota personalizada.
export const OPCOES_DE_VIAGENS = [
  { valor: '', rotulo: 'Automático (recomendado)' },
  { valor: '1', rotulo: '1' }, { valor: '2', rotulo: '2' }, { valor: '3', rotulo: '3' }, { valor: '4', rotulo: '4' },
];
export const CAPACIDADE_PADRAO = 6; // o mesmo teto que o servidor usa quando o tipo não tem capacidade
export const AVISO_VIAGENS = 'Cada viagem conta como uma rota no dia: o motorista que fizer menos viagens terá menos rotas contadas.';

/**
 * Rotas recomendadas: ceil(pedidos marcados / soma dos tetos dos motoristas marcados), mínimo 1. `tiposDosMotoristas`: o tipo de veículo de cada
 * motorista marcado; `capacidades`: { tipo: teto de pedidos por viagem }.
 */
export function recomendarRotas(pedidos, tiposDosMotoristas, capacidades) {
  const soma = (tiposDosMotoristas ?? []).reduce((t, tipo) => t + Math.max(1, Number(capacidades?.[tipo]?.capacidade ?? capacidades?.[tipo]) || CAPACIDADE_PADRAO), 0);
  if (!soma) return 1;
  return Math.max(1, Math.ceil((Number(pedidos) || 0) / soma));
}

/** "Recomendado: 1 rota com base na quantidade de pedidos" / "Recomendado: 3 rotas com base na quantidade de pedidos". */
export const textoRecomendado = (n) => `Recomendado: ${n} ${n === 1 ? 'rota' : 'rotas'} com base na quantidade de pedidos`;

/** Corpo enviado: { "id": n } só para os motoristas marcados com número definido (1 a 4); automático fica de fora. */
export function corpoDasViagens(selecionados, viagensPorMotorista) {
  const corpo = {};
  for (const id of selecionados ?? []) {
    const n = Number(viagensPorMotorista?.[id]);
    if (Number.isInteger(n) && n >= 1 && n <= 4) corpo[id] = n;
  }
  return corpo;
}

/** Tira do mapa os motoristas que deixaram de estar marcados. */
export function manterViagensDosMarcados(viagensPorMotorista, selecionados) {
  const ids = new Set(selecionados ?? []);
  return Object.fromEntries(Object.entries(viagensPorMotorista ?? {}).filter(([id]) => ids.has(Number(id))));
}

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
export function textoDeConfirmacao({ turno, loja, pedidos, motoristas, jaRoteirizados = 0 }) {
  const turnoTexto = { manha: 'da manhã', tarde: 'da tarde', noite: 'da noite' }[turno] ?? '';
  return `Gerar as rotas do turno ${turnoTexto} para ${loja || 'o endereço informado'} com ${plural(pedidos, 'pedido', 'pedidos')} e ${plural(motoristas, 'motorista', 'motoristas')}?${textoJaRoteirizadosNaConfirmacao(jaRoteirizados)}`;
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
