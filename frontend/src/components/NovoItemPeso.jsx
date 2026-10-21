// Formulário "Novo item" da tela "Pesos dos itens": cria UM item. Código e nome obrigatórios; peso (opcional, vírgula decimal, até 1000 kg),
// referência, fonte e confiança (padrão média) opcionais. Sem peso, o item entra na fila "sem peso". O peso é só informativo.
import { useState } from 'react';
import { Loader2, Save, AlertCircle, X } from 'lucide-react';
import { CONFIANCAS, FORMULARIO_NOVO_ITEM, validarNovoItem, corpoNovoItem } from '../services/itensPesos';

const campo = 'w-full px-2 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm focus:outline-none focus:border-blue-500 placeholder:text-slate-600';

function Erro({ texto }) {
  return texto ? <p className="flex items-center gap-1 text-[11px] text-amber-300 mt-1"><AlertCircle className="w-3 h-3 shrink-0" /> {texto}</p> : null;
}

export default function NovoItemPeso({ api, onCriado, onFechar, tratarErro }) {
  const [form, setForm] = useState({ ...FORMULARIO_NOVO_ITEM });
  const [erros, setErros] = useState({});
  const [erroServidor, setErroServidor] = useState('');
  const [salvando, setSalvando] = useState(false);

  const mudar = (nome) => (e) => setForm((atual) => ({ ...atual, [nome]: e.target.value }));

  const salvar = async (e) => {
    e.preventDefault();
    const conferencia = validarNovoItem(form);
    setErros(conferencia.erros);
    setErroServidor('');
    if (!conferencia.ok) return;
    setSalvando(true);
    try {
      const { data } = await api.post('/item-pesos', corpoNovoItem(form));
      onCriado(data);
    } catch (err) {
      setErroServidor(tratarErro(err, 'Não foi possível criar o item. Tente de novo.'));
    } finally {
      setSalvando(false);
    }
  };

  return (
    <form onSubmit={salvar} noValidate className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-3" aria-label="Novo item">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">Novo item</h3>
        <button type="button" onClick={onFechar} className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-white" aria-label="Fechar o formulário">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <label className="text-[11px] text-slate-400">Código do item (obrigatório)
          <input value={form.id_sku} maxLength={40} onChange={mudar('id_sku')} className={campo} placeholder="ex.: 27439" />
          <Erro texto={erros.id_sku} />
        </label>
        <label className="text-[11px] text-slate-400">Código de referência (opcional)
          <input value={form.reference_code} maxLength={60} onChange={mudar('reference_code')} className={campo} />
          <Erro texto={erros.reference_code} />
        </label>
      </div>
      <label className="block text-[11px] text-slate-400">Nome (obrigatório)
        <input value={form.nome} maxLength={300} onChange={mudar('nome')} className={campo} placeholder="ex.: Creme de Leite 200g" />
        <Erro texto={erros.nome} />
      </label>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <label className="text-[11px] text-slate-400">Peso em kg (opcional)
          <input value={form.peso_kg} inputMode="decimal" onChange={mudar('peso_kg')} className={campo} placeholder="ex.: 1,5" />
          <Erro texto={erros.peso_kg} />
        </label>
        <label className="text-[11px] text-slate-400">Fonte (opcional)
          <input value={form.fonte} maxLength={100} onChange={mudar('fonte')} className={campo} placeholder="ex.: embalagem" />
          <Erro texto={erros.fonte} />
        </label>
        <label className="text-[11px] text-slate-400">Confiança
          <select value={form.confianca} onChange={mudar('confianca')} className={campo}>
            {CONFIANCAS.map((c) => <option key={c.valor} value={c.valor}>{c.rotulo}</option>)}
          </select>
          <Erro texto={erros.confianca} />
        </label>
      </div>
      <p className="text-[10px] text-slate-500">Sem peso, o item entra na fila "sem peso". O peso é só uma informação: nada é bloqueado por ele.</p>
      <Erro texto={erroServidor} />
      <button type="submit" disabled={salvando} className="flex items-center gap-1 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs font-semibold">
        {salvando ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} Criar item
      </button>
    </form>
  );
}
