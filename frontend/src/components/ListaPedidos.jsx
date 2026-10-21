// Lista de pedidos do lote ativo, com caixa de marcar: filtrada pela loja escolhida (o único filtro), com busca por id, cliente ou
// endereço, marcar/desmarcar todos os visíveis e paginação de 50 (lotes grandes). SÓ os pedidos marcados entram na roteirização.
// A data de entrega, quando vem no arquivo, aparece em letra pequena junto do pedido, só como informação: nunca filtra nem muda a roteirização.
// Pedido cujo endereço não foi localizado fica desmarcado e travado, com a mensagem combinada, até o operador corrigir o endereço.
// Cliente e endereço só existem na memória da tela: nada vai para console, log nem armazenamento do navegador.
import { useMemo, useState } from 'react';
import { Search, AlertTriangle, Pencil, ChevronLeft, ChevronRight, CheckSquare, Square, Save, X } from 'lucide-react';
import {
  filtrarPedidos, paginar, alternarMarca, marcarVisiveis, desmarcarVisiveis, todosVisiveisMarcados, contarMarcados, textoDoContador,
  temErroDeEndereco, dataParaExibir, MSG_ERRO_ENDERECO,
} from '../services/pedidos';

const campo = 'w-full px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-[11px] focus:outline-none focus:border-blue-500';

function Correcao({ pedido, aoSalvar, aoCancelar }) {
  const [form, setForm] = useState({
    endereco: pedido.endereco || '', numero: pedido.numero || '', bairro: pedido.bairro || '', cep: pedido.cep || '', cidade: pedido.cidade || '', uf: pedido.uf || '',
  });
  const mudar = (nome) => (e) => setForm((atual) => ({ ...atual, [nome]: e.target.value }));
  const valido = form.endereco.trim() && form.numero.trim() && form.cidade.trim() && form.uf.trim();
  return (
    <div className="mt-1.5 p-2 rounded bg-slate-950/70 border border-slate-800 space-y-1.5">
      <div className="grid grid-cols-[1fr_70px] gap-1.5">
        <input className={campo} value={form.endereco} onChange={mudar('endereco')} placeholder="Endereço" aria-label="Endereço" />
        <input className={campo} value={form.numero} onChange={mudar('numero')} placeholder="Número" aria-label="Número" />
      </div>
      <div className="grid grid-cols-[1fr_90px] gap-1.5">
        <input className={campo} value={form.bairro} onChange={mudar('bairro')} placeholder="Bairro" aria-label="Bairro" />
        <input className={campo} value={form.cep} onChange={mudar('cep')} placeholder="CEP" aria-label="CEP" />
      </div>
      <div className="grid grid-cols-[1fr_50px] gap-1.5">
        <input className={campo} value={form.cidade} onChange={mudar('cidade')} placeholder="Cidade" aria-label="Cidade" />
        <input className={campo} value={form.uf} maxLength={2} onChange={mudar('uf')} placeholder="UF" aria-label="UF" />
      </div>
      <div className="flex items-center gap-1.5">
        <button type="button" disabled={!valido} onClick={() => aoSalvar({ ...form, uf: form.uf.trim().toUpperCase() })}
          className="flex items-center gap-1 px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-[11px] font-semibold">
          <Save className="w-3 h-3" /> Salvar
        </button>
        <button type="button" onClick={aoCancelar} className="flex items-center gap-1 px-2 py-1 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 text-[11px]">
          <X className="w-3 h-3" /> Cancelar
        </button>
      </div>
    </div>
  );
}

export default function ListaPedidos({ pedidos, marcados, comErro, lojaId, lojaNome, aoMudarMarcados, aoCorrigir }) {
  const [busca, setBusca] = useState('');
  const [pagina, setPagina] = useState(1);
  const [corrigindo, setCorrigindo] = useState(null);

  const { visiveis, foraDaLoja, naLoja } = useMemo(() => filtrarPedidos(pedidos, { lojaId, busca }), [pedidos, lojaId, busca]);
  const contagem = useMemo(() => contarMarcados(pedidos, marcados, { lojaId, comErro }), [pedidos, marcados, lojaId, comErro]);
  const paginas = paginar(visiveis, pagina);
  const marcadosVisiveis = visiveis.filter((p) => marcados.has(p.id) && !temErroDeEndereco(p, comErro)).length;
  const todos = todosVisiveisMarcados(marcados, visiveis, comErro);

  const mudarFiltro = (aplicar) => (valor) => { aplicar(valor); setPagina(1); };

  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between text-[11px]">
        <span className="font-bold uppercase tracking-wider text-slate-400">Pedidos do lote</span>
        <span className="font-mono text-slate-300">{textoDoContador(contagem)}</span>
      </div>

      {lojaId !== null && foraDaLoja > 0 && (
        <p className="flex items-start gap-1.5 text-[11px] text-amber-300">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{foraDaLoja} pedido(s) de outras lojas ficaram de fora: a lista mostra só os de {lojaNome || 'a loja escolhida'} ({naLoja}).</span>
        </p>
      )}

      <div className="grid grid-cols-1 gap-1.5">
        <label className="relative block">
          <Search className="w-3 h-3 text-slate-500 absolute left-2 top-1/2 -translate-y-1/2" />
          <input value={busca} onChange={(e) => mudarFiltro(setBusca)(e.target.value)} placeholder="Buscar por id, cliente ou endereço"
            aria-label="Buscar pedido" className={`${campo} pl-6`} />
        </label>
      </div>

      <div className="flex items-center gap-1.5">
        <button type="button" onClick={() => aoMudarMarcados(marcarVisiveis(marcados, visiveis, comErro))} disabled={todos || visiveis.length === 0}
          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-40">
          <CheckSquare className="w-3 h-3" /> Marcar visíveis
        </button>
        <button type="button" onClick={() => aoMudarMarcados(desmarcarVisiveis(marcados, visiveis))} disabled={marcadosVisiveis === 0}
          className="flex items-center gap-1 px-2 py-1 rounded text-[11px] border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-40">
          <Square className="w-3 h-3" /> Desmarcar visíveis
        </button>
      </div>

      {visiveis.length === 0 && <p className="py-3 text-center text-[11px] text-slate-500">Nenhum pedido com esses filtros.</p>}

      <div className="space-y-1 max-h-80 overflow-y-auto pr-1">
        {paginas.itens.map((p) => {
          const erro = temErroDeEndereco(p, comErro);
          const marcado = marcados.has(p.id) && !erro;
          return (
            <div key={p.id} className={`p-2 rounded-lg border text-[11px] ${erro ? 'bg-red-950/20 border-red-500/30' : marcado ? 'bg-blue-500/10 border-blue-500/40' : 'bg-slate-900/70 border-slate-800'}`}>
              <div className="flex items-start gap-2">
                <input type="checkbox" checked={marcado} disabled={erro} onChange={() => aoMudarMarcados(alternarMarca(marcados, p.id))}
                  aria-label={`Marcar o pedido ${p.id}`} className="mt-0.5 accent-blue-500 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-slate-100 truncate">
                    <span className="font-mono text-slate-400">#{p.id}</span>{p.cliente ? ` · ${p.cliente}` : ''}
                  </p>
                  <p className="text-slate-300 truncate">{p.endereco}, {p.numero}{p.bairro ? ` · ${p.bairro}` : ''}</p>
                  <p className="text-slate-500">
                    {p.cidade}/{p.uf}{p.cep ? ` · ${p.cep}` : ''} · vol. {p.volume}
                    {p.janela_inicio ? ` · ${p.janela_inicio}-${p.janela_fim}` : ''}
                  </p>
                  {p.data_entrega && <p className="text-[9px] text-slate-600">Entrega: {dataParaExibir(p.data_entrega)} (só informação)</p>}
                  {erro && (
                    <p className="flex items-center gap-1 text-red-300 mt-0.5">
                      <AlertTriangle className="w-3 h-3 shrink-0" /> {MSG_ERRO_ENDERECO}
                    </p>
                  )}
                </div>
                {erro && corrigindo !== p.id && (
                  <button type="button" onClick={() => setCorrigindo(p.id)}
                    className="flex items-center gap-1 px-1.5 py-0.5 rounded border border-red-500/40 text-red-300 hover:bg-red-950/40 shrink-0">
                    <Pencil className="w-3 h-3" /> Corrigir
                  </button>
                )}
              </div>
              {erro && corrigindo === p.id && (
                <Correcao pedido={p} aoCancelar={() => setCorrigindo(null)} aoSalvar={(campos) => { aoCorrigir(p.id, campos); setCorrigindo(null); }} />
              )}
            </div>
          );
        })}
      </div>

      {paginas.totalPaginas > 1 && (
        <div className="flex items-center justify-between text-[11px] text-slate-400">
          <button type="button" onClick={() => setPagina(paginas.pagina - 1)} disabled={paginas.pagina <= 1}
            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-slate-700 hover:bg-slate-800 disabled:opacity-40">
            <ChevronLeft className="w-3 h-3" /> Anterior
          </button>
          <span className="font-mono">Página {paginas.pagina} de {paginas.totalPaginas}</span>
          <button type="button" onClick={() => setPagina(paginas.pagina + 1)} disabled={paginas.pagina >= paginas.totalPaginas}
            className="flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-slate-700 hover:bg-slate-800 disabled:opacity-40">
            Próxima <ChevronRight className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
}
