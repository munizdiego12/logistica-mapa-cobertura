// "Mover para…" (Etapa 10b): botão de cada parada da matriz de despacho que abre a lista das OUTRAS rotas (motorista e viagem, pedidos e km atuais,
// inclusive as vazias e outras viagens do mesmo motorista). Escolher manda o movimento ao servidor, que reordena as paradas. Mover nunca é bloqueado
// por teto, rotação, km, janela ou peso (só avisam); depois de confirmar fica travado. Abre em posição fixa para não ser cortado pela rolagem da tabela.
// Nada de cliente aqui.
import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRightLeft, Search } from 'lucide-react';
import { deveFecharNoScroll } from '../services/despacho';
import { opcoesDeDestino } from '../services/movimentos';

export default function SeletorRotaDestino({ rotas, rotaAtualId, pedidoId, onEscolher, desabilitado = false, motivoDesabilitado = '' }) {
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState('');
  const [ativo, setAtivo] = useState(0);
  const [posicao, setPosicao] = useState({ top: 0, left: 0 });
  const botao = useRef(null);
  const caixa = useRef(null);

  const opcoes = useMemo(() => (aberto ? opcoesDeDestino(rotas, rotaAtualId, busca) : []), [aberto, rotas, rotaAtualId, busca]);

  const fechar = () => { setAberto(false); setBusca(''); setAtivo(0); };
  const abrir = () => {
    const r = botao.current?.getBoundingClientRect();
    if (r) setPosicao({ top: Math.min(r.bottom + 4, window.innerHeight - 320), left: Math.max(8, Math.min(r.left, window.innerWidth - 304)) });
    setAberto(true);
  };
  const escolher = (opcao) => { fechar(); if (opcao) onEscolher(opcao.id); botao.current?.focus(); };

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
    else if (e.key === 'ArrowDown') { e.preventDefault(); setAtivo((i) => Math.min(i + 1, Math.max(0, opcoes.length - 1))); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setAtivo((i) => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); escolher(opcoes[ativo]); }
  };

  return (
    <>
      <button
        ref={botao} type="button" onClick={() => (aberto ? fechar() : abrir())} disabled={desabilitado}
        title={desabilitado ? motivoDesabilitado : 'Mover este pedido para outra rota; o sistema reordena as paradas'}
        aria-haspopup="listbox" aria-expanded={aberto} aria-label={`Mover o pedido ${pedidoId} para outra rota`}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-slate-700 text-[10px] text-slate-300 hover:bg-slate-800 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        <ArrowRightLeft className="w-3 h-3" /> Mover para…
      </button>
      {aberto && (
        <div ref={caixa} style={{ position: 'fixed', top: posicao.top, left: posicao.left }} className="z-[90] w-72 max-h-80 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900 shadow-2xl font-sans" onKeyDown={aoTeclar}>
          <label className="relative block p-2 border-b border-slate-800">
            <Search className="w-3 h-3 text-slate-500 absolute left-4 top-1/2 -translate-y-1/2" />
            <input
              autoFocus value={busca} onChange={(e) => { setBusca(e.target.value); setAtivo(0); }} placeholder="Pesquise a rota ou o motorista" aria-label="Pesquisar rota"
              className="w-full pl-6 pr-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-[11px] focus:outline-none focus:border-blue-500"
            />
          </label>
          <div role="listbox" aria-label={`Rotas para o pedido ${pedidoId}`}>
            {opcoes.length === 0 && <p className="p-3 text-center text-[11px] text-slate-500">Nenhuma outra rota encontrada</p>}
            {opcoes.map((o, i) => (
              <div
                key={o.id} role="option" aria-selected={i === ativo} onMouseEnter={() => setAtivo(i)} onClick={() => escolher(o)}
                className={`px-3 py-1.5 cursor-pointer text-[11px] ${i === ativo ? 'bg-slate-800' : ''}`}
              >
                <p className="font-semibold text-slate-100">{o.titulo}</p>
                <p className={`text-[10px] ${o.vazia ? 'text-slate-500' : 'text-slate-400'}`}>{o.detalhe}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
