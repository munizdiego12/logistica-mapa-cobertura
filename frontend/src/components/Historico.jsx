// Histórico de rotas confirmadas (Etapa 12), em janela sem mapa, no estilo do histórico de um navegador:
// DIA > LOJA > "Motorista · Rota N" (abre e fecha) > pedidos. O endereço só aparece para o operador logado e some depois de ~90 dias;
// o operador de cada rota aparece só pelo nome. Nada daqui vai para console, log nem armazenamento do navegador.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { X, Search, Loader2, History, ChevronRight, ChevronDown, AlertCircle } from 'lucide-react';
import {
  agruparHistorico, tituloDaRota, detalheDaRota, linhaDoPedido, textoSemDetalhe, parametrosDoHistorico, juntarPaginas, resumoDoHistorico,
  TAMANHO_PAGINA_HISTORICO,
} from '../services/historico';

const campo = 'px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-[11px] focus:outline-none focus:border-blue-500';

function LinhaRota({ rota, dias }) {
  const [aberta, setAberta] = useState(false);
  const desfeita = rota.status === 'cancelada';
  const Seta = aberta ? ChevronDown : ChevronRight;
  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900/70">
      <button type="button" onClick={() => setAberta((a) => !a)} aria-expanded={aberta}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-[11px] hover:bg-slate-800/60 rounded-lg">
        <Seta className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        <span className={`font-semibold text-slate-100 ${desfeita ? 'line-through text-slate-500' : ''}`}>{tituloDaRota(rota)}</span>
        <span className={`text-slate-400 ${desfeita ? 'line-through' : ''}`}>{detalheDaRota(rota)}</span>
        {desfeita && <span className="text-[10px] text-red-300">desfeita</span>}
        {rota.operador && <span className="ml-auto text-[10px] text-slate-500 shrink-0">{rota.operador}</span>}
      </button>
      {aberta && (
        <div className="px-3 pb-2 pl-8 text-[11px]">
          {rota.sem_detalhe ? (
            <p className="text-slate-500 italic">{textoSemDetalhe}</p>
          ) : (
            <ol className={`space-y-0.5 ${desfeita ? 'line-through text-slate-500' : 'text-slate-300'}`}>
              {rota.pedidos.map((p) => <li key={`${rota.id}-${p.ordem}`} className="break-words">{linhaDoPedido(p, dias)}</li>)}
            </ol>
          )}
        </div>
      )}
    </li>
  );
}

export default function Historico({ api, onFechar }) {
  const [filtros, setFiltros] = useState({ de: '', ate: '', loja: '', motoristaId: '', operador: '', q: '', desfeitas: false });
  const [aplicados, setAplicados] = useState(filtros);
  const [opcoes, setOpcoes] = useState({ lojas: [], motoristas: [], operadores: [] });
  const [rotas, setRotas] = useState([]);
  const [info, setInfo] = useState({ hoje: '', dias_retencao: 90, tem_mais: false });
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState('');
  const geracao = useRef(0);

  const buscar = useCallback(async (f, deslocamento) => {
    const minha = ++geracao.current;
    setCarregando(true);
    setErro('');
    try {
      const { data } = await api.get('/historico', { params: parametrosDoHistorico(f, deslocamento) });
      if (minha !== geracao.current) return; // resposta de uma consulta antiga: descarta
      setRotas((atuais) => (deslocamento === 0 ? data.rotas : juntarPaginas(atuais, data.rotas)));
      setInfo({ hoje: data.hoje, dias_retencao: data.dias_retencao, tem_mais: data.tem_mais });
      setFiltros((atual) => (atual.de ? atual : { ...atual, de: data.de, ate: data.ate }));
    } catch (err) {
      if (minha !== geracao.current || err?.response?.status === 401) return; // 401: já voltou para o login, com o aviso
      const detalhe = err?.response?.data?.detail;
      setErro((typeof detalhe === 'string' && detalhe) || 'Não foi possível carregar o histórico agora. Tente de novo.');
    } finally {
      if (minha === geracao.current) setCarregando(false);
    }
  }, [api]);

  // Primeira consulta (período padrão de 7 dias) e a cada "Aplicar".
  useEffect(() => { buscar(aplicados, 0); }, [buscar, aplicados]);

  // Opções dos seletores, conforme o período aplicado.
  useEffect(() => {
    let ativo = true;
    const { de, ate } = aplicados;
    api.get('/historico/filtros', { params: { de: de || undefined, ate: ate || undefined } })
      .then(({ data }) => { if (ativo) setOpcoes(data); })
      .catch(() => { if (ativo) setOpcoes({ lojas: [], motoristas: [], operadores: [] }); });
    return () => { ativo = false; };
  }, [api, aplicados]);

  const grupos = useMemo(() => agruparHistorico(rotas, info.hoje), [rotas, info.hoje]);
  const mudar = (nome) => (e) => setFiltros((f) => ({ ...f, [nome]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));
  const aplicar = (e) => { e.preventDefault(); setAplicados({ ...filtros }); };

  return (
    <div className="fixed inset-0 z-[100] bg-slate-950/80 backdrop-blur-sm flex items-start justify-center p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-label="Histórico de rotas">
      <div className="w-full max-w-3xl my-6 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <History className="w-5 h-5 text-blue-400" />
            <h2 className="text-base font-bold text-white">Histórico de rotas</h2>
          </div>
          <button onClick={onFechar} className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white" aria-label="Fechar">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={aplicar} className="px-5 py-3 border-b border-slate-800 grid grid-cols-2 sm:grid-cols-4 gap-2 items-end">
          <label className="text-[10px] text-slate-400 space-y-0.5">De
            <input type="date" value={filtros.de} onChange={mudar('de')} className={`${campo} w-full`} />
          </label>
          <label className="text-[10px] text-slate-400 space-y-0.5">Até
            <input type="date" value={filtros.ate} onChange={mudar('ate')} className={`${campo} w-full`} />
          </label>
          <label className="text-[10px] text-slate-400 space-y-0.5">Loja
            <select value={filtros.loja} onChange={mudar('loja')} className={`${campo} w-full`}>
              <option value="">Todas</option>
              {opcoes.lojas.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>
          <label className="text-[10px] text-slate-400 space-y-0.5">Motorista
            <select value={filtros.motoristaId} onChange={mudar('motoristaId')} className={`${campo} w-full`}>
              <option value="">Todos</option>
              {opcoes.motoristas.map((m) => <option key={m.id} value={m.id}>{m.nome}</option>)}
            </select>
          </label>
          <label className="text-[10px] text-slate-400 space-y-0.5">Operador
            <select value={filtros.operador} onChange={mudar('operador')} className={`${campo} w-full`}>
              <option value="">Todos</option>
              {opcoes.operadores.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </label>
          <label className="relative block col-span-2 text-[10px] text-slate-400 space-y-0.5">Buscar
            <Search className="w-3 h-3 text-slate-500 absolute left-2 bottom-2" />
            <input value={filtros.q} onChange={mudar('q')} placeholder="Id do pedido ou trecho do endereço" aria-label="Buscar no histórico" className={`${campo} w-full pl-6`} />
          </label>
          <label className="flex items-center gap-1.5 text-[11px] text-slate-300 pb-1">
            <input type="checkbox" checked={filtros.desfeitas} onChange={mudar('desfeitas')} className="accent-blue-500" /> Mostrar rotas desfeitas
          </label>
          <button type="submit" className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-[11px] font-semibold">Aplicar</button>
        </form>

        <div className="px-5 py-3 space-y-3">
          <p className="text-[10px] text-slate-500 leading-snug">
            Mostra as rotas confirmadas. O endereço de cada pedido é removido {info.dias_retencao} dias depois da confirmação; o número do pedido, a cidade e os dados da rota ficam.
          </p>
          {erro && <p className="flex items-center gap-1.5 text-[11px] text-red-300" role="alert"><AlertCircle className="w-3.5 h-3.5 shrink-0" /> {erro}</p>}
          {!erro && rotas.length > 0 && <p className="text-[11px] font-mono text-slate-300">{resumoDoHistorico(rotas)}</p>}

          {grupos.map((dia) => (
            <section key={dia.dia} className="space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-blue-300 border-b border-slate-800 pb-1">{dia.rotulo}</h3>
              {dia.lojas.map((loja) => (
                <div key={loja.loja} className="space-y-1">
                  <p className="text-[11px] font-semibold text-slate-200">{loja.loja}</p>
                  <ul className="space-y-1">
                    {loja.rotas.map((r) => <LinhaRota key={r.id} rota={r} dias={info.dias_retencao} />)}
                  </ul>
                </div>
              ))}
            </section>
          ))}

          {carregando && <p className="flex items-center justify-center gap-1.5 py-3 text-[11px] text-slate-400"><Loader2 className="w-3.5 h-3.5 animate-spin" /> Carregando...</p>}
          {!carregando && !erro && rotas.length === 0 && <p className="py-6 text-center text-[11px] text-slate-500">Nenhuma rota confirmada neste período e com esses filtros.</p>}

          {info.tem_mais && !carregando && (
            <div className="text-center">
              <button type="button" onClick={() => buscar(aplicados, rotas.length)}
                className="px-3 py-1.5 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 text-[11px]">
                Carregar mais ({TAMANHO_PAGINA_HISTORICO} por vez)
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
