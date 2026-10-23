// Troca do motorista de uma rota na matriz de despacho (Etapa 10). Botão com o motorista atual que abre uma lista de alternativas com pesquisa:
// marcados nesta roteirização primeiro e "outros desta loja" depois, cada um com tipo de veículo, rotas de hoje, rotas nesta roteirização e o selo
// de rotação. Trocar é sempre permitido (rotação e carga só avisam). A lista abre em posição fixa para não ser cortada pela rolagem da tabela.
// Nada de telefone, pedido, endereço ou cliente aqui.
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, AlertTriangle, Check, Search } from 'lucide-react';
import { deveFecharNoScroll } from '../services/despacho';

export default function SeletorMotoristaDaRota({ rota, alternativas, onEscolher, desabilitado = false, motivoDesabilitado = '' }) {
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState('');
  const [ativo, setAtivo] = useState(0);
  const [posicao, setPosicao] = useState({ top: 0, left: 0 });
  const botao = useRef(null);
  const caixa = useRef(null);

  const grupos = useMemo(() => (aberto ? alternativas(busca) : []), [aberto, alternativas, busca]);
  const itens = useMemo(() => grupos.flatMap((g) => g.itens), [grupos]);

  const fechar = () => { setAberto(false); setBusca(''); setAtivo(0); };
  const abrir = () => {
    const r = botao.current?.getBoundingClientRect();
    if (r) setPosicao({ top: Math.min(r.bottom + 4, window.innerHeight - 320), left: Math.max(8, Math.min(r.left, window.innerWidth - 336)) });
    setAberto(true);
  };
  const escolher = (item) => { fechar(); if (item && !item.atual) onEscolher(item.id); botao.current?.focus(); };

  // Fecha ao clicar fora, ao rolar a página (a rolagem da própria lista não fecha) ou ao redimensionar.
  useEffect(() => {
    if (!aberto) return undefined;
    const fora = (e) => { if (!caixa.current?.contains(e.target) && !botao.current?.contains(e.target)) fechar(); };
    document.addEventListener('mousedown', fora);
    window.addEventListener('resize', fechar);
    const aoRolar = (e) => { if (deveFecharNoScroll(e.target, caixa.current)) fechar(); };
    window.addEventListener('scroll', aoRolar, true);
    return () => { document.removeEventListener('mousedown', fora); window.removeEventListener('resize', fechar); window.removeEventListener('scroll', aoRolar, true); };
  }, [aberto]);

  const aoTeclar = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); fechar(); botao.current?.focus(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setAtivo((i) => Math.min(i + 1, Math.max(0, itens.length - 1))); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setAtivo((i) => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); escolher(itens[ativo]); }
  };

  let indice = -1;
  return (
    <>
      <button
        ref={botao} type="button" onClick={() => (aberto ? fechar() : abrir())} disabled={desabilitado} title={desabilitado ? motivoDesabilitado : 'Trocar o motorista desta rota'}
        aria-haspopup="listbox" aria-expanded={aberto} aria-label={`Motorista da rota ${rota.id}: ${rota.motorista_base || rota.motorista}. Trocar`}
        className="flex items-center gap-1 text-left text-white font-bold rounded px-1.5 py-0.5 hover:bg-slate-800 border border-transparent hover:border-slate-700 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:border-transparent"
      >
        {rota.motorista}
        {!desabilitado && <ChevronDown className="w-3 h-3 text-slate-400" />}
      </button>
      {aberto && (
        <div ref={caixa} style={{ position: 'fixed', top: posicao.top, left: posicao.left }} className="z-[90] w-80 max-h-80 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 shadow-2xl font-sans" onKeyDown={aoTeclar}>
          <label className="relative block p-2 border-b border-slate-800">
            <Search className="w-3 h-3 text-slate-500 absolute left-4 top-1/2 -translate-y-1/2" />
            <input
              autoFocus value={busca} onChange={(e) => { setBusca(e.target.value); setAtivo(0); }} placeholder="Pesquise o motorista (nome ou código)" aria-label="Pesquisar motorista"
              className="w-full pl-6 pr-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-[11px] focus:outline-none focus:border-blue-500"
            />
          </label>
          <div role="listbox" aria-label={`Motoristas para a rota ${rota.id}`}>
            {itens.length === 0 && <p className="p-3 text-center text-[11px] text-slate-500">Nenhum motorista encontrado</p>}
            {grupos.map((g) => (
              <div key={g.chave} role="group" aria-label={g.titulo}>
                <p className="px-3 pt-2 pb-1 text-[10px] font-bold uppercase tracking-wider text-slate-500">{g.titulo}</p>
                {g.itens.map((item) => {
                  indice += 1;
                  const meu = indice;
                  return (
                    <div
                      key={item.id} role="option" aria-selected={item.atual} onMouseEnter={() => setAtivo(meu)} onClick={() => escolher(item)}
                      className={`px-3 py-1.5 cursor-pointer text-[11px] ${meu === ativo ? 'bg-slate-800' : ''}`}
                    >
                      <p className="flex items-center gap-1.5 text-slate-100">
                        <span className="font-semibold">{item.nome}</span>
                        {item.tipo && <span className="text-[10px] text-slate-400">· {item.tipo}</span>}
                        {item.atual && <Check className="w-3 h-3 text-emerald-400 ml-auto" aria-label="Motorista atual" />}
                      </p>
                      <p className="text-[10px] text-slate-400">
                        {item.textoHoje} · {item.textoNesta}
                      </p>
                      {item.sugerido && <p className="text-[10px] text-emerald-300">sugerido pelo solver</p>}
                      {item.selo && (
                        <p className="flex items-center gap-1 text-[10px] text-amber-300"><AlertTriangle className="w-3 h-3 shrink-0" /> {item.selo}</p>
                      )}
                    </div>
                  );
                })}
                {g.maisNaoMostrados > 0 && <p className="px-3 pb-1 text-[10px] text-slate-500">Mais {g.maisNaoMostrados}: use a pesquisa para achar.</p>}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
