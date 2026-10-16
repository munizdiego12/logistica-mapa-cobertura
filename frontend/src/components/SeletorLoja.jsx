// Campo de pesquisa com lista (combobox) para escolher a loja de origem.
// O operador digita e a lista filtra na hora por nome, cidade e UF (sem diferença de maiúsculas, acentos nem espaços extras).
// Teclado: setas, Enter escolhe, Esc fecha, Tab sai. Leitor de tela: padrão ARIA de combobox com lista (role="combobox" + role="listbox").
// "Outro endereço" fica sempre no fim da lista. Escolher aqui faz o mesmo que clicar na loja no mapa (quem decide é o App).
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { Search, ChevronDown, Check } from 'lucide-react';
import { filtrarLojas, destacarTrechos, cidadeEUf, moverDestaque, ROTULO_OUTRO_ENDERECO } from '../services/lojas';

function Destacado({ texto, busca }) {
  return destacarTrechos(texto, busca).map((trecho, i) => (
    trecho.destaque
      ? <mark key={i} className="bg-transparent text-blue-300 font-bold underline decoration-blue-400/60 underline-offset-2">{trecho.texto}</mark>
      : <span key={i}>{trecho.texto}</span>
  ));
}

export default function SeletorLoja({ lojas, selecaoHub, onEscolherLoja, onOutroEndereco }) {
  const idBase = useId();
  const idLista = `${idBase}-lista`;
  const idOpcao = (i) => `${idBase}-opcao-${i}`;
  const raiz = useRef(null);
  const entrada = useRef(null);
  const lista = useRef(null);

  const [aberta, setAberta] = useState(false);
  // Texto digitado. Vale só para a escolha atual: se a loja muda (ex.: clique no mapa), o texto digitado é ignorado
  // e o campo volta a mostrar o nome da loja escolhida.
  const [edicao, setEdicao] = useState(null); // { chave, texto } | null
  const [ativo, setAtivo] = useState(0);

  const lojaEscolhida = lojas.find((l) => String(l.id) === selecaoHub) || null;
  const rotuloEscolhido = selecaoHub === 'outro' ? ROTULO_OUTRO_ENDERECO : (lojaEscolhida ? lojaEscolhida.nome : '');
  const editando = edicao !== null && edicao.chave === selecaoHub;
  const busca = editando ? edicao.texto : '';

  const resultados = useMemo(() => filtrarLojas(lojas, busca), [lojas, busca]);
  const opcoes = useMemo(() => [...resultados.map((r) => ({ tipo: 'loja', loja: r.loja })), { tipo: 'outro' }], [resultados]);
  const indiceAtivo = Math.min(ativo, opcoes.length - 1);

  // Mantém a opção em destaque visível na lista (rolagem).
  useEffect(() => {
    if (!aberta || !lista.current) return;
    const elemento = lista.current.querySelector(`[id="${idOpcao(indiceAtivo)}"]`);
    if (elemento?.scrollIntoView) elemento.scrollIntoView({ block: 'nearest' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aberta, indiceAtivo, busca]);

  const fechar = () => {
    setAberta(false);
    setEdicao(null);
  };

  const escolher = (opcao) => {
    fechar();
    if (opcao.tipo === 'outro') onOutroEndereco();
    else onEscolherLoja(opcao.loja.id);
  };

  const abrir = () => {
    if (aberta) return;
    const posicao = lojaEscolhida ? opcoes.findIndex((o) => o.tipo === 'loja' && o.loja.id === lojaEscolhida.id) : -1;
    setAtivo(posicao >= 0 ? posicao : 0);
    setAberta(true);
  };

  const aoDigitar = (e) => {
    setEdicao({ chave: selecaoHub, texto: e.target.value });
    setAtivo(0);
    setAberta(true);
  };

  const aoTeclar = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!aberta) { abrir(); return; }
      setAtivo(moverDestaque(indiceAtivo, e.key === 'ArrowDown' ? 1 : -1, opcoes.length));
    } else if (e.key === 'Enter') {
      if (aberta && opcoes[indiceAtivo]) {
        e.preventDefault();
        escolher(opcoes[indiceAtivo]);
      } else if (!aberta) {
        e.preventDefault();
        abrir();
      }
    } else if (e.key === 'Escape') {
      if (aberta || editando) {
        e.preventDefault();
        fechar();
      }
    } else if (e.key === 'Tab') {
      fechar(); // sai do campo sem escolher nada
    }
  };

  const aoSairDoCampo = (e) => {
    if (!raiz.current?.contains(e.relatedTarget)) fechar();
  };

  const nenhuma = resultados.length === 0;
  const textoDoAviso = nenhuma
    ? 'Nenhuma loja encontrada'
    : `${resultados.length} ${resultados.length === 1 ? 'loja encontrada' : 'lojas encontradas'}`;

  return (
    <div ref={raiz} className="relative" onBlur={aoSairDoCampo}>
      <div className="relative">
        <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" aria-hidden="true" />
        <input
          ref={entrada}
          type="text"
          role="combobox"
          aria-label="Loja de origem"
          aria-expanded={aberta}
          aria-controls={idLista}
          aria-autocomplete="list"
          aria-haspopup="listbox"
          aria-activedescendant={aberta && opcoes[indiceAtivo] ? idOpcao(indiceAtivo) : undefined}
          autoComplete="off"
          spellCheck={false}
          value={editando ? edicao.texto : rotuloEscolhido}
          placeholder="Pesquise a loja (nome, cidade ou UF)"
          onChange={aoDigitar}
          onKeyDown={aoTeclar}
          onFocus={(e) => { e.target.select(); abrir(); }}
          onClick={abrir}
          className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg pl-8 pr-8 py-2.5 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
        />
        <ChevronDown className={`w-3.5 h-3.5 text-slate-500 absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none transition-transform ${aberta ? 'rotate-180' : ''}`} aria-hidden="true" />
      </div>

      {/* Anuncia para o leitor de tela quantas lojas a pesquisa achou */}
      <p role="status" aria-live="polite" className="sr-only">{aberta ? textoDoAviso : ''}</p>

      {aberta && (
        <ul
          ref={lista}
          id={idLista}
          role="listbox"
          aria-label="Lojas"
          className="absolute z-30 left-0 right-0 mt-1 max-h-60 overflow-y-auto rounded-lg bg-slate-900 border border-slate-700 shadow-xl shadow-black/50 py-1"
        >
          {nenhuma && (
            <li role="presentation" className="px-3 py-2 text-[11px] text-slate-500">Nenhuma loja encontrada</li>
          )}
          {opcoes.map((opcao, i) => {
            const ehLoja = opcao.tipo === 'loja';
            const escolhida = ehLoja ? String(opcao.loja.id) === selecaoHub : selecaoHub === 'outro';
            const destacada = i === indiceAtivo;
            return (
              <li
                key={ehLoja ? `loja-${opcao.loja.id}` : 'outro'}
                id={idOpcao(i)}
                role="option"
                aria-selected={escolhida}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => escolher(opcao)}
                onMouseEnter={() => setAtivo(i)}
                className={`flex items-start justify-between gap-2 px-3 py-1.5 cursor-pointer ${destacada ? 'bg-blue-600/25' : ''} ${!ehLoja ? 'border-t border-slate-800 mt-1' : ''}`}
              >
                <span className="min-w-0">
                  {ehLoja ? (
                    <>
                      <span className="block text-xs text-slate-100 truncate"><Destacado texto={opcao.loja.nome} busca={busca} /></span>
                      {cidadeEUf(opcao.loja) && (
                        <span className="block text-[10px] text-slate-400 truncate"><Destacado texto={cidadeEUf(opcao.loja)} busca={busca} /></span>
                      )}
                    </>
                  ) : (
                    <span className="block text-xs text-slate-300">{ROTULO_OUTRO_ENDERECO}</span>
                  )}
                </span>
                {escolhida && <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" aria-hidden="true" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
