import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  Truck, DollarSign, Navigation, Package, Upload, 
  MapPin, Sliders, ArrowUpRight, Play, Loader2,
  ShieldCheck, Activity, Plus, Trash2, Users, AlertCircle, 
  CheckSquare, Square, Download, FileSpreadsheet, FileDown,
  Settings, ChevronDown, ChevronUp, Layers, Compass, Table as TableIcon
} from 'lucide-react';
import MapaLeaflet from './components/MapaLeaflet';

const API_BASE = 'https://routeflow-backend-v5ji.onrender.com/api';

export default function App() {
  const [loading, setLoading] = useState(false);
  const [loadingCeps, setLoadingCeps] = useState(false);
  const [dadosCoberturaCeps, setDadosCoberturaCeps] = useState(null);
  
  // Painel de Configuração de Capacidades Variáveis por Loja
  const [mostrarConfigModais, setMostrarConfigModais] = useState(false);
  const [modais, setModais] = useState({
    'Moto': { capacidade: 3, consumo_kml: 30.0 },
    'Carro de Passeio': { capacidade: 5, consumo_kml: 11.5 },
    'Fiorino / Utilitário': { capacidade: 12, consumo_kml: 9.0 },
    'VUC / Caminhão 3/4': { capacidade: 30, consumo_kml: 6.5 }
  });

  const [precoGasolina, setPrecoGasolina] = useState(5.80);
  const [custoHora, setCustoHora] = useState(25.00);

  // Frota configurável
  const [frota, setFrota] = useState([
    { id: 1, motorista: 'Motorista 01', modal: 'Carro de Passeio' },
    { id: 2, motorista: 'Motorista 02', modal: 'Fiorino / Utilitário' }
  ]);

  // Hub Operacional
  const [origem, setOrigem] = useState({
    rua: '',
    numero: '',
    bairro: '',
    cep: ''
  });

  // Lista de Múltiplos Arquivos/Lotes de Pedidos
  const [lotes, setLotes] = useState([]);
  const [loteAtivoId, setLoteAtivoId] = useState(null);
  const [resultado, setResultado] = useState(null);

  const loteSelecionado = lotes.find(l => l.id === loteAtivoId);
  const pedidosAtivos = loteSelecionado ? loteSelecionado.pedidos : [];

  // Capacidade por Viagem Simultânea
  const capacidadeSimultaneaFrota = frota.reduce((acc, f) => {
    const cap = modais[f.modal]?.capacidade || 0;
    return acc + cap;
  }, 0);

  // Alterar capacidade variável de um modal específico
  const atualizarCapacidadeModal = (nomeModal, novaCapacidade) => {
    const valor = Math.max(1, parseInt(novaCapacidade) || 1);
    setModais(prev => ({
      ...prev,
      [nomeModal]: {
        ...prev[nomeModal],
        capacidade: valor
      }
    }));
  };

  const adicionarMotorista = () => {
    const nextId = frota.length > 0 ? Math.max(...frota.map(m => m.id)) + 1 : 1;
    const nomePadrao = `Motorista ${String(nextId).padStart(2, '0')}`;
    setFrota([...frota, { id: nextId, motorista: nomePadrao, modal: 'Carro de Passeio' }]);
  };

  const removerMotorista = (id) => {
    if (frota.length === 1) {
      alert('É necessário manter ao menos 1 motorista cadastrado na frota.');
      return;
    }
    setFrota(frota.filter(m => m.id !== id));
  };

  const atualizarModalMotorista = (id, novoModal) => {
    setFrota(frota.map(m => m.id === id ? { ...m, modal: novoModal } : m));
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    try {
      setLoading(true);
      const res = await axios.post(`${API_BASE}/upload`, formData);
      
      const novoLote = {
        id: Date.now(),
        nome: file.name,
        pedidos: res.data.pedidos,
        dataUpload: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };

      setLotes(prev => [...prev, novoLote]);
      setLoteAtivoId(novoLote.id);
    } catch (err) {
      alert('Erro ao importar arquivo. Certifique-se de que é uma planilha válida (.csv ou .xlsx).');
    } finally {
      setLoading(false);
      e.target.value = '';
    }
  };

  const removerLote = (id, e) => {
    e.stopPropagation();
    const novosLotes = lotes.filter(l => l.id !== id);
    setLotes(novosLotes);
    if (loteAtivoId === id) {
      setLoteAtivoId(novosLotes.length > 0 ? novosLotes[0].id : null);
      setResultado(null);
    }
  };

  // 1. Consultar Cobertura de CEPs por Haversine (0 a 30 km)
  const consultarCoberturaCeps = async () => {
    if (!origem.rua && !origem.cep) {
      alert('Por favor, informe o Logradouro ou o CEP da Loja Central.');
      return;
    }

    setLoadingCeps(true);
    try {
      const res = await axios.post(`${API_BASE}/cobertura-ceps`, {
        origem_rua: origem.rua || "Centro Operacional",
        origem_num: origem.numero || "S/N",
        origem_cep: origem.cep || "",
        origem_bairro: origem.bairro || "",
        raio_km: 30.0
      });
      setDadosCoberturaCeps(res.data);
    } catch (err) {
      alert('Erro ao calcular cobertura dinâmica de CEPs. Verifique a conexão com a API.');
    } finally {
      setLoadingCeps(false);
    }
  };

  const handleOtimizar = async () => {
    if (!origem.rua && !origem.cep) {
      alert('Por favor, informe o Logradouro ou o CEP da Loja Central.');
      return;
    }
    if (pedidosAtivos.length === 0) {
      alert('Selecione um lote com pedidos válidos antes de otimizar.');
      return;
    }

    setLoading(true);
    try {
      const res = await axios.post(`${API_BASE}/otimizar`, {
        origem_rua: origem.rua,
        origem_num: origem.numero,
        origem_bairro: origem.bairro,
        origem_cep: origem.cep,
        frota: frota,
        modais_config: modais,
        preco_gasolina: Number(precoGasolina),
        custo_hora: Number(custoHora),
        pedidos: pedidosAtivos
      });
      setResultado(res.data);
    } catch (err) {
      alert('Erro ao processar roteirização. Verifique os endereços informados e o status da API.');
    } finally {
      setLoading(false);
    }
  };

  const baixarPlanilhaModelo = () => {
    const cabecalho = "id,endereco,numero,bairro,cidade,uf,cep,volume\n";
    const linhasExemplo = [
      "101,Avenida Brigadeiro Luis Antonio,2000,Bela Vista,Sao Paulo,SP,01318-002,1",
      "102,Rua Augusta,1500,Consolacao,Sao Paulo,SP,01304-001,1",
      "103,Rua Oscar Freire,800,Cerqueira Cesar,Sao Paulo,SP,01426-000,1",
      "104,Rua da Consolacao,2400,Consolacao,Sao Paulo,SP,01301-100,1",
      "105,Alameda Santos,1800,Cerqueira Cesar,Sao Paulo,SP,01418-102,1"
    ].join("\n");

    const csvContent = "data:text/csv;charset=utf-8," + encodeURIComponent(cabecalho + linhasExemplo);
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', csvContent);
    downloadAnchor.setAttribute('download', 'modelo_pedidos_zubale.csv');
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const baixarModeloXLSX = () => {
    window.open(`${API_BASE}/modelo-xlsx`, '_blank');
  };

  // Exportar Tabela Gazin Log com Faixas de CEP
  const exportarTabelaGazin = () => {
    if (!dadosCoberturaCeps || !dadosCoberturaCeps.pontos_cobertos || dadosCoberturaCeps.pontos_cobertos.length === 0) {
      alert('Clique primeiro no botão "Raio 30 km" para calcular a cobertura.');
      return;
    }

    let csvContent = "data:text/csv;charset=utf-8,Codigo IBGE,UF,Cidade,Regiao_Bairro,Faixa Precificacao,CEP Inicial,CEP Final,Prazo Dias,Distancia KM\n";
    
    dadosCoberturaCeps.pontos_cobertos.forEach((p) => {
      const ibge = p.ibge || dadosCoberturaCeps.hub?.ibge || "";
      const uf = p.uf || dadosCoberturaCeps.hub?.uf || "";
      const cidade = p.cidade || dadosCoberturaCeps.hub?.cidade || "";
      const bairro = p.bairro || "Área Atendida";
      const cepIni = p.cep_inicial || "";
      const cepFim = p.cep_final || "";
      const prazo = p.dias_sla || (p.distancia_km <= 15 ? 1 : 2);
      const dist = p.distancia_km || 0;

      const linha = [
        ibge,
        `"${uf}"`,
        `"${cidade}"`,
        `"${bairro}"`,
        `"Raio ${dist} km"`,
        `"${cepIni}"`,
        `"${cepFim}"`,
        prazo,
        dist
      ].join(',');
      csvContent += linha + "\n";
    });

    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', encodeURI(csvContent));
    downloadAnchor.setAttribute('download', `tabela_frete_gazin_raio30km_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const exportarRomaneio = () => {
    if (!resultado || !resultado.rotas) return;

    let csvContent = "data:text/csv;charset=utf-8,Rota,Motorista,Viagem,Veiculo,Ordem_Parada,Endereco,Numero,Bairro,CEP,Volume\n";

    resultado.rotas.forEach((r) => {
      if (r.paradas && r.paradas.length > 0) {
        r.paradas.forEach((p, pIdx) => {
          const linha = [
            `Rota ${r.id}`,
            `"${r.motorista_base || r.motorista}"`,
            `Viagem ${r.viagem_num || 1}`,
            `"${r.modal}"`,
            pIdx + 1,
            `"${p.Endereco || p.rua || ''}"`,
            `"${p.Numero || p.numero || ''}"`,
            `"${p.Bairro || p.bairro || ''}"`,
            `"${p.CEP || p.cep || ''}"`,
            p.Volume || 1
          ].join(',');
          csvContent += linha + "\n";
        });
      }
    });

    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', encodeURI(csvContent));
    downloadAnchor.setAttribute('download', `romaneio_expedicao_zubale_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col antialiased selection:bg-blue-600 selection:text-white">
      
      {/* Navbar Superior */}
      <header className="h-16 border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl overflow-hidden flex items-center justify-center bg-blue-500/10 border border-blue-500/20 shadow-md shadow-blue-950/40 p-1.5 shrink-0">
            <img 
              src="logo-zubale.svg" 
              alt="Zubale Logo" 
              className="w-full h-full object-contain"
            />
          </div>

          <div>
            <div className="flex items-center gap-2">
              <span className="font-extrabold text-base tracking-tight text-white">
                Zubale
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 font-semibold uppercase">
                Operations & Routing
              </span>
            </div>
            <p className="text-[11px] text-slate-400">Inteligência Logística • Gestão Multimodal & Haversine 30km</p>
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs">
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-800 text-slate-300">
            <Compass className="w-3.5 h-3.5 text-emerald-400" />
            <span>Haversine Raio 30km Ativo</span>
          </div>
          <div className="flex items-center gap-1.5 text-slate-400 font-mono text-[11px]">
            <ShieldCheck className="w-4 h-4 text-blue-400" />
            <span>FastAPI Core</span>
          </div>
        </div>
      </header>

      {/* Espaço de Trabalho */}
      <div className="flex-1 flex flex-col lg:flex-row">
        
        {/* Painel Lateral */}
        <aside className="w-full lg:w-[420px] border-r border-slate-800/80 bg-slate-900/30 p-6 flex flex-col gap-6 backdrop-blur-sm overflow-y-auto">
          
          {/* 1. Hub / Loja Central */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5 text-blue-400" /> Loja Central / Hub de Origem
              </span>
              <button
                onClick={consultarCoberturaCeps}
                disabled={loadingCeps || !origem.rua}
                className="text-[10px] font-semibold text-emerald-400 hover:text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded transition-colors flex items-center gap-1 disabled:opacity-40"
                title="Consultar Faixa de CEPs até 30km"
              >
                {loadingCeps ? <Loader2 className="w-3 h-3 animate-spin" /> : <Compass className="w-3 h-3" />}
                Raio 30 km
              </button>
            </div>

            <input 
              type="text" 
              value={origem.rua} 
              onChange={(e) => setOrigem({...origem, rua: e.target.value})}
              placeholder="Logradouro da Loja (ex: Av. Paulista)"
              className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2.5 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
            />
            <div className="grid grid-cols-2 gap-2">
              <input 
                type="text" 
                value={origem.numero} 
                onChange={(e) => setOrigem({...origem, numero: e.target.value})}
                placeholder="Número (ex: 1000)"
                className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
              />
              <input 
                type="text" 
                value={origem.cep} 
                onChange={(e) => setOrigem({...origem, cep: e.target.value})}
                placeholder="CEP (ex: 01310-100)"
                className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
              />
            </div>

            {/* Painel Informativo da Consulta de Raio 30km */}
            {dadosCoberturaCeps && (
              <div className="p-2.5 rounded-lg bg-emerald-950/30 border border-emerald-500/30 text-[11px] space-y-1">
                <div className="flex justify-between items-center text-emerald-400 font-bold">
                  <span>Cobertura Haversine:</span>
                  <span>{dadosCoberturaCeps.total_pontos} CEPs no Raio de 30 km</span>
                </div>
                <button
                  onClick={exportarTabelaGazin}
                  className="w-full mt-1.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-semibold text-[10px] flex items-center justify-center gap-1 transition-colors"
                >
                  <TableIcon className="w-3 h-3" /> Baixar Tabela de Frete (Gazin Log)
                </button>
              </div>
            )}
          </div>

          {/* 2. Gerenciador de Lotes de Pedidos */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <FileSpreadsheet className="w-3.5 h-3.5 text-blue-400" /> Lotes de Pedidos ({lotes.length})
              </span>
              
              <div className="flex items-center gap-1.5">
                <button 
                  onClick={baixarPlanilhaModelo}
                  className="inline-flex items-center gap-1 text-[10px] text-blue-400 hover:text-blue-300 font-medium px-2 py-0.5 rounded bg-blue-500/10 border border-blue-500/20 transition-colors"
                  title="Baixar Modelo CSV"
                >
                  <Download className="w-2.5 h-2.5" /> CSV
                </button>
                <button 
                  onClick={baixarModeloXLSX}
                  className="inline-flex items-center gap-1 text-[10px] text-emerald-400 hover:text-emerald-300 font-medium px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 transition-colors"
                  title="Baixar Modelo Excel (.xlsx)"
                >
                  <Download className="w-2.5 h-2.5" /> XLSX
                </button>
              </div>
            </div>

            <label className="border border-dashed border-slate-800 hover:border-blue-500/60 transition-all rounded-xl p-3.5 flex flex-col items-center justify-center cursor-pointer bg-slate-900/40 group">
              <Upload className="w-4 h-4 text-slate-400 group-hover:text-blue-400 transition-colors mb-1" />
              <span className="text-xs font-semibold text-slate-200">Anexar Planilha de Entregas</span>
              <span className="text-[10px] text-slate-500">Formatos aceitos: .csv ou .xlsx</span>
              <input type="file" accept=".csv,.xlsx" onChange={handleFileUpload} className="hidden" />
            </label>

            {lotes.length > 0 && (
              <div className="space-y-2 max-h-44 overflow-y-auto pr-1">
                {lotes.map((lote) => {
                  const ativo = lote.id === loteAtivoId;
                  return (
                    <div 
                      key={lote.id} 
                      onClick={() => { setLoteAtivoId(lote.id); setResultado(null); }}
                      className={`flex items-center justify-between p-2.5 rounded-lg cursor-pointer border transition-all ${
                        ativo 
                          ? 'bg-blue-500/10 border-blue-500/50 shadow-sm shadow-blue-500/10' 
                          : 'bg-slate-900/90 border-slate-800/80 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <button type="button" className="text-blue-400 shrink-0">
                          {ativo ? (
                            <CheckSquare className="w-4 h-4 text-blue-400 fill-blue-500/20" />
                          ) : (
                            <Square className="w-4 h-4 text-slate-600" />
                          )}
                        </button>
                        <div className="min-w-0">
                          <p className={`text-xs font-medium truncate ${ativo ? 'text-white font-semibold' : 'text-slate-300'}`}>
                            {lote.nome}
                          </p>
                          <p className="text-[10px] text-slate-400 font-mono">
                            {lote.pedidos.length} entregas • {lote.dataUpload}
                          </p>
                        </div>
                      </div>

                      <button
                        onClick={(e) => removerLote(lote.id, e)}
                        className="p-1.5 text-slate-500 hover:text-rose-400 transition-colors ml-2 shrink-0"
                        title="Excluir este arquivo"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="flex items-center justify-between text-[11px] px-1">
              <span className="text-slate-400">Lote Selecionado:</span>
              <span className={`font-mono font-semibold ${pedidosAtivos.length > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                {pedidosAtivos.length} pedidos
              </span>
            </div>
          </div>

          {/* 3. Configuração de Capacidades Variáveis por Loja */}
          <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-xl space-y-2.5">
            <button
              onClick={() => setMostrarConfigModais(!mostrarConfigModais)}
              className="w-full flex items-center justify-between text-[11px] font-bold text-slate-300 hover:text-white uppercase tracking-wider"
            >
              <div className="flex items-center gap-1.5 text-blue-400">
                <Settings className="w-3.5 h-3.5" />
                <span>Capacidades Máximas por Modal</span>
              </div>
              {mostrarConfigModais ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>

            {mostrarConfigModais && (
              <div className="pt-2 border-t border-slate-800 space-y-2">
                <p className="text-[10px] text-slate-400">Defina o teto de pedidos por viagem para cada tipo de veículo nesta loja:</p>
                <div className="grid grid-cols-2 gap-2">
                  {Object.keys(modais).map((modalKey) => (
                    <div key={modalKey} className="bg-slate-900/90 border border-slate-800/80 p-2 rounded-lg">
                      <span className="text-[10px] text-slate-300 font-medium block truncate">{modalKey}</span>
                      <div className="flex items-center gap-1 mt-1">
                        <input
                          type="number"
                          min="1"
                          max="200"
                          value={modais[modalKey].capacidade}
                          onChange={(e) => atualizarCapacidadeModal(modalKey, e.target.value)}
                          className="w-full text-xs font-mono font-bold bg-slate-950 border border-slate-800 rounded px-2 py-1 text-emerald-400 focus:outline-none focus:border-blue-500"
                        />
                        <span className="text-[10px] text-slate-500">un</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 4. Frota Multimodal & Monitor de Viagens */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-blue-400" /> Frota Alocada ({frota.length})
              </span>
              <button 
                onClick={adicionarMotorista}
                className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 font-semibold px-2 py-1 rounded bg-blue-500/10 border border-blue-500/20 transition-colors"
              >
                <Plus className="w-3 h-3" /> Adicionar
              </button>
            </div>

            <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-[11px] space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Capacidade por Saída Simultânea:</span>
                <span className="font-mono font-bold text-slate-200">
                  {capacidadeSimultaneaFrota} pedidos / onda
                </span>
              </div>
              {pedidosAtivos.length > capacidadeSimultaneaFrota && (
                <div className="flex items-center gap-1.5 text-blue-400 text-[10px] pt-1 border-t border-slate-800/80">
                  <Layers className="w-3.5 h-3.5 shrink-0" />
                  <span>Demanda maior que a frota: o sistema gerará <b>múltiplas viagens/ondas</b> por motorista.</span>
                </div>
              )}
            </div>

            <div className="space-y-2 max-h-36 overflow-y-auto pr-1">
              {frota.map((item) => (
                <div key={item.id} className="flex items-center gap-2 bg-slate-900/90 border border-slate-800/80 p-2 rounded-lg">
                  <div className="flex-1">
                    <span className="text-[11px] font-medium text-slate-300 block">{item.motorista}</span>
                    <select
                      value={item.modal}
                      onChange={(e) => atualizarModalMotorista(item.id, e.target.value)}
                      className="w-full text-[11px] bg-slate-950 border border-slate-800 focus:border-blue-500/80 rounded px-2 py-1 mt-1 text-slate-200 focus:outline-none"
                    >
                      {Object.keys(modais).map((m) => (
                        <option key={m} value={m} className="bg-slate-900 text-slate-100">
                          {m} (Máx: {modais[m]?.capacidade} un)
                        </option>
                      ))}
                    </select>
                  </div>
                  <button
                    onClick={() => removerMotorista(item.id)}
                    className="p-1.5 text-slate-500 hover:text-rose-400 transition-colors"
                    title="Remover Motorista"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* 5. Parâmetros Financeiros */}
          <div className="space-y-3">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-blue-400" /> Parâmetros Financeiros
            </span>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-slate-400 block mb-1">Combustível (R$/L)</label>
                <input 
                  type="number" step="0.1" 
                  value={precoGasolina} 
                  onChange={(e) => setPrecoGasolina(e.target.value)}
                  className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-400 block mb-1">Motorista (R$/h)</label>
                <input 
                  type="number" step="1.0" 
                  value={custoHora} 
                  onChange={(e) => setCustoHora(e.target.value)}
                  className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
                />
              </div>
            </div>
          </div>

          {/* Botão de Execução */}
          <button
            onClick={handleOtimizar}
            disabled={loading || pedidosAtivos.length === 0 || !origem.rua}
            className="mt-auto w-full py-3.5 bg-blue-600 hover:bg-blue-500 active:scale-[0.99] transition-all rounded-xl font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-blue-600/25 text-white disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-current" />}
            {loading ? 'Agrupando Polígonos & Otimizando...' : 'Executar Roteirização'}
          </button>
        </aside>

        {/* Dashboard de Métricas e Mapa */}
        <main className="flex-1 p-6 lg:p-8 space-y-6 overflow-y-auto">
          
          {/* Cards de Métricas */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-slate-900/50 border border-slate-800/80 p-5 rounded-xl">
              <div className="flex items-center justify-between text-slate-400 mb-2">
                <span className="text-[11px] font-semibold tracking-wider uppercase">Volume Total</span>
                <Package className="w-4 h-4 text-blue-400" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-black text-white font-mono">{resultado ? resultado.kpis.total_pedidos : pedidosAtivos.length}</span>
                <span className="text-xs text-slate-500">entregas</span>
              </div>
            </div>

            <div className="bg-slate-900/50 border border-slate-800/80 p-5 rounded-xl">
              <div className="flex items-center justify-between text-slate-400 mb-2">
                <span className="text-[11px] font-semibold tracking-wider uppercase">Rotas / Viagens</span>
                <Layers className="w-4 h-4 text-indigo-400" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-black text-white font-mono">
                  {resultado ? resultado.kpis.total_rotas_viagens : frota.length}
                </span>
                <span className="text-xs text-slate-500">
                  {resultado ? `(${resultado.kpis.total_veiculos} veículos)` : 'rotas'}
                </span>
              </div>
            </div>

            <div className="bg-slate-900/50 border border-slate-800/80 p-5 rounded-xl">
              <div className="flex items-center justify-between text-slate-400 mb-2">
                <span className="text-[11px] font-semibold tracking-wider uppercase">Extensão Viária</span>
                <Navigation className="w-4 h-4 text-emerald-400" />
              </div>
              <div className="flex items-baseline gap-1">
                <span className="text-2xl font-black text-white font-mono">{resultado ? resultado.kpis.km_total : '--'}</span>
                {resultado && <span className="text-xs text-slate-500">km</span>}
              </div>
            </div>

            <div className="bg-slate-900/50 border border-slate-800/80 p-5 rounded-xl">
              <div className="flex items-center justify-between text-slate-400 mb-2">
                <span className="text-[11px] font-semibold tracking-wider uppercase">Custo Estimado</span>
                <DollarSign className="w-4 h-4 text-emerald-400" />
              </div>
              <div>
                <span className="text-2xl font-black text-emerald-400 font-mono">
                  {resultado ? `R$ ${resultado.kpis.custo_total.toFixed(2)}` : '--'}
                </span>
                {resultado && (
                  <p className="text-[10px] text-slate-500 font-mono mt-0.5">
                    R$ {resultado.kpis.custo_medio_pedido.toFixed(2)} / entrega
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Visualizador do Mapa */}
          <div className="bg-slate-900/50 border border-slate-800/80 p-4 rounded-xl">
            <div className="flex items-center justify-between mb-3 px-1">
              <div>
                <h3 className="font-bold text-xs uppercase tracking-wider text-slate-200">Polígonos Espaciais & Raio de Cobertura</h3>
                <p className="text-[11px] text-slate-500">Isolinhas concêntricas até 30 km com cálculo de Haversine e traçado viário OSRM</p>
              </div>
              <span className="text-[10px] font-mono px-2 py-1 bg-slate-900 border border-slate-800 text-slate-400 rounded-md">
                Haversine + Polar VRP
              </span>
            </div>
            
            {resultado ? (
              <MapaLeaflet origem={resultado ? resultado.origem : (dadosCoberturaCeps ? dadosCoberturaCeps.hub : null)} rotas={resultado ? resultado.rotas : []} dadosCeps={dadosCoberturaCeps}/>
            ) : (
              <div className="h-[460px] flex flex-col items-center justify-center border border-slate-800/80 rounded-xl bg-slate-950/40 text-slate-500 gap-3">
                <div className="w-12 h-12 rounded-full bg-slate-900 flex items-center justify-center border border-slate-800">
                  <Navigation className="w-6 h-6 text-slate-500" />
                </div>
                <div className="text-center space-y-1">
                  <p className="text-xs font-semibold text-slate-300">Nenhuma rota ativa</p>
                  <p className="text-[11px] text-slate-500 max-w-sm">
                    Preencha a Loja Central, selecione um lote anexado e clique em Executar Roteirização.
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* Tabela de Resultados por Viagem / Motorista */}
          {resultado && (
            <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl overflow-hidden">
              <div className="p-4 border-b border-slate-800/80 flex items-center justify-between">
                <div>
                  <h3 className="font-bold text-xs uppercase tracking-wider text-slate-200">Matriz de Despacho & Ondas de Entrega</h3>
                  <p className="text-[11px] text-slate-400">{resultado.rotas.length} viagens distribuídas entre a frota</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={exportarRomaneio}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-lg text-xs font-medium transition-colors"
                  >
                    <FileDown className="w-3.5 h-3.5" /> Romaneio (.csv)
                  </button>
                </div>
              </div>
              
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800/80 text-[11px] uppercase tracking-wider">
                    <tr>
                      <th className="p-3.5 font-semibold">Despacho / Motorista</th>
                      <th className="p-3.5 font-semibold">Veículo</th>
                      <th className="p-3.5 font-semibold">Entregas</th>
                      <th className="p-3.5 font-semibold">Quilometragem</th>
                      <th className="p-3.5 font-semibold">Tempo</th>
                      <th className="p-3.5 font-semibold">Custo Rota</th>
                      <th className="p-3.5 font-semibold">Custo / Un</th>
                      <th className="p-3.5 font-semibold text-right">Navegação</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono text-[12px]">
                    {resultado.rotas.map((r) => (
                      <tr key={r.id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="p-3.5 font-sans font-bold flex items-center gap-2">
                          <span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: r.cor }}></span>
                          <span className="text-white">{r.motorista}</span>
                        </td>
                        <td className="p-3.5 text-slate-300 font-sans">
                          <span className="text-[10px] font-normal px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                            {r.modal}
                          </span>
                        </td>
                        <td className="p-3.5 text-slate-300 font-sans">{r.qtd_pedidos} paradas</td>
                        <td className="p-3.5 text-slate-300">{r.km_total} km</td>
                        <td className="p-3.5 text-slate-400">{r.tempo_formatado}</td>
                        <td className="p-3.5 font-semibold text-emerald-400">R$ {r.custo_total.toFixed(2)}</td>
                        <td className="p-3.5 text-slate-300">R$ {r.custo_por_pedido.toFixed(2)}</td>
                        <td className="p-3.5 text-right font-sans">
                          <a 
                            href={r.link_maps} 
                            target="_blank" 
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 bg-blue-600/10 hover:bg-blue-600 text-blue-400 hover:text-white rounded-md transition-all font-medium text-[11px] border border-blue-500/20"
                          >
                            Maps <ArrowUpRight className="w-3 h-3" />
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

        </main>
      </div>
    </div>
  );
}