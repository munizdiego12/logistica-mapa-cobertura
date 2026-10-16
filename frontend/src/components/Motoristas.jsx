// Cadastro de motoristas e tipos de veículo (diária base e peso de referência).
// Qualquer operador logado edita; o sistema guarda quem alterou e quando. Motorista não é apagado: é desativado.
// O peso de referência é só um guia para o montador de rotas: não é limite e nunca bloqueia nem avisa nada.
// Etapa 6b: código único, lojas do motorista, telefone (mascarado na lista; o número completo só aparece ao editar),
// "Diária do motorista" opcional, busca, filtros e paginação (feitos aqui mesmo: os ~500 motoristas vêm numa resposta só).
import { useEffect, useMemo, useState } from 'react';
import {
  X, Loader2, Save, AlertCircle, CheckCircle2, Users, Truck, Plus, Power, Pencil, Search, ChevronLeft, ChevronRight, Trash2,
} from 'lucide-react';
import ComboboxMultiplo from './ComboboxMultiplo';
import { filtrarLojas, cidadeEUf } from '../services/lojas';
import {
  validarTelefone, formatarTelefone, filtrarMotoristasDaTela, paginar, resumoDasLojas, LIMITE_DA_LISTA, POR_PAGINA,
} from '../services/motoristas';
import { rotuloDoTipo, validarValorRota } from '../services/valorRota';

const formatarNumero = (n, max = 3) =>
  n === null || n === undefined ? '' : Number(n).toLocaleString('pt-BR', { maximumFractionDigits: max });

const formatarData = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
};

const textoDoErro = (err, padrao) => {
  if (err?.response?.status === 401) return 'Sua sessão expirou. Entre novamente.';
  const detalhe = err?.response?.data?.detail;
  return typeof detalhe === 'string' && detalhe ? detalhe : padrao;
};

const quemAlterou = (item) => {
  if (!item.atualizado_por) return '';
  const autor = item.atualizado_por.startsWith('cadastro inicial') ? 'cadastro inicial' : item.atualizado_por;
  const quando = formatarData(item.atualizado_em);
  return `Alterado por ${autor}${quando ? ` em ${quando}` : ''}`;
};

const EH_NUMERO = /^\d+([.,]\d+)?$/;

function LinhaTipo({ tipo, onSalvar }) {
  const [custo, setCusto] = useState(formatarNumero(tipo.custo_rota, 2));
  const [peso, setPeso] = useState(formatarNumero(tipo.peso_referencia_kg));
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState('');

  const mudou = custo.trim() !== formatarNumero(tipo.custo_rota, 2) || peso.trim() !== formatarNumero(tipo.peso_referencia_kg);

  const salvar = async () => {
    if (!EH_NUMERO.test(custo.trim())) {
      setErro('Digite o valor da diária em reais, por exemplo 260 ou 260,50.');
      return;
    }
    if (peso.trim() !== '' && (!EH_NUMERO.test(peso.trim()) || Number(peso.trim().replace(',', '.')) <= 0)) {
      setErro('O peso de referência precisa ser maior que zero (ou deixe em branco para "sem referência").');
      return;
    }
    setErro('');
    setSalvando(true);
    const mensagem = await onSalvar(tipo, custo.trim(), peso.trim());
    setSalvando(false);
    if (mensagem) setErro(mensagem);
  };

  return (
    <div className="p-3 rounded-lg bg-slate-900/70 border border-slate-800 space-y-2">
      <p className="text-sm font-semibold text-slate-100">{tipo.nome}</p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-[11px] text-slate-400 space-y-1">
          <span className="block">Diária base (R$)</span>
          <input
            type="text"
            inputMode="decimal"
            value={custo}
            onChange={(e) => setCusto(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && mudou) salvar(); }}
            aria-label={`Diária base de ${tipo.nome}`}
            className="w-28 px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm font-mono focus:outline-none focus:border-blue-500"
          />
          <span className="block text-[10px] text-slate-500">Valor da diária do motorista</span>
        </label>
        <label className="text-[11px] text-slate-400 space-y-1">
          <span className="block">Peso de referência (kg)</span>
          <input
            type="text"
            inputMode="decimal"
            value={peso}
            onChange={(e) => setPeso(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && mudou) salvar(); }}
            placeholder="sem referência"
            aria-label={`Peso de referência de ${tipo.nome}`}
            className="w-36 px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm font-mono placeholder:text-slate-600 focus:outline-none focus:border-blue-500"
          />
        </label>
        <button
          onClick={salvar}
          disabled={salvando || !mudou}
          className="flex items-center gap-1 px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold transition-colors"
        >
          {salvando ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} Salvar
        </button>
      </div>
      {erro && <p className="flex items-center gap-1 text-[11px] text-amber-300"><AlertCircle className="w-3 h-3" /> {erro}</p>}
      {quemAlterou(tipo) && <p className="text-[10px] text-slate-500">{quemAlterou(tipo)}</p>}
    </div>
  );
}

const campo = 'w-full px-2 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm placeholder:text-slate-600 focus:outline-none focus:border-blue-500';
const selecionar = 'px-2 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-200 text-xs';

const diariaEmTexto = (valor) => (valor === null || valor === undefined ? '' : formatarNumero(valor, 2));

// Formulário de cadastro (modo "novo") e de edição. O telefone completo só existe aqui: vem de GET /motoristas/{id}.
function FormularioMotorista({ api, motorista, tipos, lojas, onSalvar, onCancelar }) {
  const novo = motorista === null;
  const [codigo, setCodigo] = useState(motorista?.codigo ?? '');
  const [nome, setNome] = useState(motorista?.nome ?? '');
  const [tipoVeiculo, setTipoVeiculo] = useState(motorista?.tipo_veiculo ?? tipos[0]?.nome ?? '');
  const [lojasIds, setLojasIds] = useState((motorista?.lojas ?? []).map((l) => l.id));
  const [buscaLojas, setBuscaLojas] = useState('');
  const [telefone, setTelefone] = useState('');
  const [telefoneCarregado, setTelefoneCarregado] = useState(novo);
  const [diaria, setDiaria] = useState(diariaEmTexto(motorista?.valor_rota));
  const [ativo, setAtivo] = useState(motorista?.ativo ?? true);
  const [salvando, setSalvando] = useState(false);
  const [erros, setErros] = useState([]);

  useEffect(() => {
    let vivo = true;
    if (novo) {
      api.get('/motoristas/proximo-codigo')
        .then(({ data }) => { if (vivo) setCodigo((atual) => atual || data.codigo || ''); })
        .catch(() => {}); // sem sugestão: o operador digita o código
    } else {
      api.get(`/motoristas/${motorista.id}`)
        .then(({ data }) => { if (vivo) { setTelefone(formatarTelefone(data.telefone)); setTelefoneCarregado(true); } })
        .catch(() => { if (vivo) setErros(['Não foi possível carregar o telefone deste motorista. Ele não será alterado ao salvar.']); });
    }
    return () => { vivo = false; };
  }, [api, novo, motorista?.id]);

  const nomePorId = useMemo(() => {
    const mapa = new Map((lojas ?? []).map((l) => [l.id, l]));
    for (const l of motorista?.lojas ?? []) if (!mapa.has(l.id)) mapa.set(l.id, l);
    return mapa;
  }, [lojas, motorista]);

  const rotuloLoja = (l) => `${l.nome}${l.ativo === false ? ' (desativada)' : ''}`;
  // Opções: lojas ativas e as desativadas que o motorista já tem (para poder tirar). A lista é limitada.
  const opcoesDeLojas = useMemo(() => {
    const permitidas = (lojas ?? []).filter((l) => l.ativo !== false || lojasIds.includes(l.id));
    const achadas = filtrarLojas(permitidas, buscaLojas).map((r) => r.loja);
    return { itens: achadas.slice(0, LIMITE_DA_LISTA).map((l) => ({ id: l.id, rotulo: rotuloLoja(l), detalhe: cidadeEUf(l) })), total: achadas.length };
  }, [lojas, buscaLojas, lojasIds]);
  const chipsDeLojas = lojasIds.map((id) => ({ id, rotulo: nomePorId.has(id) ? rotuloLoja(nomePorId.get(id)) : `Loja ${id}` }));

  const alternarLoja = (id) => setLojasIds((atuais) => (atuais.includes(id) ? atuais.filter((x) => x !== id) : [...atuais, id]));

  const salvar = async (e) => {
    e.preventDefault();
    const problemas = [];
    if (nome.trim() === '') problemas.push('Informe o nome do motorista.');
    if (codigo.trim() === '' && (novo || motorista.codigo)) problemas.push('Informe o código do motorista, por exemplo MOT-0001.');
    const fone = validarTelefone(telefone);
    if (telefoneCarregado && !fone.ok) problemas.push(fone.mensagem);
    if (!validarValorRota(diaria).ok) problemas.push('A diária do motorista precisa ser um valor em reais, por exemplo 130 ou 130,50 (ou deixe em branco).');
    if (problemas.length > 0) { setErros(problemas); return; }
    setErros([]);
    setSalvando(true);
    const corpo = {
      nome: nome.trim(), tipo_veiculo: tipoVeiculo, ativo, valor_rota: diaria.trim(), lojas: lojasIds,
      ...(codigo.trim() !== '' ? { codigo: codigo.trim() } : {}),
      ...(telefoneCarregado ? { telefone: telefone.trim() } : {}), // não carregou o telefone: não mexe nele
    };
    const mensagem = await onSalvar(motorista, corpo);
    setSalvando(false);
    if (mensagem) setErros([mensagem]);
  };

  return (
    <form onSubmit={salvar} className="p-4 rounded-lg bg-slate-950/70 border border-blue-500/30 space-y-3" aria-label={novo ? 'Cadastrar motorista' : `Editar ${motorista.nome}`}>
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-bold uppercase tracking-wider text-blue-300">{novo ? 'Novo motorista' : `Editar ${motorista.nome}`}</h4>
        <button type="button" onClick={onCancelar} className="text-[11px] text-slate-400 hover:text-white">Cancelar</button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-[11px] text-slate-400 space-y-1">
          <span className="block">Código (único)</span>
          <input type="text" value={codigo} maxLength={40} onChange={(e) => setCodigo(e.target.value)} placeholder="MOT-0001" aria-label="Código do motorista" className={`${campo} font-mono`} />
          {novo && <span className="block text-[10px] text-slate-500">Sugerido: o próximo livre. Você pode trocar.</span>}
        </label>
        <label className="text-[11px] text-slate-400 space-y-1">
          <span className="block">Nome</span>
          <input type="text" value={nome} maxLength={120} onChange={(e) => setNome(e.target.value)} placeholder="Nome do motorista" aria-label="Nome do motorista" className={campo} />
        </label>
        <label className="text-[11px] text-slate-400 space-y-1">
          <span className="block">Tipo de veículo</span>
          <select value={tipoVeiculo} onChange={(e) => setTipoVeiculo(e.target.value)} aria-label="Tipo de veículo do motorista" className={`${selecionar} w-full`}>
            {tipos.map((t) => <option key={t.id} value={t.nome}>{t.nome}</option>)}
          </select>
        </label>
        <label className="text-[11px] text-slate-400 space-y-1">
          <span className="block">Diária do motorista (opcional)</span>
          <input type="text" inputMode="decimal" value={diaria} onChange={(e) => setDiaria(e.target.value)} placeholder="usa a diária base" aria-label="Diária do motorista" className={`${campo} font-mono`} />
          <span className="block text-[10px] text-slate-500">Em branco usa a diária base do tipo.</span>
        </label>
        <label className="text-[11px] text-slate-400 space-y-1 sm:col-span-2">
          <span className="block">Telefone (opcional, com DDD)</span>
          <span className="flex items-center gap-2">
            <input
              type="tel"
              value={telefone}
              onChange={(e) => setTelefone(e.target.value)}
              disabled={!telefoneCarregado}
              placeholder={telefoneCarregado ? '(11) 98765-4321' : 'carregando...'}
              aria-label="Telefone do motorista"
              autoComplete="off"
              className={`${campo} max-w-xs font-mono disabled:opacity-50`}
            />
            {telefone.trim() !== '' && (
              <button type="button" onClick={() => setTelefone('')} className="flex items-center gap-1 text-[11px] text-amber-300 hover:text-amber-200">
                <Trash2 className="w-3 h-3" /> Apagar telefone
              </button>
            )}
          </span>
          <span className="block text-[10px] text-slate-500">Dado pessoal: aparece mascarado nas listas. Se o motorista pedir a remoção dos dados, desative-o e apague o telefone.</span>
        </label>
      </div>

      <div className="space-y-1">
        <span className="block text-[11px] text-slate-400">Lojas do motorista</span>
        <ComboboxMultiplo
          rotulo="Lojas do motorista"
          placeholder="Pesquise a loja (nome, cidade ou UF)"
          grupos={[{ chave: 'lojas', titulo: '', itens: opcoesDeLojas.itens }]}
          selecionados={lojasIds}
          chips={chipsDeLojas}
          busca={buscaLojas}
          onBusca={setBuscaLojas}
          onAlternar={alternarLoja}
          onRemover={alternarLoja}
          aviso={opcoesDeLojas.total > opcoesDeLojas.itens.length ? `Mostrando ${opcoesDeLojas.itens.length} de ${opcoesDeLojas.total}. Digite para refinar.` : ''}
          textoVazio="Nenhuma loja encontrada"
        />
        {lojasIds.length === 0 && <p className="text-[10px] text-slate-500">Sem lojas marcadas, o motorista aparece só em "Outros motoristas" na roteirização.</p>}
      </div>

      {!novo && (
        <label className="flex items-center gap-2 text-[11px] text-slate-300">
          <input type="checkbox" checked={ativo} onChange={(e) => setAtivo(e.target.checked)} className="accent-blue-500" />
          Ativo (motorista desativado não entra nas rotas, mas continua cadastrado)
        </label>
      )}

      {erros.length > 0 && (
        <ul className="space-y-0.5">
          {erros.map((texto) => <li key={texto} className="flex items-start gap-1 text-[11px] text-amber-300"><AlertCircle className="w-3 h-3 mt-0.5 shrink-0" /> {texto}</li>)}
        </ul>
      )}

      <div className="flex items-center gap-2">
        <button type="submit" disabled={salvando} className="flex items-center gap-1 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs font-semibold transition-colors">
          {salvando ? <Loader2 className="w-3 h-3 animate-spin" /> : novo ? <Plus className="w-3 h-3" /> : <Save className="w-3 h-3" />} {novo ? 'Cadastrar' : 'Salvar'}
        </button>
        {!novo && quemAlterou(motorista) && <span className="text-[10px] text-slate-500">{quemAlterou(motorista)}</span>}
      </div>
    </form>
  );
}

function LinhaMotorista({ motorista, onEditar, onAlternarAtivo, ocupado }) {
  const mascara = motorista.telefone_mascarado || ''; // a lista só recebe o telefone mascarado
  return (
    <div className={`p-2.5 rounded-lg border flex flex-wrap items-center gap-x-3 gap-y-1 ${motorista.ativo ? 'bg-slate-900/70 border-slate-800' : 'bg-slate-950/60 border-slate-800/60 opacity-75'}`}>
      <span className="w-24 shrink-0 font-mono text-[11px] text-slate-400">{motorista.codigo || 'sem código'}</span>
      <div className="flex-1 min-w-[180px]">
        <p className="text-sm text-slate-100 leading-snug">{motorista.nome} {!motorista.ativo && <span className="ml-1 text-[10px] uppercase tracking-wider text-slate-500">Desativado</span>}</p>
        <p className="text-[10px] text-slate-500 leading-snug">
          {rotuloDoTipo(motorista.tipo_veiculo)}
          {motorista.lojas?.length > 0 && <> · {resumoDasLojas(motorista.lojas)}</>}
          {mascara && <> · {mascara}</>}
          {motorista.valor_rota !== null && motorista.valor_rota !== undefined && <> · diária R$ {formatarNumero(motorista.valor_rota, 2)}</>}
        </p>
      </div>
      <button
        type="button"
        onClick={() => onEditar(motorista)}
        aria-label={`Editar ${motorista.nome}`}
        className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold border text-blue-300 border-blue-500/30 hover:bg-blue-950/30"
      >
        <Pencil className="w-3 h-3" /> Editar
      </button>
      <button
        type="button"
        onClick={() => onAlternarAtivo(motorista)}
        disabled={ocupado}
        aria-label={`${motorista.ativo ? 'Desativar' : 'Reativar'} ${motorista.nome}`}
        className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold border disabled:opacity-40 ${
          motorista.ativo
            ? 'text-slate-300 border-slate-700 hover:text-amber-300 hover:border-amber-500/40'
            : 'text-emerald-300 border-emerald-500/30 hover:bg-emerald-950/30'
        }`}
      >
        <Power className="w-3 h-3" /> {motorista.ativo ? 'Desativar' : 'Reativar'}
      </button>
    </div>
  );
}

export default function Motoristas({ api, onFechar, onMudou }) {
  const [tipos, setTipos] = useState([]);
  const [motoristas, setMotoristas] = useState([]);
  const [lojas, setLojas] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState('');
  const [aviso, setAviso] = useState('');
  const [formulario, setFormulario] = useState(undefined); // undefined = fechado | null = novo | motorista = edição
  const [ocupado, setOcupado] = useState(false);
  const [busca, setBusca] = useState('');
  const [filtroTipo, setFiltroTipo] = useState('');
  const [filtroLoja, setFiltroLoja] = useState('');
  const [situacao, setSituacao] = useState('todos');
  const [pagina, setPagina] = useState(1);

  useEffect(() => {
    let ativo = true;
    Promise.all([api.get('/tipos-veiculo'), api.get('/motoristas'), api.get('/lojas').catch(() => ({ data: [] }))])
      .then(([respTipos, respMotoristas, respLojas]) => {
        if (!ativo) return;
        setTipos(respTipos.data);
        setMotoristas(respMotoristas.data);
        setLojas(respLojas.data);
      })
      .catch((err) => { if (ativo) setErro(textoDoErro(err, 'Não foi possível carregar o cadastro. Tente de novo.')); })
      .finally(() => { if (ativo) setCarregando(false); });
    return () => { ativo = false; };
  }, [api]);

  const avisar = (texto) => {
    setAviso(texto);
    setTimeout(() => setAviso(''), 3500);
  };

  // Devolvem '' quando deu certo ou o texto do erro (mostrado no próprio formulário/linha).
  const salvarTipo = async (tipo, custo, peso) => {
    try {
      const { data } = await api.put(`/tipos-veiculo/${tipo.id}`, { custo_rota: custo, peso_referencia_kg: peso === '' ? null : peso });
      setTipos((atuais) => atuais.map((t) => (t.id === tipo.id ? data : t)));
      onMudou?.();
      avisar(`Dados de "${tipo.nome}" salvos.`);
      return '';
    } catch (err) {
      return textoDoErro(err, 'Não foi possível salvar. Tente de novo.');
    }
  };

  const salvarMotorista = async (motorista, corpo) => {
    try {
      const { data } = motorista === null ? await api.post('/motoristas', corpo) : await api.put(`/motoristas/${motorista.id}`, corpo);
      setMotoristas((atuais) => (motorista === null ? [...atuais, data] : atuais.map((m) => (m.id === data.id ? data : m))));
      setFormulario(undefined);
      onMudou?.();
      avisar(motorista === null ? `${data.nome} cadastrado.` : `Dados de ${data.nome} salvos.`);
      return '';
    } catch (err) {
      return textoDoErro(err, 'Não foi possível salvar. Tente de novo.');
    }
  };

  const alternarAtivo = async (motorista) => {
    if (motorista.ativo && !window.confirm(`Desativar ${motorista.nome}? Ele deixa de entrar nas rotas, mas continua cadastrado e pode ser reativado.`)) return;
    setOcupado(true);
    try {
      // Só nome, tipo e situação: código, telefone, diária e lojas não vão no pedido, então ficam como estão.
      const { data } = await api.put(`/motoristas/${motorista.id}`, { nome: motorista.nome, tipo_veiculo: motorista.tipo_veiculo, ativo: !motorista.ativo });
      setMotoristas((atuais) => atuais.map((m) => (m.id === data.id ? data : m)));
      onMudou?.();
      avisar(data.ativo ? `${data.nome} reativado.` : `${data.nome} desativado.`);
    } catch (err) {
      setErro(textoDoErro(err, 'Não foi possível salvar. Tente de novo.'));
    } finally {
      setOcupado(false);
    }
  };

  const filtrados = useMemo(
    () => filtrarMotoristasDaTela(motoristas, { busca, tipo: filtroTipo, lojaId: filtroLoja, situacao }),
    [motoristas, busca, filtroTipo, filtroLoja, situacao],
  );
  const pag = paginar(filtrados, pagina, POR_PAGINA);
  const ativosTotal = motoristas.filter((m) => m.ativo).length;
  const mudarFiltro = (definir) => (e) => { definir(e.target.value); setPagina(1); };

  return (
    <div className="fixed inset-0 z-[100] bg-slate-950/80 backdrop-blur-sm flex items-start justify-center p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-label="Motoristas e veículos">
      <div className="w-full max-w-4xl my-6 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-blue-400" />
            <h2 className="text-base font-bold text-white">Motoristas e veículos</h2>
          </div>
          <button onClick={onFechar} className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white" aria-label="Fechar">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-5">
          <p className="text-[11px] text-slate-400 leading-snug">
            Só os motoristas ativos aparecem na escolha da roteirização (lá você marca quem entra nas rotas). Qualquer operador pode editar; fica registrado quem alterou e quando.
            A diária base é o valor da diária do motorista, definido por tipo de veículo; cada motorista pode ter uma diária própria (por enquanto só cadastro: o pagamento ainda não é calculado).
            O peso de referência é opcional e é só um guia para montar as rotas: não é um limite e o sistema nunca bloqueia nem avisa por causa dele.
          </p>

          {aviso && <p className="flex items-center gap-1.5 text-[11px] text-emerald-300"><CheckCircle2 className="w-3.5 h-3.5" /> {aviso}</p>}
          {erro && (
            <div className="p-2.5 rounded-lg bg-amber-950/30 border border-amber-500/30 text-[11px] text-amber-300 flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> <span>{erro}</span>
            </div>
          )}
          {carregando && (
            <p className="py-4 flex items-center justify-center gap-2 text-xs text-slate-400"><Loader2 className="w-4 h-4 animate-spin" /> Carregando...</p>
          )}

          {!carregando && tipos.length > 0 && (
            <>
              <section className="space-y-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                  <Truck className="w-3.5 h-3.5 text-blue-400" /> Tipos de veículo
                </h3>
                {tipos.map((t) => (
                  <LinhaTipo key={`${t.id}|${t.custo_rota}|${t.peso_referencia_kg ?? ''}|${t.atualizado_em ?? ''}`} tipo={t} onSalvar={salvarTipo} />
                ))}
              </section>

              <section className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                    <Users className="w-3.5 h-3.5 text-blue-400" /> Motoristas ({ativosTotal} ativos de {motoristas.length})
                  </h3>
                  {formulario === undefined && (
                    <button type="button" onClick={() => setFormulario(null)} className="flex items-center gap-1 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold transition-colors">
                      <Plus className="w-3 h-3" /> Novo motorista
                    </button>
                  )}
                </div>

                {formulario !== undefined && (
                  <FormularioMotorista
                    key={formulario === null ? 'novo' : formulario.id}
                    api={api}
                    motorista={formulario}
                    tipos={tipos}
                    lojas={lojas}
                    onSalvar={salvarMotorista}
                    onCancelar={() => setFormulario(undefined)}
                  />
                )}

                <div className="grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]">
                  <label className="relative block">
                    <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" aria-hidden="true" />
                    <input
                      type="search"
                      value={busca}
                      onChange={mudarFiltro(setBusca)}
                      placeholder="Pesquise por nome ou código"
                      aria-label="Pesquisar motorista por nome ou código"
                      className="w-full text-xs bg-slate-950 border border-slate-700 focus:border-blue-500 rounded pl-8 pr-2 py-2 text-slate-100 placeholder:text-slate-500 focus:outline-none"
                    />
                  </label>
                  <select value={filtroTipo} onChange={mudarFiltro(setFiltroTipo)} aria-label="Filtrar por tipo de veículo" className={selecionar}>
                    <option value="">Todos os tipos</option>
                    {tipos.map((t) => <option key={t.id} value={t.nome}>{t.nome}</option>)}
                  </select>
                  <select value={filtroLoja} onChange={mudarFiltro(setFiltroLoja)} aria-label="Filtrar por loja" className={`${selecionar} max-w-[220px]`}>
                    <option value="">Todas as lojas</option>
                    {lojas.map((l) => <option key={l.id} value={l.id}>{l.nome}{l.ativo === false ? ' (desativada)' : ''}</option>)}
                  </select>
                  <select value={situacao} onChange={mudarFiltro(setSituacao)} aria-label="Filtrar por situação" className={selecionar}>
                    <option value="todos">Ativos e desativados</option>
                    <option value="ativos">Só ativos</option>
                    <option value="desativados">Só desativados</option>
                  </select>
                </div>

                {motoristas.length === 0 && (
                  <p className="py-3 text-center text-sm text-slate-500">Nenhum motorista cadastrado. Use "Novo motorista" para poder gerar rotas.</p>
                )}
                {motoristas.length > 0 && pag.total === 0 && (
                  <p className="py-3 text-center text-sm text-slate-500">Nenhum motorista encontrado com esses filtros.</p>
                )}
                {pag.itens.map((m) => (
                  <LinhaMotorista key={m.id} motorista={m} onEditar={setFormulario} onAlternarAtivo={alternarAtivo} ocupado={ocupado} />
                ))}

                {pag.total > 0 && (
                  <div className="flex items-center justify-between pt-1 text-[11px] text-slate-400">
                    <span>Mostrando {pag.de} a {pag.ate} de {pag.total}</span>
                    <span className="flex items-center gap-2">
                      <button type="button" onClick={() => setPagina(pag.pagina - 1)} disabled={pag.pagina <= 1} aria-label="Página anterior" className="p-1 rounded border border-slate-700 hover:bg-slate-800 disabled:opacity-40">
                        <ChevronLeft className="w-3.5 h-3.5" />
                      </button>
                      <span>Página {pag.pagina} de {pag.totalPaginas}</span>
                      <button type="button" onClick={() => setPagina(pag.pagina + 1)} disabled={pag.pagina >= pag.totalPaginas} aria-label="Próxima página" className="p-1 rounded border border-slate-700 hover:bg-slate-800 disabled:opacity-40">
                        <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </span>
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
