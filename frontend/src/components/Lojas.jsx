// Administração de lojas: listar, criar, editar e ativar/desativar. Qualquer operador logado edita; o sistema guarda quem
// alterou e quando. Loja não é apagada: é desativada (some do mapa e da escolha do hub, mas continua cadastrada).
// A filial já faz parte do nome da loja (ex.: "Atacadão Guarujá"): não há campo filial.
// As capacidades de peso e de volume são só informativas: nunca bloqueiam nada.
import { useEffect, useState } from 'react';
import { X, Loader2, Save, AlertCircle, CheckCircle2, Store, Plus, Power, Pencil } from 'lucide-react';
import { UFS, FORMULARIO_VAZIO, validarFormularioLoja, corpoDaLoja, formularioDaLoja } from '../services/lojas';

const textoDoErro = (err, padrao) => {
  if (err?.response?.status === 401) return 'Sua sessão expirou. Entre novamente.';
  const detalhe = err?.response?.data?.detail;
  return typeof detalhe === 'string' && detalhe ? detalhe : padrao;
};

const formatarData = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
};

const quemAlterou = (loja) => {
  if (!loja.atualizado_por) return '';
  const autor = loja.atualizado_por.startsWith('carga inicial') ? 'carga inicial' : loja.atualizado_por;
  const quando = formatarData(loja.atualizado_em);
  return `Alterado por ${autor}${quando ? ` em ${quando}` : ''}`;
};

const campo = 'w-full px-2 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm focus:outline-none focus:border-blue-500 placeholder:text-slate-600';

function Erro({ texto }) {
  return texto ? <p className="flex items-center gap-1 text-[11px] text-amber-300 mt-1"><AlertCircle className="w-3 h-3 shrink-0" /> {texto}</p> : null;
}

function Janela({ rotulo, form, turno, aoMudar, erro, desligada }) {
  return (
    <div className={desligada ? 'opacity-40' : ''}>
      <div className="flex items-center gap-2 text-[11px] text-slate-400">
        <span className="w-12">{rotulo}</span>
        <input type="time" disabled={desligada} value={form[`janela_${turno}_inicio`]} onChange={(e) => aoMudar(`janela_${turno}_inicio`, e.target.value)}
          aria-label={`Início da ${rotulo}`} className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-xs" />
        <span>às</span>
        <input type="time" disabled={desligada} value={form[`janela_${turno}_fim`]} onChange={(e) => aoMudar(`janela_${turno}_fim`, e.target.value)}
          aria-label={`Fim da ${rotulo}`} className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-xs" />
      </div>
      <Erro texto={erro} />
    </div>
  );
}

export default function Lojas({ api, onFechar, onMudou }) {
  const [lojas, setLojas] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState('');
  const [aviso, setAviso] = useState('');
  const [editandoId, setEditandoId] = useState(null); // null = criando
  const [form, setForm] = useState({ ...FORMULARIO_VAZIO });
  const [errosForm, setErrosForm] = useState({});
  const [erroServidor, setErroServidor] = useState('');
  const [salvando, setSalvando] = useState(false);

  useEffect(() => {
    let ativo = true;
    api.get('/lojas')
      .then((resp) => { if (ativo) setLojas(resp.data); })
      .catch((err) => { if (ativo) setErro(textoDoErro(err, 'Não foi possível carregar as lojas. Tente de novo.')); })
      .finally(() => { if (ativo) setCarregando(false); });
    return () => { ativo = false; };
  }, [api]);

  const avisar = (texto) => {
    setAviso(texto);
    setTimeout(() => setAviso(''), 3500);
  };

  const mudar = (nome, valor) => setForm((atual) => ({ ...atual, [nome]: valor }));

  const limparFormulario = () => {
    setEditandoId(null);
    setForm({ ...FORMULARIO_VAZIO });
    setErrosForm({});
    setErroServidor('');
  };

  const editar = (loja) => {
    setEditandoId(loja.id);
    setForm(formularioDaLoja(loja));
    setErrosForm({});
    setErroServidor('');
  };

  const gravar = async (dadosDoForm, id) => {
    const corpo = corpoDaLoja(dadosDoForm);
    const { data } = id === null ? await api.post('/lojas', corpo) : await api.put(`/lojas/${id}`, corpo);
    setLojas((atuais) => {
      const semEsta = atuais.filter((l) => l.id !== data.id);
      return [...semEsta, data].sort((a, b) => Number(b.ativo) - Number(a.ativo) || a.nome.localeCompare(b.nome, 'pt-BR'));
    });
    onMudou?.();
    return data;
  };

  const salvar = async (e) => {
    e.preventDefault();
    const conferencia = validarFormularioLoja(form);
    setErrosForm(conferencia.erros);
    setErroServidor('');
    if (!conferencia.ok) return;
    setSalvando(true);
    try {
      const data = await gravar(form, editandoId);
      avisar(editandoId === null ? `${data.nome} cadastrada.` : `Dados de ${data.nome} salvos.`);
      limparFormulario();
    } catch (err) {
      setErroServidor(textoDoErro(err, 'Não foi possível salvar. Tente de novo.'));
    } finally {
      setSalvando(false);
    }
  };

  const alternarAtiva = async (loja) => {
    if (loja.ativo && !window.confirm(`Desativar ${loja.nome}? Ela some do mapa e da escolha da loja, mas continua cadastrada e pode ser reativada.`)) return;
    try {
      const data = await gravar({ ...formularioDaLoja(loja), ativo: !loja.ativo }, loja.id);
      avisar(data.ativo ? `${data.nome} reativada.` : `${data.nome} desativada.`);
    } catch (err) {
      setErro(textoDoErro(err, 'Não foi possível salvar. Tente de novo.'));
    }
  };

  const ativas = lojas.filter((l) => l.ativo);
  const inativas = lojas.filter((l) => !l.ativo);

  const renderLinha = (loja) => (
    <div key={`${loja.id}|${loja.atualizado_em ?? ''}`} className={`p-3 rounded-lg border flex flex-wrap items-center gap-2 justify-between ${loja.ativo ? 'bg-slate-900/70 border-slate-800' : 'bg-slate-950/60 border-slate-800/60 opacity-75'}`}>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-100 truncate">{loja.nome}{loja.uf ? ` - ${loja.uf}` : ''}</p>
        {(loja.nome_operacao || loja.codigo_externo) && (
          <p className="text-[11px] text-blue-300 truncate">
            {loja.nome_operacao ? `Operação: ${loja.nome_operacao}` : ''}{loja.nome_operacao && loja.codigo_externo ? ' · ' : ''}{loja.codigo_externo ? `Código: ${loja.codigo_externo}` : ''}
          </p>
        )}
        {loja.cidade && <p className="text-[11px] text-slate-300 truncate">{loja.cidade}</p>}
        {loja.endereco && <p className="text-[11px] text-slate-400 truncate">{loja.endereco}</p>}
        <p className="text-[10px] text-slate-500 font-mono">{loja.lat.toLocaleString('pt-BR', { maximumFractionDigits: 6 })}, {loja.lng.toLocaleString('pt-BR', { maximumFractionDigits: 6 })}</p>
        {quemAlterou(loja) && <p className="text-[10px] text-slate-500">{quemAlterou(loja)}</p>}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button onClick={() => editar(loja)} className="flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold border border-slate-700 text-slate-300 hover:text-white hover:bg-slate-800">
          <Pencil className="w-3 h-3" /> Editar
        </button>
        <button onClick={() => alternarAtiva(loja)}
          className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold border ${loja.ativo ? 'text-slate-300 border-slate-700 hover:text-amber-300 hover:border-amber-500/40' : 'text-emerald-300 border-emerald-500/30 hover:bg-emerald-950/30'}`}>
          <Power className="w-3 h-3" /> {loja.ativo ? 'Desativar' : 'Reativar'}
        </button>
      </div>
    </div>
  );

  return (
    <div className="fixed inset-0 z-[100] bg-slate-950/80 backdrop-blur-sm flex items-start justify-center p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-label="Lojas">
      <div className="w-full max-w-3xl my-6 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Store className="w-5 h-5 text-blue-400" />
            <h2 className="text-base font-bold text-white">Lojas</h2>
          </div>
          <button onClick={onFechar} className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white" aria-label="Fechar">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-5">
          <p className="text-[11px] text-slate-400 leading-snug">
            As lojas ativas aparecem no mapa; clicar numa loja a escolhe como ponto de partida. O nome já traz a filial (ex.: "Atacadão Guarujá").
            A loja não é apagada: ela é desativada. As capacidades são opcionais e só informativas: o sistema nunca bloqueia nem avisa por causa delas.
            Qualquer operador pode editar; fica registrado quem alterou e quando.
          </p>
          {aviso && <p className="flex items-center gap-1.5 text-[11px] text-emerald-300"><CheckCircle2 className="w-3.5 h-3.5" /> {aviso}</p>}
          {erro && (
            <div className="p-2.5 rounded-lg bg-amber-950/30 border border-amber-500/30 text-[11px] text-amber-300 flex items-start gap-2">
              <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" /> <span>{erro}</span>
            </div>
          )}

          <form onSubmit={salvar} className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-3" noValidate>
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
              {editandoId === null ? <><Plus className="w-3.5 h-3.5 text-blue-400" /> Nova loja</> : <><Pencil className="w-3.5 h-3.5 text-blue-400" /> Editando a loja</>}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-[1fr_90px] gap-2">
              <label className="text-[11px] text-slate-400">Nome (com a filial)
                <input type="text" value={form.nome} maxLength={120} onChange={(e) => mudar('nome', e.target.value)} placeholder="ex.: Atacadão Guarujá" className={campo} />
                <Erro texto={errosForm.nome} />
              </label>
              <label className="text-[11px] text-slate-400">Estado
                <select value={form.uf} onChange={(e) => mudar('uf', e.target.value)} className={campo}>
                  <option value="">--</option>
                  {UFS.map((uf) => <option key={uf} value={uf}>{uf}</option>)}
                </select>
                <Erro texto={errosForm.uf} />
              </label>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <label className="text-[11px] text-slate-400">Nome de operação (opcional, único; ex.: "SDA Mooca")
                <input type="text" value={form.nome_operacao} maxLength={120} onChange={(e) => mudar('nome_operacao', e.target.value)} placeholder="ex.: SDA Mooca" className={campo} />
                <Erro texto={errosForm.nome_operacao} />
              </label>
              <label className="text-[11px] text-slate-400">Código externo (opcional, único)
                <input type="text" value={form.codigo_externo} maxLength={40} onChange={(e) => mudar('codigo_externo', e.target.value)} className={campo} />
                <Erro texto={errosForm.codigo_externo} />
              </label>
            </div>
            <label className="block text-[11px] text-slate-400">Endereço (opcional)
              <input type="text" value={form.endereco} maxLength={250} onChange={(e) => mudar('endereco', e.target.value)} placeholder="ex.: Av. Santos Dumont, 100" className={campo} />
            </label>
            <label className="block text-[11px] text-slate-400">Cidade (opcional; com o Estado, dá o código IBGE do ponto de partida)
              <input type="text" value={form.cidade} maxLength={120} onChange={(e) => mudar('cidade', e.target.value)} placeholder="ex.: Guarujá" className={campo} />
              <Erro texto={errosForm.cidade} />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-[11px] text-slate-400">Latitude
                <input type="text" inputMode="decimal" value={form.lat} onChange={(e) => mudar('lat', e.target.value)} placeholder="-23,5614" className={campo} />
                <Erro texto={errosForm.lat} />
              </label>
              <label className="text-[11px] text-slate-400">Longitude
                <input type="text" inputMode="decimal" value={form.lng} onChange={(e) => mudar('lng', e.target.value)} placeholder="-46,6333" className={campo} />
                <Erro texto={errosForm.lng} />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-[11px] text-slate-400">Capacidade de peso (opcional, só informativa)
                <input type="text" inputMode="decimal" value={form.capacidade_peso} onChange={(e) => mudar('capacidade_peso', e.target.value)} className={campo} />
                <Erro texto={errosForm.capacidade_peso} />
              </label>
              <label className="text-[11px] text-slate-400">Capacidade de volume (opcional, só informativa)
                <input type="text" inputMode="decimal" value={form.capacidade_volume} onChange={(e) => mudar('capacidade_volume', e.target.value)} className={campo} />
                <Erro texto={errosForm.capacidade_volume} />
              </label>
            </div>
            <div className="space-y-1.5">
              <p className="text-[11px] text-slate-400">Janelas de entrega</p>
              <Janela rotulo="Manhã" turno="manha" form={form} aoMudar={mudar} erro={errosForm.janela_manha} />
              <Janela rotulo="Tarde" turno="tarde" form={form} aoMudar={mudar} erro={errosForm.janela_tarde} />
              <Janela rotulo="Noite" turno="noite" form={form} aoMudar={mudar} erro={errosForm.janela_noite} desligada={!form.usa_noite} />
              <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
                <input type="checkbox" checked={form.usa_noite} onChange={(e) => mudar('usa_noite', e.target.checked)} className="accent-blue-500" /> Esta loja usa o turno da noite
              </label>
            </div>
            <Erro texto={erroServidor} />
            <div className="flex items-center gap-2">
              <button type="submit" disabled={salvando} className="flex items-center gap-1 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs font-semibold transition-colors">
                {salvando ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} {editandoId === null ? 'Cadastrar' : 'Salvar'}
              </button>
              {editandoId !== null && (
                <button type="button" onClick={limparFormulario} className="px-3 py-1.5 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 text-xs">Cancelar edição</button>
              )}
            </div>
          </form>

          {carregando && <p className="py-4 flex items-center justify-center gap-2 text-xs text-slate-400"><Loader2 className="w-4 h-4 animate-spin" /> Carregando...</p>}
          {!carregando && !erro && (
            <section className="space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Lojas ativas ({ativas.length})</h3>
              {ativas.length === 0 && <p className="py-3 text-center text-sm text-slate-500">Nenhuma loja ativa. Cadastre uma acima ou carregue a lista pelo administrador do sistema.</p>}
              {ativas.map(renderLinha)}
              {inativas.length > 0 && (
                <>
                  <h4 className="pt-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Desativadas ({inativas.length})</h4>
                  {inativas.map(renderLinha)}
                </>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
