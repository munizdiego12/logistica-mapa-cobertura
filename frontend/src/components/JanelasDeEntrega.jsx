// Bloco "Janelas de entrega" (Etapa 11): chegada estimada em cada parada e pedidos fora do prazo, por rota. INFORMATIVO: nunca muda as rotas, nunca bloqueia e
// nada é gravado. Recolhível: abre sozinho quando há pedido fora do prazo (o operador pode fechar ou abrir depois). A hora de saída é opcional
// (vazio = início da janela da loja no turno). Mostra o id do pedido, como a lista de pedidos já faz; nunca cliente nem telefone.
import { useEffect, useState } from 'react';
import { Clock, ChevronDown, ChevronRight, AlertTriangle } from 'lucide-react';
import { resumoDoRelatorio, minutosParaHora } from '../services/janelas';

export default function JanelasDeEntrega({ relatorio, horaDeSaida, onHoraDeSaida }) {
  const [aberto, setAberto] = useState(relatorio.foraDoPrazo > 0);
  // Abre sozinho quando aparece pedido fora do prazo (e fecha quando deixa de haver), sem brigar com o clique do operador entre uma mudança e outra.
  useEffect(() => { setAberto(relatorio.foraDoPrazo > 0); }, [relatorio.foraDoPrazo > 0]); // eslint-disable-line react-hooks/exhaustive-deps
  const Seta = aberto ? ChevronDown : ChevronRight;
  const resumo = resumoDoRelatorio(relatorio);

  return (
    <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 space-y-2" aria-label="Janelas de entrega">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={() => setAberto((a) => !a)} aria-expanded={aberto} className="flex items-center gap-1.5 text-left">
          <Seta className="w-3.5 h-3.5 text-slate-400" />
          <Clock className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Janelas de entrega</span>
          {resumo && <span className={`text-[11px] ${relatorio.foraDoPrazo > 0 ? 'text-amber-300' : 'text-slate-400'}`}>· {resumo}</span>}
        </button>
        <label className="flex items-center gap-2 text-[11px] text-slate-400">
          Hora de saída
          <input
            type="time" value={horaDeSaida} onChange={(e) => onHoraDeSaida(e.target.value)} aria-label="Hora de saída da loja"
            className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-xs font-mono focus:outline-none focus:border-blue-500"
          />
          <span className="text-[10px] text-slate-500">
            {horaDeSaida ? '' : relatorio.saidaPadrao !== null ? `padrão: ${minutosParaHora(relatorio.saidaPadrao)}` : 'opcional'}
          </span>
        </label>
      </div>

      {aberto && (
        <div className="space-y-2">
          {relatorio.mensagens.map((m) => <p key={m} className="text-[11px] text-slate-400">{m}</p>)}
          {relatorio.status === 'ok' && (
            <p className="text-[10px] text-slate-500">
              Estimativa: a 1ª viagem de cada motorista sai na hora de saída e a seguinte, quando a anterior volta à loja; o tempo por parada é o usado ao gerar as rotas.
            </p>
          )}
          {relatorio.status === 'ok' && relatorio.rotas.length === 0 && <p className="text-[11px] text-emerald-300">Todos os pedidos chegam dentro das janelas.</p>}
          {relatorio.rotas.map((r) => (
            <div key={r.rotaId} className="rounded-lg bg-slate-950/50 border border-slate-800 p-2.5 space-y-1">
              <p className="text-[11px] font-semibold text-slate-200">
                {r.titulo} <span className="font-normal text-slate-400">· sai às {r.saida}</span>
                {r.fora.length > 0 && <span className="font-normal text-amber-300"> · {r.fora.length} de {r.total} {r.total === 1 ? 'pedido' : 'pedidos'} fora do prazo</span>}
              </p>
              {r.fora.map((p) => (
                <p key={`f-${p.id}`} className="flex items-start gap-1.5 text-[11px] text-amber-200">
                  <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" /> <span><span className="font-mono text-amber-100">#{p.id}</span> · {p.texto}</span>
                </p>
              ))}
              {r.antes.map((p) => (
                <p key={`a-${p.id}`} className="text-[10px] text-slate-500"><span className="font-mono">#{p.id}</span> · {p.texto}</p>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
