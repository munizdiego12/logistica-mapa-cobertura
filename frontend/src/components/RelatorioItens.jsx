// Relatório de validação do arquivo de itens do pedido, mostrado ANTES de aceitar (subetapa 3 do peso): válidas, com erro, avisos, pedidos fora do lote e
// SKUs novos ou sem peso (entram na fila "sem peso" da tela "Pesos dos itens" ao aceitar). O operador aceita só as linhas válidas.
// O arquivo não é guardado: os itens só vivem na tela, junto do lote. Informativo: nada daqui bloqueia a roteirização.
import { X, CheckCircle2, AlertTriangle, AlertCircle, Loader2 } from 'lucide-react';

const MAX_NA_TELA = 100;

function Contador({ rotulo, valor, cor }) {
  return (
    <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
      <p className={`text-lg font-black font-mono ${cor}`}>{valor}</p>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{rotulo}</p>
    </div>
  );
}

const textoDoErro = (e) => `Linha ${e.linha}${e.id_pedido ? ` (pedido ${e.id_pedido})` : ''}: ${e.motivos.join('; ')}`;
const textoDoSku = (s) => (s.descricao ? `${s.sku} · ${s.descricao}` : s.sku);

export default function RelatorioItens({ nomeArquivo, relatorio, enviando = false, onAceitar, onCancelar }) {
  const { resumo, erros, erros_truncados: truncados, avisos, pedidos_fora_do_lote: fora, total_pedidos_fora_do_lote: totalFora, skus_novos: novos, skus_sem_peso: semPeso } = relatorio;
  const validas = resumo.validas;

  return (
    <div className="fixed inset-0 z-[100] bg-slate-950/80 backdrop-blur-sm flex items-start justify-center p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-label="Relatório do arquivo de itens">
      <div className="w-full max-w-2xl my-6 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <div className="min-w-0">
            <h2 className="text-base font-bold text-white">Conferir o arquivo de itens antes de aceitar</h2>
            <p className="text-[11px] text-slate-400 truncate">{nomeArquivo}</p>
          </div>
          <button onClick={onCancelar} disabled={enviando} className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white disabled:opacity-40" aria-label="Fechar">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Contador rotulo="Linhas lidas" valor={resumo.linhas} cor="text-slate-200" />
            <Contador rotulo="Válidas" valor={validas} cor="text-emerald-400" />
            <Contador rotulo="Com erro" valor={resumo.invalidas} cor={resumo.invalidas ? 'text-red-400' : 'text-slate-500'} />
            <Contador rotulo="Fora do lote" valor={resumo.fora_do_lote} cor={resumo.fora_do_lote ? 'text-amber-300' : 'text-slate-500'} />
          </div>
          <p className="text-[11px] text-slate-400 leading-snug">
            {resumo.pedidos_com_itens} {resumo.pedidos_com_itens === 1 ? 'pedido' : 'pedidos'} com itens e {resumo.skus_distintos} {resumo.skus_distintos === 1 ? 'item diferente' : 'itens diferentes'}.
            O peso dos pedidos é uma estimativa e só serve de informação: nada é bloqueado.
          </p>

          {resumo.invalidas > 0 && (
            <section className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-red-400">
                <AlertCircle className="w-3.5 h-3.5" /> Linhas com erro (não serão aceitas)
              </h3>
              <div className="space-y-1 max-h-56 overflow-y-auto pr-1">
                {erros.slice(0, MAX_NA_TELA).map((e) => (
                  <p key={e.linha} className="text-[11px] text-red-300 bg-red-950/30 rounded px-2.5 py-1.5">{textoDoErro(e)}</p>
                ))}
              </div>
              {(truncados || erros.length > MAX_NA_TELA) && (
                <p className="text-[10px] text-slate-500">Mostrando as primeiras {Math.min(erros.length, MAX_NA_TELA)} de {resumo.invalidas} linhas com erro. Corrija o arquivo para ver as demais.</p>
              )}
            </section>
          )}

          {totalFora > 0 && (
            <section className="space-y-1.5">
              <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-amber-300">
                <AlertTriangle className="w-3.5 h-3.5" /> Pedidos que não estão neste lote (ignorados)
              </h3>
              <p className="text-[11px] text-amber-200 bg-amber-950/20 rounded px-2.5 py-1.5 break-words">
                {fora.join(', ')}{totalFora > fora.length ? ` e mais ${totalFora - fora.length}` : ''}
              </p>
            </section>
          )}

          {avisos.length > 0 && (
            <section className="space-y-1.5">
              <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-amber-300">
                <AlertTriangle className="w-3.5 h-3.5" /> Avisos (as linhas são aceitas)
              </h3>
              <div className="space-y-1 max-h-44 overflow-y-auto pr-1">
                {avisos.slice(0, MAX_NA_TELA).map((a, i) => (
                  <p key={`${a.linha}-${i}`} className="text-[11px] text-amber-200 bg-amber-950/20 rounded px-2.5 py-1.5">
                    {a.linha ? `Linha ${a.linha}: ` : ''}{a.motivo}
                  </p>
                ))}
              </div>
            </section>
          )}

          {(novos.length > 0 || semPeso.length > 0) && (
            <section className="space-y-1.5">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Itens que entram na fila "sem peso" ao aceitar</h3>
              <p className="text-[11px] text-slate-400">Depois de cadastrar o peso na tela "Pesos dos itens", o peso dos pedidos se recalcula.</p>
              <div className="space-y-0.5 max-h-36 overflow-y-auto pr-1">
                {[...novos.map((s) => ({ ...s, tipo: 'novo' })), ...semPeso.map((s) => ({ ...s, tipo: 'sem peso' }))].slice(0, MAX_NA_TELA).map((s) => (
                  <p key={`${s.tipo}-${s.sku}`} className="text-[11px] text-slate-300 break-words"><span className="font-mono">{textoDoSku(s)}</span> <span className="text-slate-500">({s.tipo === 'novo' ? 'novo no cadastro' : 'sem peso'})</span></p>
                ))}
              </div>
            </section>
          )}

          {resumo.invalidas === 0 && validas > 0 && (
            <p className="flex items-center gap-1.5 text-[11px] text-emerald-300"><CheckCircle2 className="w-3.5 h-3.5" /> Nenhum erro encontrado.</p>
          )}
          {validas === 0 && <p className="text-[11px] text-amber-300">Nenhuma linha válida. Corrija o arquivo e envie de novo.</p>}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button onClick={onCancelar} disabled={enviando} className="px-3 py-1.5 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-40 text-xs">Cancelar</button>
            <button
              onClick={onAceitar}
              disabled={validas === 0 || enviando}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold"
            >
              {enviando && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {enviando ? 'Aceitando...' : resumo.invalidas > 0 ? `Aceitar só as ${validas} válidas` : `Aceitar as ${validas} linhas`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
