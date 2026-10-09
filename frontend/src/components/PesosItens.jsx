// Manutenção dos pesos dos itens: fila "sem peso" (mais vendidos primeiro) e lista de todos os itens.
// Qualquer operador logado pode editar; o sistema guarda quem alterou e quando.
// O peso é só uma informação para o operador: o sistema nunca bloqueia nem avisa por capacidade.
import { useCallback, useEffect, useRef, useState } from 'react';
import { X, Search, Loader2, Save, AlertCircle, CheckCircle2, Scale, RotateCcw } from 'lucide-react';

const POR_PAGINA = 50;
const CONFIANCAS = [
  { valor: 'alta', rotulo: 'Conferido (alta)' },
  { valor: 'media', rotulo: 'Média' },
  { valor: 'baixa', rotulo: 'Incerto (baixa)' },
];

const formatarPeso = (kg) =>
  kg === null || kg === undefined ? '' : Number(kg).toLocaleString('pt-BR', { maximumFractionDigits: 4 });

const formatarData = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
};

const textoDoErro = (err, padrao) => {
  const detalhe = err?.response?.data?.detail;
  return typeof detalhe === 'string' && detalhe ? detalhe : padrao;
};

function quemAlterou(item) {
  if (!item.atualizado_por) return '';
  const autor = item.atualizado_por.startsWith('carga inicial') ? 'carga inicial' : item.atualizado_por;
  const quando = formatarData(item.atualizado_em);
  return `Alterado por ${autor}${quando ? ` em ${quando}` : ''}`;
}

function LinhaItem({ item, naFila, onSalvar, onRemover }) {
  const [peso, setPeso] = useState(formatarPeso(item.peso_kg));
  const [confianca, setConfianca] = useState(item.confianca || 'alta');
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState('');

  const mudou = peso.trim() !== formatarPeso(item.peso_kg) || (item.peso_kg !== null && confianca !== (item.confianca || 'alta'));
  const pesoValido = /^\d+([.,]\d+)?$/.test(peso.trim());

  const salvar = async () => {
    if (!pesoValido) {
      setErro('Digite o peso em kg, por exemplo 1,5');
      return;
    }
    setErro('');
    setSalvando(true);
    const mensagem = await onSalvar(item, peso.trim(), confianca);
    setSalvando(false);
    if (mensagem) setErro(mensagem);
  };

  const remover = async () => {
    if (!window.confirm('Tirar o peso deste item? Ele volta para a fila "sem peso".')) return;
    setSalvando(true);
    const mensagem = await onRemover(item);
    setSalvando(false);
    if (mensagem) setErro(mensagem);
  };

  return (
    <div className="p-3 rounded-lg bg-slate-900/70 border border-slate-800 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-100 truncate" title={item.nome || ''}>
            {item.nome || 'Item sem nome cadastrado'}
          </p>
          <p className="text-[11px] text-slate-500 font-mono">
            código {item.id_sku}{item.reference_code ? ` • ref. ${item.reference_code}` : ''}
          </p>
        </div>
        <span className="shrink-0 text-[11px] text-slate-400">
          {Number(item.unidades_vendidas).toLocaleString('pt-BR')} un. vendidas
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
          Peso (kg)
          <input
            type="text"
            inputMode="decimal"
            value={peso}
            onChange={(e) => setPeso(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && mudou) salvar(); }}
            placeholder="ex.: 1,5"
            aria-label={`Peso em kg de ${item.nome || item.id_sku}`}
            className="w-24 px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm font-mono focus:outline-none focus:border-blue-500"
          />
        </label>
        <select
          value={confianca}
          onChange={(e) => setConfianca(e.target.value)}
          aria-label="Confiança no peso"
          className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-200 text-xs"
        >
          {CONFIANCAS.map((c) => <option key={c.valor} value={c.valor}>{c.rotulo}</option>)}
        </select>
        <button
          onClick={salvar}
          disabled={salvando || !mudou || peso.trim() === ''}
          className="flex items-center gap-1 px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold transition-colors"
        >
          {salvando ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} Salvar
        </button>
        {!naFila && item.peso_kg !== null && (
          <button
            onClick={remover}
            disabled={salvando}
            className="flex items-center gap-1 px-2 py-1 rounded text-slate-400 hover:text-amber-300 text-[11px] disabled:opacity-40"
            title="Tirar o peso e devolver o item para a fila"
          >
            <RotateCcw className="w-3 h-3" /> Tirar peso
          </button>
        )}
      </div>

      {erro && (
        <p className="flex items-center gap-1 text-[11px] text-amber-300"><AlertCircle className="w-3 h-3" /> {erro}</p>
      )}
      {quemAlterou(item) && <p className="text-[10px] text-slate-500">{quemAlterou(item)}</p>}
    </div>
  );
}

export default function PesosItens({ api, onFechar, onSessaoExpirada }) {
  const [aba, setAba] = useState('fila'); // 'fila' = só sem peso | 'todos'
  const [busca, setBusca] = useState('');
  const [buscaAplicada, setBuscaAplicada] = useState('');
  const [itens, setItens] = useState([]);
  const [temMais, setTemMais] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState('');
  const [resumo, setResumo] = useState(null);
  const [aviso, setAviso] = useState('');
  const geracao = useRef(0); // identifica a consulta atual: respostas de consultas antigas são descartadas

  // O App recria o logout a cada renderização: guardá-lo numa ref mantém a carga estável (sem refazer a consulta).
  const sessaoExpirada = useRef(onSessaoExpirada);
  useEffect(() => { sessaoExpirada.current = onSessaoExpirada; });

  const tratarErro = useCallback((err, padrao) => {
    if (err?.response?.status === 401) {
      sessaoExpirada.current?.();
      return 'Sua sessão expirou. Entre novamente.';
    }
    return textoDoErro(err, padrao);
  }, []);

  const atualizarResumo = useCallback(() => {
    api.get('/item-pesos/resumo').then(({ data }) => setResumo(data)).catch(() => setResumo(null));
  }, [api]);

  const buscarPagina = useCallback(async (deslocamento) => {
    const params = { limite: POR_PAGINA, deslocamento };
    if (aba === 'fila' && !buscaAplicada) {
      return (await api.get('/item-pesos/fila-sem-peso', { params })).data;
    }
    return (await api.get('/item-pesos', { params: { ...params, busca: buscaAplicada || undefined, somente_sem_peso: aba === 'fila' } })).data;
  }, [api, aba, buscaAplicada]);

  // Resumo na abertura.
  useEffect(() => {
    let ativo = true;
    api.get('/item-pesos/resumo').then(({ data }) => { if (ativo) setResumo(data); }).catch(() => { if (ativo) setResumo(null); });
    return () => { ativo = false; };
  }, [api]);

  // Primeira página sempre que a aba ou a busca mudam (respostas de consultas antigas são descartadas).
  useEffect(() => {
    let ativo = true;
    const minha = ++geracao.current;
    buscarPagina(0)
      .then((dados) => {
        if (!ativo) return;
        setItens(dados.itens);
        setTemMais(dados.tem_mais);
        setErro('');
      })
      .catch((err) => {
        if (!ativo) return;
        setItens([]);
        setTemMais(false);
        setErro(tratarErro(err, 'Não foi possível carregar os itens. Tente de novo.'));
      })
      .finally(() => { if (ativo && minha === geracao.current) setCarregando(false); });
    return () => { ativo = false; };
  }, [buscarPagina, tratarErro]);

  const carregarMais = async () => {
    const minha = geracao.current;
    setCarregando(true);
    try {
      const dados = await buscarPagina(itens.length);
      if (minha !== geracao.current) return;
      setItens((atuais) => [...atuais, ...dados.itens]);
      setTemMais(dados.tem_mais);
    } catch (err) {
      if (minha === geracao.current) setErro(tratarErro(err, 'Não foi possível carregar mais itens. Tente de novo.'));
    } finally {
      if (minha === geracao.current) setCarregando(false);
    }
  };

  // Espera o operador parar de digitar antes de buscar.
  useEffect(() => {
    const t = setTimeout(() => {
      const nova = busca.trim();
      if (nova !== buscaAplicada) {
        setCarregando(true);
        setBuscaAplicada(nova);
      }
    }, 400);
    return () => clearTimeout(t);
  }, [busca, buscaAplicada]);

  const mostrarAviso = (texto) => {
    setAviso(texto);
    setTimeout(() => setAviso(''), 3500);
  };

  // Devolve uma mensagem de erro (texto) ou '' quando deu certo.
  const salvarPeso = async (item, pesoTexto, confianca) => {
    try {
      const { data } = await api.put(`/item-pesos/${encodeURIComponent(item.id_sku)}`, { peso_kg: pesoTexto, confianca });
      setItens((atuais) => (aba === 'fila'
        ? atuais.filter((i) => i.id_sku !== item.id_sku) // saiu da fila
        : atuais.map((i) => (i.id_sku === item.id_sku ? data : i))));
      atualizarResumo();
      mostrarAviso(`Peso de "${item.nome || item.id_sku}" salvo.`);
      return '';
    } catch (err) {
      return tratarErro(err, 'Não foi possível salvar. Tente de novo.');
    }
  };

  const removerPeso = async (item) => {
    try {
      const { data } = await api.put(`/item-pesos/${encodeURIComponent(item.id_sku)}`, { peso_kg: null });
      setItens((atuais) => atuais.map((i) => (i.id_sku === item.id_sku ? data : i)));
      atualizarResumo();
      mostrarAviso(`"${item.nome || item.id_sku}" voltou para a fila "sem peso".`);
      return '';
    } catch (err) {
      return tratarErro(err, 'Não foi possível tirar o peso. Tente de novo.');
    }
  };

  const trocarAba = (nova) => {
    if (nova === aba) return;
    setItens([]);
    setErro('');
    setCarregando(true);
    setAba(nova);
  };

  return (
    <div className="fixed inset-0 z-[100] bg-slate-950/80 backdrop-blur-sm flex items-start justify-center p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-label="Pesos dos itens">
      <div className="w-full max-w-3xl my-6 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Scale className="w-5 h-5 text-blue-400" />
            <h2 className="text-base font-bold text-white">Pesos dos itens</h2>
          </div>
          <button onClick={onFechar} className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white" aria-label="Fechar">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-5 py-3 space-y-3">
          <p className="text-[11px] text-slate-400 leading-snug">
            O peso é só uma informação para o operador: o sistema mostra o peso estimado dos pedidos, mas nunca bloqueia
            nem avisa por capacidade de veículo. Qualquer operador pode editar; fica registrado quem alterou e quando.
          </p>

          {resumo && (
            <div className="flex flex-wrap gap-2 text-[11px]">
              <span className="px-2 py-1 rounded bg-slate-800 text-slate-300">{resumo.total.toLocaleString('pt-BR')} itens cadastrados</span>
              <span className="px-2 py-1 rounded bg-emerald-950/40 border border-emerald-500/30 text-emerald-300">{resumo.com_peso.toLocaleString('pt-BR')} com peso</span>
              <span className="px-2 py-1 rounded bg-amber-950/40 border border-amber-500/30 text-amber-300">{resumo.sem_peso.toLocaleString('pt-BR')} sem peso</span>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-lg overflow-hidden border border-slate-700 text-xs font-semibold">
              <button onClick={() => trocarAba('fila')} className={`px-3 py-1.5 ${aba === 'fila' ? 'bg-blue-600 text-white' : 'bg-slate-900 text-slate-300 hover:bg-slate-800'}`}>
                Fila "sem peso"
              </button>
              <button onClick={() => trocarAba('todos')} className={`px-3 py-1.5 ${aba === 'todos' ? 'bg-blue-600 text-white' : 'bg-slate-900 text-slate-300 hover:bg-slate-800'}`}>
                Todos os itens
              </button>
            </div>
            <div className="relative flex-1 min-w-[200px]">
              <Search className="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={busca}
                onChange={(e) => setBusca(e.target.value)}
                placeholder="Buscar por nome, código ou referência"
                aria-label="Buscar item"
                className="w-full pl-8 pr-2 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-100 text-xs focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          {aba === 'fila' && !buscaAplicada && (
            <p className="text-[11px] text-slate-500">Os itens mais vendidos aparecem primeiro: comece pelo topo da lista.</p>
          )}
          {aviso && (
            <p className="flex items-center gap-1.5 text-[11px] text-emerald-300"><CheckCircle2 className="w-3.5 h-3.5" /> {aviso}</p>
          )}
          {erro && (
            <div className="p-2.5 rounded-lg bg-amber-950/30 border border-amber-500/30 text-[11px] text-amber-300 flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> <span>{erro}</span>
            </div>
          )}

          <div className="space-y-2">
            {itens.map((item) => (
              <LinhaItem key={`${item.id_sku}|${item.peso_kg ?? ''}|${item.confianca ?? ''}|${item.atualizado_em ?? ''}`} item={item} naFila={aba === 'fila'} onSalvar={salvarPeso} onRemover={removerPeso} />
            ))}
            {!carregando && !erro && itens.length === 0 && (
              <p className="py-8 text-center text-sm text-slate-500">
                {aba === 'fila' && !buscaAplicada ? 'Nenhum item sem peso. Tudo certo por aqui.' : 'Nenhum item encontrado.'}
              </p>
            )}
            {carregando && (
              <p className="py-4 flex items-center justify-center gap-2 text-xs text-slate-400">
                <Loader2 className="w-4 h-4 animate-spin" /> Carregando...
              </p>
            )}
            {temMais && !carregando && (
              <button onClick={carregarMais} className="w-full py-2 rounded-lg border border-slate-700 text-xs text-slate-300 hover:bg-slate-800">
                Carregar mais
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
