// Bloco "Janelas de entrega" (Etapa 11): chegada estimada em cada parada e pedidos fora do prazo, por rota. INFORMATIVO: nunca muda as rotas, nunca bloqueia e
// nada é gravado. Recolhível: abre sozinho quando há pedido fora do prazo (o operador pode fechar ou abrir depois). A hora de saída é opcional
// (vazio = início da janela da loja no turno): campo de texto "HH:MM" que aceita 8, 830, 1230, 8:30 e 08h30, com botões de 15 minutos e "Usar padrão". Mostra o id do pedido, como a lista de pedidos já faz; nunca cliente nem telefone.
import { useEffect, useState } from 'react';
import { Clock, ChevronDown, ChevronRight, AlertTriangle } from 'lucide-react';
import { resumoDoRelatorio, minutosParaHora, normalizarHoraDigitada, somarMinutos, resumoDaSaida } from '../services/janelas';

export default function JanelasDeEntrega({ relatorio, horaDeSaida, onHoraDeSaida }) {
  const [aberto, setAberto] = useState(relatorio.foraDoPrazo > 0);
  // Abre sozinho quando aparece pedido fora do prazo (e fecha quando deixa de haver), sem brigar com o clique do operador entre uma mudança e outra.
  useEffect(() => { setAberto(relatorio.foraDoPrazo > 0); }, [relatorio.foraDoPrazo > 0]); // eslint-disable-line react-hooks/exhaustive-deps
  const Seta = aberto ? ChevronDown : ChevronRight;
  const resumo = resumoDoRelatorio(relatorio);
  const [texto, setTexto] = useState(horaDeSaida);
  const [erroDaHora, setErroDaHora] = useState('');
  useEffect(() => { setTexto(horaDeSaida); setErroDaHora(''); }, [horaDeSaida]);
  const padrao = relatorio.saidaPadrao;
  const textoDoPadrao = padrao !== null ? minutosParaHora(padrao) : '';

  // Confirma o que foi digitado (ao sair do campo ou com Enter): normaliza para HH:MM; inválido mostra a mensagem e não é usado.
  const confirmar = () => {
    const r = normalizarHoraDigitada(texto);
    if (r.ok) { setErroDaHora(''); setTexto(r.valor); onHoraDeSaida(r.valor); } else setErroDaHora(r.mensagem);
  };
  const passo = (delta) => { setErroDaHora(''); onHoraDeSaida(somarMinutos(horaDeSaida, delta, padrao)); };
  const botao = 'px-2 py-1 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 text-[11px] font-mono';

  return (
    <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 space-y-2" aria-label="Janelas de entrega">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" onClick={() => setAberto((a) => !a)} aria-expanded={aberto} className="flex items-center gap-1.5 text-left">
          <Seta className="w-3.5 h-3.5 text-slate-400" />
          <Clock className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Janelas de entrega</span>
          {resumo && <span className={`text-[11px] ${relatorio.foraDoPrazo > 0 ? 'text-amber-300' : 'text-slate-400'}`}>· {resumo}</span>}
        </button>
      </div>

      <div className="space-y-1.5">
        <p className="text-[11px] text-slate-400">A que horas os motoristas saem da loja? Usado só para estimar a chegada em cada pedido.</p>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => passo(-15)} className={botao} aria-label="Sair 15 minutos mais cedo">−15 min</button>
          <input
            type="text" inputMode="numeric" value={texto} placeholder={textoDoPadrao || 'HH:MM'} aria-label="Hora de saída da loja (HH:MM)"
            aria-invalid={Boolean(erroDaHora)} onChange={(e) => setTexto(e.target.value)} onBlur={confirmar}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); confirmar(); } }}
            className="w-20 px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-xs font-mono text-center focus:outline-none focus:border-blue-500"
          />
          <button type="button" onClick={() => passo(15)} className={botao} aria-label="Sair 15 minutos mais tarde">+15 min</button>
          {horaDeSaida && (
            <button type="button" onClick={() => { setErroDaHora(''); onHoraDeSaida(''); }} className="px-2 py-1 rounded border border-violet-500/30 text-violet-300 hover:bg-violet-500/10 text-[11px]">
              Usar padrão{textoDoPadrao ? ` (${textoDoPadrao})` : ''}
            </button>
          )}
          <span className="text-[11px] font-semibold text-slate-200">{resumoDaSaida(horaDeSaida, padrao)}</span>
        </div>
        {erroDaHora && <p className="text-[11px] text-amber-300" role="alert">{erroDaHora}</p>}
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
