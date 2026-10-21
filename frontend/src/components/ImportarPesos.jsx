// Importação de vários itens: mostra o RELATÓRIO da validação (novos, já existentes, sem peso, inválidos, linha e motivo) antes de gravar.
// O servidor não guarda nada entre as etapas: ao confirmar, o mesmo arquivo é enviado de novo e revalidado. O peso é só informativo.
import { useState } from 'react';
import { X, Loader2, AlertCircle, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { quantosVaoSerImportados, textoDoErroDeLinha, textoDoResultado } from '../services/itensPesos';

const MAX_ERROS_NA_TELA = 100;

function Contador({ rotulo, valor, cor }) {
  return (
    <div className="p-2 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
      <p className={`text-base font-black font-mono ${cor}`}>{valor}</p>
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{rotulo}</p>
    </div>
  );
}

export default function ImportarPesos({ api, arquivo, relatorio, onImportado, onCancelar, tratarErro }) {
  const [atualizar, setAtualizar] = useState(false);
  const [incluirSemPeso, setIncluirSemPeso] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState('');
  const { resumo, erros } = relatorio;
  const total = quantosVaoSerImportados(resumo, { atualizar, incluirSemPeso });

  const confirmar = async () => {
    setEnviando(true);
    setErro('');
    try {
      const corpo = new FormData();
      corpo.append('file', arquivo);
      corpo.append('atualizar_existentes', atualizar ? 'true' : 'false');
      corpo.append('incluir_sem_peso', incluirSemPeso ? 'true' : 'false');
      const { data } = await api.post('/item-pesos/importar/confirmar', corpo);
      onImportado(textoDoResultado(data));
    } catch (err) {
      setErro(tratarErro(err, 'Não foi possível importar. Nada foi gravado: tente de novo.'));
    } finally {
      setEnviando(false);
    }
  };

  return (
    <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-3" aria-label="Relatório da importação">
      <div className="flex items-center justify-between">
        <div className="min-w-0">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Conferir o arquivo antes de importar</h3>
          <p className="text-[11px] text-slate-500 truncate">{arquivo.name}</p>
        </div>
        <button type="button" onClick={onCancelar} className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white" aria-label="Cancelar a importação">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Contador rotulo="Itens novos" valor={resumo.novos_com_peso + resumo.novos_sem_peso} cor="text-emerald-400" />
        <Contador rotulo="Já existem" valor={resumo.existentes} cor="text-slate-200" />
        <Contador rotulo="Sem peso" valor={resumo.sem_peso} cor={resumo.sem_peso ? 'text-amber-300' : 'text-slate-500'} />
        <Contador rotulo="Inválidos" valor={resumo.invalidos} cor={resumo.invalidos ? 'text-red-400' : 'text-slate-500'} />
      </div>

      {resumo.invalidos > 0 && (
        <section className="space-y-1.5">
          <h4 className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-red-400">
            <AlertCircle className="w-3.5 h-3.5" /> Linhas com erro (não serão importadas)
          </h4>
          <div className="space-y-1 max-h-44 overflow-y-auto pr-1">
            {erros.slice(0, MAX_ERROS_NA_TELA).map((e) => (
              <p key={e.linha} className="text-[11px] text-red-300 bg-red-950/30 rounded px-2.5 py-1.5">{textoDoErroDeLinha(e)}</p>
            ))}
          </div>
          {(relatorio.erros_truncados || erros.length > MAX_ERROS_NA_TELA) && (
            <p className="text-[10px] text-slate-500">Mostrando as primeiras {Math.min(erros.length, MAX_ERROS_NA_TELA)} de {resumo.invalidos} linhas com erro.</p>
          )}
        </section>
      )}

      <div className="space-y-1.5 text-[11px] text-slate-300">
        <label className="flex items-start gap-2">
          <input type="checkbox" checked={atualizar} onChange={(e) => setAtualizar(e.target.checked)} className="mt-0.5 accent-blue-500" />
          <span>
            Atualizar também os itens que já existem (nome, peso, fonte e confiança)
            <span className="block text-[10px] text-slate-500">
              Sem marcar, os {resumo.existentes} que já existem são ignorados. Um peso que um operador editou na tela nunca é sobrescrito
              {resumo.existentes_preservados > 0 && ` (${resumo.existentes_preservados} item(ns) neste arquivo ficariam como estão)`}.
            </span>
          </span>
        </label>
        <label className="flex items-start gap-2">
          <input type="checkbox" checked={incluirSemPeso} onChange={(e) => setIncluirSemPeso(e.target.checked)} className="mt-0.5 accent-blue-500" />
          <span>Incluir itens sem peso (entram na fila "sem peso")</span>
        </label>
      </div>

      {resumo.validas === 0 && (
        <p className="flex items-center gap-1.5 text-[11px] text-amber-300"><AlertTriangle className="w-3.5 h-3.5" /> Nenhuma linha válida. Corrija o arquivo e envie de novo.</p>
      )}
      {erro && <p className="flex items-center gap-1 text-[11px] text-amber-300"><AlertCircle className="w-3 h-3 shrink-0" /> {erro}</p>}

      <div className="flex items-center gap-2">
        <button type="button" onClick={confirmar} disabled={enviando || total === 0}
          className="flex items-center gap-1 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold">
          {enviando ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />} Importar {total} {total === 1 ? 'item' : 'itens'}
        </button>
        <button type="button" onClick={onCancelar} className="px-3 py-1.5 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 text-xs">Cancelar</button>
      </div>
    </div>
  );
}
