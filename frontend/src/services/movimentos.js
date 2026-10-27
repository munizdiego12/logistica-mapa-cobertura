// Mover um pedido entre rotas (Etapa 10b), antes de confirmar. Só funções puras: quem move é o SERVIDOR (é o resultado de lá que "Confirmar rotas" grava),
// a tela só manda o pedido, a rota de destino e a versão que mostra, e troca o resultado pelo que volta. O sistema escolhe a ordem das paradas; o operador
// nunca reordena à mão. Mover é sempre permitido (teto, rotação, km, janela e peso só avisam). Sem cliente aqui: a parada mostra só id e endereço curto.
import { textoPedidos } from './selecaoMotoristas.js';
import { rotaVazia } from './despacho.js';

export const MSG_MOVER_TRAVADO = 'Desfaça a confirmação para mover pedidos.';
export const MSG_FALHA_AO_MOVER = 'Não foi possível mover o pedido agora. Tente de novo.';
export const MSG_ROTA_SEM_PEDIDOS = 'Sem pedidos: não será confirmada';

const km = (valor) => `${Number(valor || 0).toFixed(1).replace('.', ',')} km`;

/** "Rua das Flores, 10 - Centro" (só o que existir). Nunca o cliente. */
export function enderecoCurto(parada) {
  const rua = [parada?.Endereco, parada?.Numero].map((t) => String(t ?? '').trim()).filter(Boolean).join(', ');
  const bairro = String(parada?.Bairro ?? '').trim();
  return rua && bairro ? `${rua} - ${bairro}` : (rua || bairro);
}

/** Paradas de uma rota, na ordem escolhida pelo sistema: [{ ordem, id, endereco }]. */
export function paradasDaRota(rota) {
  return (rota?.paradas ?? []).map((p, i) => ({ ordem: p.ordem ?? i + 1, id: String(p.id), endereco: enderecoCurto(p) }));
}

/**
 * Rotas para onde a parada pode ir: todas menos a atual, inclusive as vazias e outras viagens do mesmo motorista. `rotas`: as rotas efetivas
 * (com o motorista final da Etapa 10). Cada opção: { id, titulo: "Rota 2 · Ana • Viagem 2", detalhe: "3 pedidos · 12,4 km" ou "sem pedidos" }.
 */
export function opcoesDeDestino(rotas, rotaAtualId, busca = '') {
  const termo = String(busca ?? '').trim().toLowerCase();
  return (rotas ?? [])
    .filter((r) => r.id !== rotaAtualId)
    .map((r) => ({
      id: r.id,
      titulo: `Rota ${r.id} · ${rotaVazia(r) ? (r.motorista_base || r.motorista) : r.motorista}`,
      detalhe: rotaVazia(r) ? 'sem pedidos' : `${textoPedidos(r.qtd_pedidos)} · ${km(r.km_total)}`,
      vazia: rotaVazia(r),
    }))
    .filter((o) => !termo || o.titulo.toLowerCase().includes(termo));
}

/** Resumo depois de mover: "Pedido movido da Rota 1 para a Rota 2. Rota 1: 3 → 2 pedidos, 12,4 → 9,1 km; Rota 2: 2 → 3 pedidos, 8,0 → 10,2 km." */
export function textoDoMovimento(movimento) {
  if (!movimento) return '';
  const { rota_origem: de, rota_destino: para, antes = {}, depois = {} } = movimento;
  const parte = (id) => {
    const a = antes[String(id)] ?? {};
    const d = depois[String(id)] ?? {};
    return `Rota ${id}: ${a.qtd_pedidos ?? 0} → ${textoPedidos(d.qtd_pedidos ?? 0)}, ${km(a.km_total).replace(' km', '')} → ${km(d.km_total)}`;
  };
  return `Pedido movido da Rota ${de} para a Rota ${para}. ${parte(de)}; ${parte(para)}.`;
}

/** Corpo das chamadas de movimento: só o id do pedido, o número da rota e a versão (nada de endereço nem cliente). */
export function corpoDoMovimento(pedidoId, rotaDestino, versao) {
  return { pedido_id: String(pedidoId), rota_destino: Number(rotaDestino), versao: Number.isInteger(versao) ? versao : null };
}

/** Mensagem do erro em linguagem do operador: a do servidor quando houver; `recarregar` quando outra aba mudou a divisão (409 de versão). */
export function erroDoMovimento(err) {
  const status = err?.response?.status;
  const detalhe = err?.response?.data?.detail;
  const texto = (typeof detalhe === 'string' && detalhe) || MSG_FALHA_AO_MOVER;
  return { mensagem: texto, recarregar: status === 409 && texto !== MSG_MOVER_TRAVADO, expirado: status === 404 };
}
