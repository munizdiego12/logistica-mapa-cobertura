// Cadastro de motoristas e tipos de veículo (valor base por rota e peso de referência).
// Qualquer operador logado edita; o sistema guarda quem alterou e quando. Motorista não é apagado: é desativado.
// O peso de referência é só um guia para o montador de rotas: não é limite e nunca bloqueia nem avisa nada.
import { useEffect, useState } from 'react';
import { X, Loader2, Save, AlertCircle, CheckCircle2, Users, Truck, Plus, Power } from 'lucide-react';
import { validarValorRota, formatarReais } from '../services/valorRota';

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
      setErro('Digite o valor base da rota em reais, por exemplo 130 ou 130,50.');
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
          <span className="block">Valor base por rota (R$)</span>
          <input
            type="text"
            inputMode="decimal"
            value={custo}
            onChange={(e) => setCusto(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && mudou) salvar(); }}
            aria-label={`Valor base por rota de ${tipo.nome}`}
            className="w-28 px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm font-mono focus:outline-none focus:border-blue-500"
          />
          <span className="block text-[10px] text-slate-500">Usado quando o campo de valor fica vazio na roteirização</span>
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

function LinhaMotorista({ motorista, tipos, onSalvar }) {
  const [nome, setNome] = useState(motorista.nome);
  const [tipoVeiculo, setTipoVeiculo] = useState(motorista.tipo_veiculo);
  const [valor, setValor] = useState(formatarNumero(motorista.valor_rota, 2));
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState('');

  const valorBase = tipos.find((t) => t.nome === tipoVeiculo)?.custo_rota;
  const mudou = nome.trim() !== motorista.nome || tipoVeiculo !== motorista.tipo_veiculo
    || valor.trim() !== formatarNumero(motorista.valor_rota, 2);

  const gravar = async (ativo) => {
    if (nome.trim() === '') {
      setErro('Informe o nome do motorista.');
      return;
    }
    const conferencia = validarValorRota(valor);
    if (!conferencia.ok) {
      setErro(conferencia.mensagem);
      return;
    }
    setErro('');
    setSalvando(true);
    const mensagem = await onSalvar(motorista, { nome: nome.trim(), tipo_veiculo: tipoVeiculo, ativo, valor_rota: valor.trim() === '' ? null : valor.trim() });
    setSalvando(false);
    if (mensagem) setErro(mensagem);
  };

  const alternarAtivo = () => {
    if (motorista.ativo && !window.confirm(`Desativar ${motorista.nome}? Ele deixa de entrar nas rotas, mas continua cadastrado e pode ser reativado.`)) return;
    gravar(!motorista.ativo);
  };

  return (
    <div className={`p-3 rounded-lg border space-y-2 ${motorista.ativo ? 'bg-slate-900/70 border-slate-800' : 'bg-slate-950/60 border-slate-800/60 opacity-75'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={nome}
          maxLength={120}
          onChange={(e) => setNome(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && mudou) gravar(motorista.ativo); }}
          aria-label="Nome do motorista"
          className="flex-1 min-w-[160px] px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm focus:outline-none focus:border-blue-500"
        />
        <select
          value={tipoVeiculo}
          onChange={(e) => setTipoVeiculo(e.target.value)}
          aria-label={`Tipo de veículo de ${motorista.nome}`}
          className="px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-200 text-xs"
        >
          {tipos.map((t) => <option key={t.id} value={t.nome}>{t.nome}</option>)}
        </select>
        <button
          onClick={() => gravar(motorista.ativo)}
          disabled={salvando || !mudou}
          className="flex items-center gap-1 px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-xs font-semibold transition-colors"
        >
          {salvando ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />} Salvar
        </button>
        <button
          onClick={alternarAtivo}
          disabled={salvando}
          className={`flex items-center gap-1 px-2 py-1 rounded text-[11px] font-semibold border disabled:opacity-40 ${
            motorista.ativo
              ? 'text-slate-300 border-slate-700 hover:text-amber-300 hover:border-amber-500/40'
              : 'text-emerald-300 border-emerald-500/30 hover:bg-emerald-950/30'
          }`}
        >
          <Power className="w-3 h-3" /> {motorista.ativo ? 'Desativar' : 'Reativar'}
        </button>
        {!motorista.ativo && <span className="text-[10px] uppercase tracking-wider text-slate-500">Desativado</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400">
          Valor próprio por rota (opcional)
          <input
            type="text"
            inputMode="decimal"
            value={valor}
            onChange={(e) => setValor(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && mudou) gravar(motorista.ativo); }}
            placeholder="Vazio usa o valor base"
            aria-label={`Valor próprio por rota de ${motorista.nome}`}
            className="w-40 px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm font-mono placeholder:text-slate-600 focus:outline-none focus:border-blue-500"
          />
        </label>
        {valorBase !== undefined && (
          <span className="text-[11px] text-slate-500">Valor base do tipo: <span className="font-mono text-slate-300">{formatarReais(valorBase)}</span></span>
        )}
      </div>
      {erro && <p className="flex items-center gap-1 text-[11px] text-amber-300"><AlertCircle className="w-3 h-3" /> {erro}</p>}
      {quemAlterou(motorista) && <p className="text-[10px] text-slate-500">{quemAlterou(motorista)}</p>}
    </div>
  );
}

export default function Motoristas({ api, onFechar, onMudou }) {
  const [tipos, setTipos] = useState([]);
  const [motoristas, setMotoristas] = useState([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState('');
  const [aviso, setAviso] = useState('');
  const [novoNome, setNovoNome] = useState('');
  const [novoTipo, setNovoTipo] = useState('');
  const [novoValor, setNovoValor] = useState('');
  const [criando, setCriando] = useState(false);
  const [erroNovo, setErroNovo] = useState('');

  useEffect(() => {
    let ativo = true;
    Promise.all([api.get('/tipos-veiculo'), api.get('/motoristas')])
      .then(([respTipos, respMotoristas]) => {
        if (!ativo) return;
        setTipos(respTipos.data);
        setMotoristas(respMotoristas.data);
        setNovoTipo((atual) => atual || respTipos.data[0]?.nome || '');
      })
      .catch((err) => { if (ativo) setErro(textoDoErro(err, 'Não foi possível carregar o cadastro. Tente de novo.')); })
      .finally(() => { if (ativo) setCarregando(false); });
    return () => { ativo = false; };
  }, [api]);

  const avisar = (texto) => {
    setAviso(texto);
    setTimeout(() => setAviso(''), 3500);
  };

  // Devolvem '' quando deu certo ou o texto do erro (mostrado na própria linha).
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

  const salvarMotorista = async (motorista, campos) => {
    try {
      const { data } = await api.put(`/motoristas/${motorista.id}`, campos);
      setMotoristas((atuais) => atuais.map((m) => (m.id === motorista.id ? data : m)));
      onMudou?.();
      avisar(
        motorista.ativo === data.ativo ? `Dados de ${data.nome} salvos.` : data.ativo ? `${data.nome} reativado.` : `${data.nome} desativado.`,
      );
      return '';
    } catch (err) {
      return textoDoErro(err, 'Não foi possível salvar. Tente de novo.');
    }
  };

  const criar = async (e) => {
    e.preventDefault();
    if (novoNome.trim() === '') {
      setErroNovo('Informe o nome do motorista.');
      return;
    }
    const conferencia = validarValorRota(novoValor);
    if (!conferencia.ok) {
      setErroNovo(conferencia.mensagem);
      return;
    }
    setErroNovo('');
    setCriando(true);
    try {
      const { data } = await api.post('/motoristas', { nome: novoNome.trim(), tipo_veiculo: novoTipo, valor_rota: novoValor.trim() === '' ? null : novoValor.trim() });
      setMotoristas((atuais) => [...atuais, data]);
      setNovoNome('');
      setNovoValor('');
      onMudou?.();
      avisar(`${data.nome} cadastrado.`);
    } catch (err) {
      setErroNovo(textoDoErro(err, 'Não foi possível cadastrar. Tente de novo.'));
    } finally {
      setCriando(false);
    }
  };

  const ativos = motoristas.filter((m) => m.ativo);
  const inativos = motoristas.filter((m) => !m.ativo);

  return (
    <div className="fixed inset-0 z-[100] bg-slate-950/80 backdrop-blur-sm flex items-start justify-center p-4 overflow-y-auto" role="dialog" aria-modal="true" aria-label="Motoristas e veículos">
      <div className="w-full max-w-3xl my-6 rounded-xl bg-slate-900 border border-slate-800 shadow-2xl">
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
            Os motoristas ativos são os que entram nas rotas. Qualquer operador pode editar; fica registrado quem alterou e quando.
            O valor base por rota é o de cada tipo de veículo. Cada motorista pode ter um valor próprio (opcional; vazio usa o valor base, e pode ser trocado quando ele mudar de loja). Na roteirização vale, do mais específico ao mais geral: o valor digitado na tela, o valor próprio do motorista e o valor base. O peso de referência é opcional e é só um guia para montar as rotas:
            não é um limite e o sistema nunca bloqueia nem avisa por causa dele.
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

          {!carregando && !erro && (
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
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                  <Users className="w-3.5 h-3.5 text-blue-400" /> Motoristas ({ativos.length} ativos)
                </h3>

                <form onSubmit={criar} className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      value={novoNome}
                      maxLength={120}
                      onChange={(e) => setNovoNome(e.target.value)}
                      placeholder="Nome do novo motorista"
                      aria-label="Nome do novo motorista"
                      className="flex-1 min-w-[160px] px-2 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm placeholder:text-slate-600 focus:outline-none focus:border-blue-500"
                    />
                    <select
                      value={novoTipo}
                      onChange={(e) => setNovoTipo(e.target.value)}
                      aria-label="Tipo de veículo do novo motorista"
                      className="px-2 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-200 text-xs"
                    >
                      {tipos.map((t) => <option key={t.id} value={t.nome}>{t.nome}</option>)}
                    </select>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={novoValor}
                      onChange={(e) => setNovoValor(e.target.value)}
                      placeholder="Valor próprio (opcional)"
                      aria-label="Valor próprio por rota do novo motorista (opcional)"
                      title="Vazio usa o valor base"
                      className="w-44 px-2 py-1.5 rounded bg-slate-950 border border-slate-700 text-slate-100 text-sm font-mono placeholder:text-slate-600 focus:outline-none focus:border-blue-500"
                    />
                    <button
                      type="submit"
                      disabled={criando}
                      className="flex items-center gap-1 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-xs font-semibold transition-colors"
                    >
                      {criando ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />} Cadastrar
                    </button>
                  </div>
                  {erroNovo && <p className="flex items-center gap-1 text-[11px] text-amber-300"><AlertCircle className="w-3 h-3" /> {erroNovo}</p>}
                </form>

                {ativos.length === 0 && (
                  <p className="py-3 text-center text-sm text-slate-500">Nenhum motorista ativo. Cadastre um acima para poder gerar rotas.</p>
                )}
                {ativos.map((m) => (
                  <LinhaMotorista key={`${m.id}|${m.nome}|${m.tipo_veiculo}|${m.valor_rota ?? ''}|${m.ativo}|${m.atualizado_em ?? ''}`} motorista={m} tipos={tipos} onSalvar={salvarMotorista} />
                ))}

                {inativos.length > 0 && (
                  <>
                    <h4 className="pt-2 text-[11px] font-bold uppercase tracking-wider text-slate-500">Desativados ({inativos.length})</h4>
                    {inativos.map((m) => (
                      <LinhaMotorista key={`${m.id}|${m.nome}|${m.tipo_veiculo}|${m.valor_rota ?? ''}|${m.ativo}|${m.atualizado_em ?? ''}`} motorista={m} tipos={tipos} onSalvar={salvarMotorista} />
                    ))}
                  </>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
