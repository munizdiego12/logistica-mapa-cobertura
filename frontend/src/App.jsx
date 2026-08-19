import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  Truck, DollarSign, Navigation, Package, Upload, 
  MapPin, Sliders, ArrowUpRight, Play, Loader2,
  Layers, ShieldCheck, Activity, Plus, Trash2, Users
} from 'lucide-react';
import MapaLeaflet from './components/MapaLeaflet';

const API_BASE = 'https://routeflow-backend-v5ji.onrender.com/api';

export default function App() {
  const [loading, setLoading] = useState(false);
  const [modais, setModais] = useState({
    'Moto': { capacidade: 10, consumo_kml: 30.0 },
    'Carro de Passeio': { capacidade: 25, consumo_kml: 11.5 },
    'Fiorino / Van': { capacidade: 60, consumo_kml: 9.0 },
    'VUC / Caminhão 3/4': { capacidade: 150, consumo_kml: 6.5 }
  });

  const [precoGasolina, setPrecoGasolina] = useState(5.80);
  const [custoHora, setCustoHora] = useState(25.00);

  // Lista dinâmica de frota
  const [frota, setFrota] = useState([
    { id: 1, motorista: 'Motorista 01', modal: 'Carro de Passeio' },
    { id: 2, motorista: 'Motorista 02', modal: 'Fiorino / Van' }
  ]);

  const [origem, setOrigem] = useState({
    rua: 'Avenida Paulista',
    numero: '1000',
    bairro: 'Bela Vista',
    cep: '01310-100'
  });

  const [pedidos, setPedidos] = useState([
    { id_pedido: 'PED-01', cliente: 'Diego Muniz', logradouro: 'Rua Bela Cintra', numero: '500', bairro: 'Consolação', cep: '01415-000', volume: 1 },
    { id_pedido: 'PED-02', cliente: 'Tech Hub SP', logradouro: 'Rua Oscar Freire', numero: '900', bairro: 'Cerqueira César', cep: '01426-001', volume: 2 },
    { id_pedido: 'PED-03', cliente: 'Alpha Coworking', logradouro: 'Av Brigadeiro Faria Lima', numero: '2000', bairro: 'Pinheiros', cep: '01452-001', volume: 1 },
    { id_pedido: 'PED-04', cliente: 'Studio Design', logradouro: 'Rua dos Pinheiros', numero: '450', bairro: 'Pinheiros', cep: '05422-000', volume: 1 },
    { id_pedido: 'PED-05', cliente: 'Fintech SP', logradouro: 'Rua Funchal', numero: '418', bairro: 'Vila Olímpia', cep: '04551-060', volume: 3 },
    { id_pedido: 'PED-06', cliente: 'Log Lab', logradouro: 'Av Engenheiro Luís Carlos Berrini', numero: '105', bairro: 'Brooklin', cep: '04571-010', volume: 1 }
  ]);

  const [resultado, setResultado] = useState(null);

  useEffect(() => {
    axios.get(`${API_BASE}/modais`)
      .then(res => {
        if (Object.keys(res.data).length > 0) setModais(res.data);
      })
      .catch(() => {});
  }, []);

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

  const handleOtimizar = async () => {
    setLoading(true);
    try {
      const res = await axios.post(`${API_BASE}/otimizar`, {
        origem_rua: origem.rua,
        origem_num: origem.numero,
        origem_bairro: origem.bairro,
        origem_cep: origem.cep,
        modal: frota[0]?.modal || 'Carro de Passeio',
        frota: frota,
        preco_gasolina: Number(precoGasolina),
        custo_hora: Number(custoHora),
        pedidos: pedidos
      });
      setResultado(res.data);
    } catch (err) {
      alert('Falha na comunicação com o backend FastAPI (porta 8000). Verifique se o servidor está rodando.');
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      setLoading(true);
      const res = await axios.post(`${API_BASE}/upload`, formData);
      setPedidos(res.data.pedidos);
    } catch (err) {
      alert('Erro ao importar arquivo. Certifique-se de que é uma planilha válida (.csv ou .xlsx).');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#030712] text-slate-100 flex flex-col antialiased selection:bg-blue-600 selection:text-white">
      
      {/* Navbar Superior Zubale */}
      <header className="h-16 border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl overflow-hidden flex items-center justify-center bg-[#5B2E91] border border-[#7C3AED]/50 shadow-md shadow-purple-950/40 shrink-0">
            <img 
              src="logo-zubale.svg" 
              alt="Zubale Logo" 
              className="w-full h-full object-cover"
            />
          </div>

          <div>
            <div className="flex items-center gap-2">
              <span className="font-extrabold text-base tracking-tight text-white">
                Zubale
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-300 border border-purple-500/20 font-semibold uppercase">
                Operations & Routing
              </span>
            </div>
            <p className="text-[11px] text-slate-400">Inteligência Logística • Gestão Multimodal de Frota</p>
          </div>
        </div>

        <div className="flex items-center gap-4 text-xs">
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/80 border border-slate-800 text-slate-300">
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
            <span>Motor VRP / OSRM Ativo</span>
          </div>
          <div className="flex items-center gap-1.5 text-slate-400 font-mono text-[11px]">
            <ShieldCheck className="w-4 h-4 text-purple-400" />
            <span>FastAPI Core</span>
          </div>
        </div>
      </header>

      {/* Espaço de Trabalho Principal */}
      <div className="flex-1 flex flex-col lg:flex-row">
        
        {/* Painel Lateral de Parâmetros */}
        <aside className="w-full lg:w-[410px] border-r border-slate-800/80 bg-slate-900/30 p-6 flex flex-col gap-6 backdrop-blur-sm overflow-y-auto">
          
          {/* Importação de Arquivos */}
          <div>
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block mb-2.5">Entrada de Dados</span>
            <label className="border border-dashed border-slate-800 hover:border-blue-500/60 transition-all rounded-xl p-4 flex flex-col items-center justify-center cursor-pointer bg-slate-900/40 group">
              <Upload className="w-5 h-5 text-slate-400 group-hover:text-blue-400 transition-colors mb-1.5" />
              <span className="text-xs font-semibold text-slate-200">Importar Planilha</span>
              <span className="text-[11px] text-slate-500 mt-0.5">Formatos .CSV ou .XLSX</span>
              <input type="file" accept=".csv,.xlsx" onChange={handleFileUpload} className="hidden" />
            </label>
            <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400 px-1">
              <span>Fila de Entregas:</span>
              <span className="font-mono text-slate-200 font-medium">{pedidos.length} pontos cadastrados</span>
            </div>
          </div>

          {/* Configuração do CD / Hub */}
          <div className="space-y-3">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <MapPin className="w-3.5 h-3.5 text-blue-400" /> Centro de Distribuição (Origem)
            </span>
            <input 
              type="text" 
              value={origem.rua} 
              onChange={(e) => setOrigem({...origem, rua: e.target.value})}
              placeholder="Logradouro"
              className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2.5 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
            />
            <div className="grid grid-cols-2 gap-2">
              <input 
                type="text" 
                value={origem.numero} 
                onChange={(e) => setOrigem({...origem, numero: e.target.value})}
                placeholder="Número"
                className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
              />
              <input 
                type="text" 
                value={origem.cep} 
                onChange={(e) => setOrigem({...origem, cep: e.target.value})}
                placeholder="CEP"
                className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
              />
            </div>
          </div>

          {/* Gestão de Frota e Modais */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-blue-400" /> Frota Disponível ({frota.length})
              </span>
              <button 
                onClick={adicionarMotorista}
                className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 font-semibold px-2 py-1 rounded bg-blue-500/10 border border-blue-500/20 transition-colors"
              >
                <Plus className="w-3 h-3" /> Adicionar
              </button>
            </div>

            <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
              {frota.map((item) => (
                <div key={item.id} className="flex items-center gap-2 bg-slate-900/90 border border-slate-800/80 p-2.5 rounded-lg">
                  <div className="flex-1">
                    <span className="text-[11px] font-medium text-slate-300 block">{item.motorista}</span>
                    <select
                      value={item.modal}
                      onChange={(e) => atualizarModalMotorista(item.id, e.target.value)}
                      className="w-full text-[11px] bg-slate-950 border border-slate-800 focus:border-blue-500/80 rounded px-2 py-1.5 mt-1.5 text-slate-200 focus:outline-none"
                    >
                      {Object.keys(modais).map((m) => (
                        <option key={m} value={m} className="bg-slate-900 text-slate-100">
                          {m} (Cap: {modais[m]?.capacidade || '--'} un)
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

          {/* Parâmetros Financeiros */}
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
            disabled={loading}
            className="mt-auto w-full py-3.5 bg-blue-600 hover:bg-blue-500 active:scale-[0.99] transition-all rounded-xl font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-blue-600/25 text-white disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-current" />}
            {loading ? 'Calculando Malha Viária...' : 'Executar Roteirização'}
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
                <span className="text-2xl font-black text-white font-mono">{resultado ? resultado.kpis.total_pedidos : pedidos.length}</span>
                <span className="text-xs text-slate-500">entregas</span>
              </div>
            </div>

            <div className="bg-slate-900/50 border border-slate-800/80 p-5 rounded-xl">
              <div className="flex items-center justify-between text-slate-400 mb-2">
                <span className="text-[11px] font-semibold tracking-wider uppercase">Veículos Alocados</span>
                <Truck className="w-4 h-4 text-indigo-400" />
              </div>
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-black text-white font-mono">{resultado ? resultado.kpis.total_veiculos : frota.length}</span>
                <span className="text-xs text-slate-500">rotas</span>
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
                <h3 className="font-bold text-xs uppercase tracking-wider text-slate-200">Traçado Geoespacial em Malha Real</h3>
                <p className="text-[11px] text-slate-500">Isolinhas concêntricas de alcance e percursos otimizados</p>
              </div>
              <span className="text-[10px] font-mono px-2 py-1 bg-slate-900 border border-slate-800 text-slate-400 rounded-md">
                OSRM Routing Engine
              </span>
            </div>
            
            {resultado ? (
              <MapaLeaflet origem={resultado.origem} rotas={resultado.rotas} />
            ) : (
              <div className="h-[460px] flex flex-col items-center justify-center border border-slate-800/80 rounded-xl bg-slate-950/40 text-slate-500 gap-2">
                <Navigation className="w-8 h-8 text-slate-600 stroke-[1.5]" />
                <p className="text-xs font-medium">Inicie a roteirização para projetar as rotas e alocações de frota.</p>
              </div>
            )}
          </div>

          {/* Tabela de Detalhamento por Rota */}
          {resultado && (
            <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl overflow-hidden">
              <div className="p-4 border-b border-slate-800/80 flex items-center justify-between">
                <h3 className="font-bold text-xs uppercase tracking-wider text-slate-200">Matriz de Desempenho por Rota e Motorista</h3>
                <span className="text-[11px] text-slate-400">{resultado.rotas.length} rotas geradas</span>
              </div>
              
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800/80 text-[11px] uppercase tracking-wider">
                    <tr>
                      <th className="p-3.5 font-semibold">Rota / Veículo</th>
                      <th className="p-3.5 font-semibold">Entregas</th>
                      <th className="p-3.5 font-semibold">Quilometragem</th>
                      <th className="p-3.5 font-semibold">Tempo Previsto</th>
                      <th className="p-3.5 font-semibold">Custo Operacional</th>
                      <th className="p-3.5 font-semibold">Custo Médio / Un</th>
                      <th className="p-3.5 font-semibold text-right">Ação</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono text-[12px]">
                    {resultado.rotas.map((r, idx) => (
                      <tr key={r.id} className="hover:bg-slate-800/30 transition-colors">
                        <td className="p-3.5 font-sans font-bold flex items-center gap-2">
                          <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: r.cor }}></span>
                          <span>Rota #{r.id}</span>
                          <span className="text-[10px] font-normal px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                            {frota[idx]?.modal || 'Padrão'}
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
                            Navegação <ArrowUpRight className="w-3 h-3" />
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