// Campo de pesquisa com lista de seleção múltipla (combobox), usado nas lojas do motorista e na escolha dos motoristas da roteirização.
// O pai filtra, agrupa e LIMITA as opções (nunca se renderizam centenas de itens) e guarda o texto da busca; aqui ficam a abertura
// da lista, o teclado e a acessibilidade. Os marcados aparecem como etiquetas removíveis.
// Teclado: setas movem, Enter marca/desmarca (a lista continua aberta), Esc fecha, Tab sai. As etiquetas só saem pelo "x" de cada uma.
// Leitor de tela: padrão ARIA de combobox com lista (role="combobox" + role="listbox" aria-multiselectable + grupos).
//
// grupos: [{ chave, titulo, itens: [{ id, rotulo, detalhe?, aviso? }] }]   chips: [{ id, rotulo }]
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Search, ChevronDown, Check, X } from 'lucide-react';

export default function ComboboxMultiplo({
  rotulo, placeholder, grupos, selecionados, chips, busca, onBusca, onAlternar, onRemover,
  aviso = '', textoVazio = 'Nenhum resultado', desabilitado = false,
}) {
  const idBase = useId();
  const idLista = `${idBase}-lista`;
  const idOpcao = (i) => `${idBase}-opcao-${i}`;
  const raiz = useRef(null);
  const lista = useRef(null);
  const [aberta, setAberta] = useState(false);
  const [ativo, setAtivo] = useState(0);

  const marcados = useMemo(() => new Set(selecionados ?? []), [selecionados]);
  const opcoes = useMemo(() => (grupos ?? []).flatMap((g) => g.itens.map((item) => ({ ...item, grupo: g.chave }))), [grupos]);
  // Posição da primeira opção de cada grupo na lista corrida (o teclado anda pela lista inteira).
  const comecos = useMemo(() => (grupos ?? []).map((_, gi) => (grupos ?? []).slice(0, gi).reduce((soma, g) => soma + g.itens.length, 0)), [grupos]);
  const indiceAtivo = Math.min(ativo, Math.max(0, opcoes.length - 1));

  useEffect(() => {
    if (!aberta || !lista.current) return;
    const elemento = lista.current.querySelector(`[id="${idOpcao(indiceAtivo)}"]`);
    if (elemento?.scrollIntoView) elemento.scrollIntoView({ block: 'nearest' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberta, indiceAtivo, opcoes]);

  const aoTeclar = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!aberta) { setAberta(true); return; }
      if (opcoes.length > 0) setAtivo((indiceAtivo + (e.key === 'ArrowDown' ? 1 : -1) + opcoes.length) % opcoes.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (aberta && opcoes[indiceAtivo]) onAlternar(opcoes[indiceAtivo].id);
      else setAberta(true);
    } else if (e.key === 'Escape') {
      if (aberta) { e.preventDefault(); setAberta(false); }
    } else if (e.key === 'Tab') {
      setAberta(false);
    }
  };

  const aoSairDoCampo = (e) => {
    if (!raiz.current?.contains(e.relatedTarget)) setAberta(false);
  };

  const textoDoAviso = opcoes.length === 0 ? textoVazio : `${opcoes.length} ${opcoes.length === 1 ? 'opção' : 'opções'}${aviso ? `. ${aviso}` : ''}`;

  return (
    <div ref={raiz} className="relative space-y-1.5" onBlur={aoSairDoCampo}>
      {(chips ?? []).length > 0 && (
        <ul aria-label="Marcados" className="flex flex-wrap gap-1 max-h-24 overflow-y-auto pr-1">
          {chips.map((chip) => (
            <li key={chip.id} className="flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-full bg-blue-500/15 border border-blue-500/30 text-[11px] text-blue-100">
              <span className="max-w-[220px] truncate">{chip.rotulo}</span>
              <button
                type="button"
                onClick={() => onRemover(chip.id)}
                disabled={desabilitado}
                aria-label={`Remover ${chip.rotulo}`}
                className="p-0.5 rounded-full text-blue-300 hover:text-white hover:bg-blue-500/30"
              >
                <X className="w-3 h-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="relative">
        <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" aria-hidden="true" />
        <input
          type="text"
          role="combobox"
          aria-label={rotulo}
          aria-expanded={aberta}
          aria-controls={idLista}
          aria-autocomplete="list"
          aria-haspopup="listbox"
          aria-activedescendant={aberta && opcoes[indiceAtivo] ? idOpcao(indiceAtivo) : undefined}
          autoComplete="off"
          spellCheck={false}
          disabled={desabilitado}
          value={busca}
          placeholder={placeholder}
          onChange={(e) => { onBusca(e.target.value); setAtivo(0); setAberta(true); }}
          onKeyDown={aoTeclar}
          onFocus={() => setAberta(true)}
          onClick={() => setAberta(true)}
          className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg pl-8 pr-8 py-2.5 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors disabled:opacity-50"
        />
        <ChevronDown className={`w-3.5 h-3.5 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none transition-transform ${aberta ? 'rotate-180' : ''}`} aria-hidden="true" />
      </div>

      <p role="status" aria-live="polite" className="sr-only">{aberta ? textoDoAviso : ''}</p>

      {aberta && (
        <ul
          ref={lista}
          id={idLista}
          role="listbox"
          aria-label={rotulo}
          aria-multiselectable="true"
          className="absolute z-30 left-0 right-0 top-full mt-1 max-h-60 overflow-y-auto rounded-lg bg-slate-900 border border-slate-700 shadow-xl shadow-black/50 py-1"
        >
          {opcoes.length === 0 && <li role="presentation" className="px-3 py-2 text-[11px] text-slate-500">{textoVazio}</li>}
          {(grupos ?? []).map((grupo, gi) => (
            <li key={grupo.chave} role="presentation">
              <ul role="group" aria-label={grupo.titulo || rotulo}>
                {grupo.titulo && (
                  <li role="presentation" className="px-3 pt-1.5 pb-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">{grupo.titulo}</li>
                )}
                {grupo.itens.map((item, k) => {
                  const i = comecos[gi] + k;
                  const marcado = marcados.has(item.id);
                  return (
                    <li
                      key={item.id}
                      id={idOpcao(i)}
                      role="option"
                      aria-selected={marcado}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => onAlternar(item.id)}
                      onMouseEnter={() => setAtivo(i)}
                      className={`flex items-start justify-between gap-2 px-3 py-1.5 cursor-pointer ${i === indiceAtivo ? 'bg-blue-600/25' : ''}`}
                    >
                      <span className="min-w-0">
                        <span className="block text-xs text-slate-100 leading-snug">{item.rotulo}</span>
                        {item.detalhe && <span className="block text-[10px] text-slate-400 truncate">{item.detalhe}</span>}
                      </span>
                      {marcado && <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" aria-hidden="true" />}
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
          {aviso && <li role="presentation" className="px-3 py-1.5 text-[10px] text-amber-300/90 border-t border-slate-800 mt-1">{aviso}</li>}
        </ul>
      )}
    </div>
  );
}
