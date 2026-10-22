// Histórico de rotas confirmadas (Etapa 12): agrupamento por dia > loja > rota, rótulos e parâmetros da consulta. Só funções puras.
// O servidor entrega o operador só pelo nome e o endereço só até o prazo de retenção; nada daqui vai para console nem armazenamento.
import { dataParaExibir } from './pedidos.js';
import { rotuloDoTurno } from './roteirizacao.js';

export const TAMANHO_PAGINA_HISTORICO = 50;

const somarDias = (iso, dias) => {
  const [a, m, d] = iso.split('-').map(Number);
  const dt = new Date(Date.UTC(a, m - 1, d + dias));
  return dt.toISOString().slice(0, 10);
};

/** "Hoje", "Ontem" ou "21/10/2026". `hoje` é o dia de Brasília que o servidor informou (aaaa-mm-dd). */
export function rotuloDoDia(dia, hoje) {
  if (hoje && dia === hoje) return 'Hoje';
  if (hoje && dia === somarDias(hoje, -1)) return 'Ontem';
  return dataParaExibir(dia) || dia;
}

/**
 * Agrupa as rotas (já ordenadas pelo servidor: dia mais recente primeiro, depois loja, hora e número) em
 * [{ dia, rotulo, lojas: [{ loja, rotas: [...] }] }], mantendo a ordem de chegada.
 */
export function agruparHistorico(rotas, hoje) {
  const dias = [];
  rotas.forEach((rota) => {
    let grupoDia = dias[dias.length - 1];
    if (!grupoDia || grupoDia.dia !== rota.dia) {
      grupoDia = { dia: rota.dia, rotulo: rotuloDoDia(rota.dia, hoje), lojas: [] };
      dias.push(grupoDia);
    }
    let grupoLoja = grupoDia.lojas.find((l) => l.loja === rota.loja);
    if (!grupoLoja) {
      grupoLoja = { loja: rota.loja, rotas: [] };
      grupoDia.lojas.push(grupoLoja);
    }
    grupoLoja.rotas.push(rota);
  });
  return dias;
}

/** "Ana · Rota 2" */
export const tituloDaRota = (rota) => `${rota.motorista?.nome || 'Motorista'} · Rota ${rota.numero}`;

const km = (valor) => `${Number(valor).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 1 })} km`;

/** "Manhã · 10:30 · 2 pedidos · 12,5 km" (partes sem valor são omitidas). */
export function detalheDaRota(rota) {
  const pedidos = Number(rota.qtd_pedidos) || 0;
  return [
    rotuloDoTurno(rota.turno), rota.hora, `${pedidos} ${pedidos === 1 ? 'pedido' : 'pedidos'}`,
    rota.km === null || rota.km === undefined ? '' : km(rota.km),
  ].filter(Boolean).join(' · ');
}

export const textoSemDetalhe = 'sem detalhe dos pedidos';

/** Endereço do pedido ou, depois do prazo, "endereço removido após 90 dias". */
export function textoDoEndereco(pedido, diasRetencao = 90) {
  if (pedido.endereco) return pedido.endereco;
  return pedido.endereco_apagado ? `endereço removido após ${diasRetencao} dias` : 'sem endereço';
}

/** "1. #123 · Rua A, 10 - Centro · São Paulo/SP" */
export function linhaDoPedido(pedido, diasRetencao = 90) {
  const local = [pedido.cidade, pedido.uf].filter(Boolean).join('/');
  return `${pedido.ordem}. #${pedido.id} · ${textoDoEndereco(pedido, diasRetencao)}${local ? ` · ${local}` : ''}`;
}

/** Filtros da tela -> parâmetros da consulta (só o que foi preenchido). `loja`, `operador` e `q` vazios não vão. */
export function parametrosDoHistorico(filtros, deslocamento = 0, limite = TAMANHO_PAGINA_HISTORICO) {
  const params = { limite, deslocamento };
  if (filtros.de) params.de = filtros.de;
  if (filtros.ate) params.ate = filtros.ate;
  if (filtros.loja) params.loja = filtros.loja;
  if (filtros.motoristaId) params.motorista_id = filtros.motoristaId;
  if (filtros.operador) params.operador_nome = filtros.operador;
  if (filtros.q && filtros.q.trim()) params.q = filtros.q.trim();
  if (filtros.desfeitas) params.desfeitas = 1;
  return params;
}

/** Junta a página nova às já carregadas, sem repetir rotas (o "carregar mais" pode sobrepor se algo mudou). */
export function juntarPaginas(anteriores, novas) {
  const vistos = new Set(anteriores.map((r) => r.id));
  return [...anteriores, ...novas.filter((r) => !vistos.has(r.id))];
}

/** Resumo no topo: "3 rotas · 8 pedidos" (rotas desfeitas não entram na soma). */
export function resumoDoHistorico(rotas) {
  const validas = rotas.filter((r) => r.status === 'confirmada');
  const pedidos = validas.reduce((s, r) => s + (Number(r.qtd_pedidos) || 0), 0);
  return `${validas.length} ${validas.length === 1 ? 'rota' : 'rotas'} · ${pedidos} ${pedidos === 1 ? 'pedido' : 'pedidos'}`;
}
