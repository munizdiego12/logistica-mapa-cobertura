// Relatório de validação do lote de pedidos, mostrado ANTES de aceitar: válidas, com erro e avisos, com o número da linha e o motivo.
// O operador pode aceitar só as linhas válidas. O arquivo não é guardado: o lote só vive na tela e é descartado depois do uso.
import { X, CheckCircle2, AlertTriangle, AlertCircle } from 'lucide-react';
import { textoDoErro } from '../services/pedidos';

const MAX_ERROS_NA_TELA = 100;

function Contador({ rotulo, valor, cor }) {
  return (
    <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
      <p className={`text-lg font-black font-mono ${cor}`}>{valor}</p>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{rotulo}</p>
    </div>
  );
}

export default function RelatorioImportacao({ nomeArquivo, relatorio, onAceitar, onCancelar }) {
  const { resumo, erros, erros_truncados: truncados, erros_por_motivo: porMotivo, avisos, lojas, datas } = relatorio;
  const validas = resumo.validas;
  const motivos = Object.entries(porMotivo || {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="fixed inset-0 z-[100] bg-slate-950/80 backdrop-blur-sm flex items-start justify-center p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-label="Relatório da importação">
      <div className="w-full max-w-2xl my-6 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <div className="min-w-0">
            <h2 className="text-base font-bold text-white">Conferir o arquivo antes de aceitar</h2>
            <p className="text-[11px] text-slate-400 truncate">{nomeArquivo}</p>
          </div>
          <button onClick={onCancelar} className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white" aria-label="Fechar">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="grid grid-cols-3 gap-2">
            <Contador rotulo="Linhas lidas" valor={resumo.linhas} cor="text-slate-200" />
            <Contador rotulo="Válidas" valor={validas} cor="text-emerald-400" />
            <Contador rotulo="Com erro" valor={resumo.com_erro} cor={resumo.com_erro ? 'text-red-400' : 'text-slate-500'} />
          </div>

          {(lojas.length > 0 || datas.length > 0) && (
            <p className="text-[11px] text-slate-400 leading-snug">
              {lojas.length > 0 && <>Lojas no arquivo: {lojas.map((l) => `${l.nome} (${l.quantidade})`).join(', ')}. </>}
              {datas.length > 0 && <>Datas de entrega: {datas.length}.</>}
            </p>
          )}

          {resumo.com_erro > 0 && (
            <section className="space-y-2">
              <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-red-400">
                <AlertCircle className="w-3.5 h-3.5" /> Linhas com erro (não serão aceitas)
              </h3>
              {motivos.length > 0 && (
                <p className="text-[11px] text-slate-400">{motivos.map(([m, q]) => `${m}: ${q}`).join(' • ')}</p>
              )}
              <div className="space-y-1 max-h-56 overflow-y-auto pr-1">
                {erros.slice(0, MAX_ERROS_NA_TELA).map((e) => (
                  <p key={e.linha} className="text-[11px] text-red-300 bg-red-950/30 rounded px-2.5 py-1.5">{textoDoErro(e)}</p>
                ))}
              </div>
              {(truncados || erros.length > MAX_ERROS_NA_TELA) && (
                <p className="text-[10px] text-slate-500">Mostrando as primeiras {Math.min(erros.length, MAX_ERROS_NA_TELA)} de {resumo.com_erro} linhas com erro. Corrija o arquivo para ver as demais.</p>
              )}
            </section>
          )}

          {avisos.length > 0 && (
            <section className="space-y-1.5">
              <h3 className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-amber-300">
                <AlertTriangle className="w-3.5 h-3.5" /> Avisos (as linhas são aceitas)
              </h3>
              {avisos.map((a) => (
                <p key={a.motivo} className="text-[11px] text-amber-200 bg-amber-950/20 rounded px-2.5 py-1.5">
                  {a.quantidade} linha(s): {a.motivo}
                  {a.linhas.length > 0 && <span className="text-amber-300/70"> (linhas {a.linhas.slice(0, 8).join(', ')}{a.quantidade > 8 ? ' ...' : ''})</span>}
                </p>
              ))}
            </section>
          )}

          {resumo.com_erro === 0 && validas > 0 && (
            <p className="flex items-center gap-1.5 text-[11px] text-emerald-300"><CheckCircle2 className="w-3.5 h-3.5" /> Nenhum erro encontrado.</p>
          )}
          {validas === 0 && <p className="text-[11px] text-amber-300">Nenhuma linha válida. Corrija o arquivo e envie de novo.</p>}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button onClick={onCancelar} className="px-3 py-1.5 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 text-xs">Cancelar</button>
            <button
              onClick={onAceitar}
              disabled={validas === 0}
              className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold"
            >
              {resumo.com_erro > 0 ? `Aceitar só as ${validas} válidas` : `Aceitar os ${validas} pedidos`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
