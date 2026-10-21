import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import {
  Truck, Navigation, Package, Upload,
  MapPin, ArrowUpRight, Play, Loader2,
  ShieldCheck, Activity, Trash2, Users, AlertCircle,
  CheckSquare, Square, Download, FileSpreadsheet, FileDown,
  Settings, ChevronDown, ChevronUp, Layers, Compass, Table as TableIcon, Store, 
  AlertTriangle, Scale
} from 'lucide-react';
import MapaLeaflet from './components/MapaLeaflet';
import Login from './components/Login';
import PesosItens from './components/PesosItens';
import Motoristas from './components/Motoristas';
import SeletorMotoristas from './components/SeletorMotoristas';
import Lojas from './components/Lojas';
import SeletorLoja from './components/SeletorLoja';
import ListaPedidos from './components/ListaPedidos';
import RelatorioImportacao from './components/RelatorioImportacao';
import {
  TURNOS, interpretarTempoPorParada, podeExecutar, textoDeConfirmacao, textoDosSetores, avisosOrdenados, distanciasEmLinhaReta, formatarMinutos,
  MSG_ESCOLHA_O_TURNO, TEMPO_POR_PARADA_PADRAO_MIN
} from './services/roteirizacao';
import {
  pedidosParaRoteirizar, pedidoParaRoteirizacao, idsSemEndereco, corrigirEndereco, contarMarcados, avisoAntesDeExecutar, MSG_ERRO_ENDERECO
} from './services/pedidos';
import { interpretarRaio, nomeDoHub, RAIO_PADRAO_KM } from './services/lojas';
import { API_BASE } from './config';
import { instalarTratamento401, MENSAGEM_SESSAO_EXPIRADA } from './services/sessao';
import { baixarBlob } from './services/download';
import {
  MSG_MARQUE_MOTORISTA, textoRotasEMotoristas, linhaDeConfirmacao, linhaDeDesfazer,
  rotasPorMotoristaDoResultado, manterSomenteAtivos, motoristasMarcados, podeExecutarComMotoristas
} from './services/selecaoMotoristas';

// Instância dedicada que anexa automaticamente o token do operador logado
// (Etapa 1 — Autenticação) em toda chamada ao backend, para que qualquer
// rota protegida no futuro já funcione sem mudanças adicionais aqui.
const apiAuth = axios.create({ baseURL: API_BASE });
apiAuth.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default function App() {
  // Operador logado (Etapa 1 — Autenticação). Recupera do localStorage
  // para manter a sessão entre recarregamentos de página.
  const [operador, setOperador] = useState(() => {
    try {
      const salvo = localStorage.getItem('operador');
      return salvo ? JSON.parse(salvo) : null;
    } catch {
      return null;
    }
  });

  const [avisoLogin, setAvisoLogin] = useState('');

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('operador');
    setOperador(null);
  };

  // Qualquer resposta 401 (sessão vencida ou inválida) devolve o operador à tela de login, com um aviso curto.
  const sessaoExpiradaRef = useRef(null);
  useEffect(() => {
    sessaoExpiradaRef.current = () => {
      handleLogout();
      setAvisoLogin(MENSAGEM_SESSAO_EXPIRADA);
    };
  });
  useEffect(() => {
    const id = instalarTratamento401(apiAuth, () => sessaoExpiradaRef.current());
    return () => apiAuth.interceptors.response.eject(id);
  }, []);

  const [loading, setLoading] = useState(false);
  const [mostrarPesos, setMostrarPesos] = useState(false);
  const [mostrarMotoristas, setMostrarMotoristas] = useState(false);
  const [mostrarLojas, setMostrarLojas] = useState(false);
  // Lojas ativas (mapa permanente), hub escolhido ('' = nenhum, 'outro' = "Outro endereço", ou o id da loja) e raio do "Raio X km".
  const [lojas, setLojas] = useState([]);
  const [lojasCarregadas, setLojasCarregadas] = useState(false);
  const [selecaoHub, setSelecaoHub] = useState('');
  const [raioTexto, setRaioTexto] = useState(String(RAIO_PADRAO_KM));
  // Cada escolha de loja (na lista ou clicando no mapa) pede para o mapa centralizar nela: { n, lat, lng }
  const [focoMapa, setFocoMapa] = useState(null);
  const [loadingCeps, setLoadingCeps] = useState(false);
  const [dadosCoberturaCeps, setDadosCoberturaCeps] = useState(null);
  const [progresso, setProgresso] = useState(null); // { etapa, atual, total } | null
  // Turno ESCOLHIDO À MÃO pelo operador (nunca inferido do relógio) e tempo parado em cada entrega.
  const [turno, setTurno] = useState('');
  const [tempoPorParada, setTempoPorParada] = useState(String(TEMPO_POR_PARADA_PADRAO_MIN));

  // Painel de Configuração de Capacidades Variáveis por Loja
  const [mostrarConfigModais, setMostrarConfigModais] = useState(false);
  const [modais, setModais] = useState({
    'Carro de passeio': { capacidade: 5 },
    'Fiorino/Utilitário': { capacidade: 12 }
  });

  // Motoristas ATIVOS do cadastro (tela "Motoristas e veículos"), quantas rotas cada um fez hoje e quais foram marcados
  // para esta roteirização: só os marcados entram nas rotas. Marcar não ativa nem desativa ninguém.
  const [motoristas, setMotoristas] = useState([]);
  const [rotasHoje, setRotasHoje] = useState({});
  const [selecionados, setSelecionados] = useState([]);
  const [frotaCarregada, setFrotaCarregada] = useState(false);
  // Confirmação das rotas do resultado: { confirmada, linhas, enviando, erro }
  const [confirmacao, setConfirmacao] = useState({ confirmada: false, linhas: [], enviando: false, erro: '' });

  // Sem o cadastro a roteirização avisa o operador na hora de gerar as rotas.
  const carregarFrota = useCallback(() => Promise.all([
    apiAuth.get('/motoristas', { params: { incluir_inativos: false } }),
    apiAuth.get('/rotas-realizadas/hoje').catch(() => ({ data: { por_motorista: {} } }))
  ]).then(([respMotoristas, respHoje]) => {
    setMotoristas(respMotoristas.data);
    setRotasHoje(respHoje.data.por_motorista || {});
    setSelecionados((atuais) => manterSomenteAtivos(atuais, respMotoristas.data));
  }).catch(() => {}).finally(() => setFrotaCarregada(true)), []);

  useEffect(() => {
    if (operador) carregarFrota();
  }, [operador, carregarFrota]);

  // Hub Operacional
  const [origem, setOrigem] = useState({
    rua: '',
    numero: '',
    bairro: '',
    cep: ''
  });

  // Lojas ativas para o mapa permanente e a escolha do hub.
  const carregarLojas = useCallback(() => apiAuth.get('/lojas', { params: { incluir_inativas: false } })
    .then((resp) => {
      setLojas(resp.data);
      // loja que foi desativada (ou sumiu) deixa de ser o hub escolhido
      setSelecaoHub((atual) => (/^\d+$/.test(atual) && !resp.data.some((l) => String(l.id) === atual) ? '' : atual));
    })
    .catch(() => {})
    .finally(() => setLojasCarregadas(true)), []);

  useEffect(() => {
    if (operador) carregarLojas();
  }, [operador, carregarLojas]);

  const lojaHubId = /^\d+$/.test(selecaoHub) ? Number(selecaoHub) : null;
  const lojaHub = lojas.find((l) => l.id === lojaHubId) || null;
  // Sem nenhuma loja cadastrada, o endereço livre aparece sozinho; com lojas, só em "Outro endereço".
  const modoEndereco = selecaoHub === 'outro' || (lojasCarregadas && lojas.length === 0);
  const hubDefinido = lojaHubId !== null || (modoEndereco && Boolean(origem.rua));

  // Lista de Múltiplos Arquivos/Lotes de Pedidos
  // Cada lote: { id, nome, pedidos, marcados (Set de ids), comErro (Set de ids sem endereço localizado) }. Só vive na memória.
  const [lotes, setLotes] = useState([]);
  const [loteAtivoId, setLoteAtivoId] = useState(null);
  const [resultado, setResultado] = useState(null);
  const [relatorioPendente, setRelatorioPendente] = useState(null); // { nome, relatorio } à espera de o operador aceitar

  const loteSelecionado = lotes.find(l => l.id === loteAtivoId);
  // Só os pedidos MARCADOS, da loja escolhida e sem erro de endereço, entram na roteirização. A data de entrega nunca filtra.
  const pedidosAtivos = loteSelecionado
    ? pedidosParaRoteirizar(loteSelecionado.pedidos, loteSelecionado.marcados, { lojaId: lojaHubId, comErro: loteSelecionado.comErro })
    : [];
  const marcadosForaDoFiltro = loteSelecionado
    ? contarMarcados(loteSelecionado.pedidos, loteSelecionado.marcados, { lojaId: lojaHubId, comErro: loteSelecionado.comErro }).foraDoFiltro
    : 0;

  const alterarLote = (id, mudanca) => setLotes((prev) => prev.map((l) => (l.id === id ? { ...l, ...(typeof mudanca === 'function' ? mudanca(l) : mudanca) } : l)));

  // Capacidade por Viagem Simultânea: só dos motoristas marcados
  const marcados = motoristasMarcados(motoristas, selecionados);
  const capacidadeSimultaneaFrota = capacityCheck(modais, marcados);

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

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    try {
      setLoading(true);
      // Valida linha a linha e devolve o relatório; o lote só entra depois de o operador aceitar (só as válidas).
      const res = await apiAuth.post(`/pedidos/validar`, formData);
      setRelatorioPendente({ nome: file.name, relatorio: res.data });
    } catch (err) {
      if (err?.response?.status === 401) return; // já voltou para o login, com o aviso
      const detalhe = err?.response?.data?.detail;
      alert((typeof detalhe === 'string' && detalhe) || 'Erro ao importar arquivo. Certifique-se de que é uma planilha válida (.csv ou .xlsx).');
    } finally {
      setLoading(false);
      e.target.value = '';
    }
  };

  const aceitarLote = () => {
    const { nome, relatorio } = relatorioPendente;
    const novoLote = {
      id: Date.now(),
      nome,
      pedidos: relatorio.pedidos,
      marcados: new Set(relatorio.pedidos.map((p) => p.id)),
      comErro: new Set(),
      dataUpload: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    setLotes(prev => [...prev, novoLote]);
    setLoteAtivoId(novoLote.id);
    setRelatorioPendente(null);
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

  // 1. Cobertura de CEPs até o raio escolhido ("Raio X km"). Com loja escolhida usa a coordenada cadastrada dela (sem
  //    geocodificar o endereço); em "Outro endereço" vale o endereço digitado, como antes.
  const consultarCoberturaCeps = async (idDaLoja = lojaHubId) => {
    const raio = interpretarRaio(raioTexto);
    if (!raio.ok) {
      alert(raio.mensagem);
      return;
    }
    if (idDaLoja === null && !origem.rua && !origem.cep) {
      alert('Escolha uma loja ou informe o endereço do hub.');
      return;
    }

    setLoadingCeps(true);
    try {
      const corpo = idDaLoja !== null
        ? { loja_id: idDaLoja, raio_km: raio.valor }
        : {
          origem_rua: origem.rua || "Centro Operacional",
          origem_num: origem.numero || "S/N",
          origem_cep: origem.cep || "",
          origem_bairro: origem.bairro || "",
          raio_km: raio.valor
        };
      const res = await apiAuth.post(`/cobertura-ceps`, corpo);
      setDadosCoberturaCeps(res.data);
    } catch (err) {
      if (err?.response?.status === 401) return; // já voltou para o login, com o aviso
      const detalhe = err?.response?.data?.detail;
      alert((typeof detalhe === 'string' && detalhe) || 'Não foi possível calcular a cobertura de CEPs. Verifique sua conexão e tente de novo.');
    } finally {
      setLoadingCeps(false);
    }
  };

  // Escolher a loja (pelo seletor ou clicando no marcador do mapa): vira o hub e recalcula a cobertura e as faixas de CEP.
  const escolherLoja = (id) => {
    const alvo = lojas.find((l) => l.id === id);
    if (alvo) setFocoMapa((atual) => ({ n: (atual?.n ?? 0) + 1, lat: alvo.lat, lng: alvo.lng }));
    if (id === lojaHubId) return;
    if (resultado && !confirmacao.confirmada
      && !window.confirm('Trocar a loja descarta as rotas calculadas que ainda não foram confirmadas. Continuar?')) {
      return;
    }
    setResultado(null);
    setConfirmacao({ confirmada: false, linhas: [], enviando: false, erro: '' });
    setDadosCoberturaCeps(null);
    setSelecaoHub(String(id));
    consultarCoberturaCeps(id);
  };

  const trocarSelecaoHub = (valor) => {
    if (valor !== '' && valor !== 'outro') {
      escolherLoja(Number(valor));
      return;
    }
    if (valor === selecaoHub) return;
    if (resultado && !confirmacao.confirmada
      && !window.confirm('Trocar o ponto de partida descarta as rotas calculadas que ainda não foram confirmadas. Continuar?')) {
      return;
    }
    setResultado(null);
    setConfirmacao({ confirmada: false, linhas: [], enviando: false, erro: '' });
    setDadosCoberturaCeps(null);
    setSelecaoHub(valor);
  };

  const handleOtimizar = async () => {
    if (lojaHubId === null && !origem.rua && !origem.cep) {
      alert('Escolha uma loja ou informe o endereço do hub antes de gerar as rotas.');
      return;
    }
    if (pedidosAtivos.length === 0) {
      alert('Marque pelo menos um pedido na lista (da loja escolhida) antes de gerar as rotas.');
      return;
    }

    if (frotaCarregada && motoristas.length === 0) {
      alert('Não há motoristas ativos. Cadastre ou ative pelo menos um motorista em "Motoristas e veículos" antes de gerar as rotas.');
      setMostrarMotoristas(true);
      return;
    }

    if (!podeExecutarComMotoristas(selecionados)) {
      alert(MSG_MARQUE_MOTORISTA);
      return;
    }

    if (!turno) {
      alert(MSG_ESCOLHA_O_TURNO);
      return;
    }
    const tempo = interpretarTempoPorParada(tempoPorParada);
    if (!tempo.ok) {
      alert(tempo.mensagem);
      return;
    }

    // Aviso curto: marcados de outra loja não entram nas rotas desta loja.
    const aviso = avisoAntesDeExecutar(marcadosForaDoFiltro);
    if (aviso && !window.confirm(aviso)) return;
    // Confirmação curta antes de rodar.
    if (!window.confirm(textoDeConfirmacao({ turno, loja: lojaHub?.nome, pedidos: pedidosAtivos.length, motoristas: selecionados.length }))) return;

    setLoading(true);
    setProgresso({ etapa: 'Iniciando...', atual: 0, total: pedidosAtivos.length });
    const loteDaExecucao = loteAtivoId;

    try {
      // 1. Inicia o job em segundo plano — a resposta chega na hora, com um job_id.
      const inicio = await apiAuth.post(`/otimizar`, {
        ...(lojaHubId !== null
          ? { loja_id: lojaHubId }
          : { origem_rua: origem.rua, origem_num: origem.numero, origem_bairro: origem.bairro, origem_cep: origem.cep }),
        modais_config: modais,
        motorista_ids: selecionados,
        turno,
        tempo_por_parada_min: tempo.valor,
        pedidos: pedidosAtivos.map(pedidoParaRoteirizacao)
      });

      const jobId = inicio.data.job_id;

      // 2. Consulta o andamento a cada 1.2s até o job terminar (ou dar erro).
      await new Promise((resolve, reject) => {
        const intervalo = setInterval(async () => {
          try {
            const status = await apiAuth.get(`/otimizar/status/${jobId}`);
            const dados = status.data;

            setProgresso({ etapa: dados.etapa, atual: dados.atual, total: dados.total });

            if (dados.status === 'concluido') {
              clearInterval(intervalo);
              setResultado(dados.resultado);
              // pedido cujo endereço não foi localizado sai da seleção e fica travado na lista até ser corrigido
              const semEndereco = idsSemEndereco(dados.resultado);
              if (semEndereco.size > 0) {
                alterarLote(loteDaExecucao, (l) => ({
                  comErro: new Set([...l.comErro, ...semEndereco]),
                  marcados: new Set([...l.marcados].filter((id) => !semEndereco.has(id)))
                }));
              }
              setConfirmacao({ confirmada: false, linhas: [], enviando: false, erro: '' });
              resolve();
            } else if (dados.status === 'erro') {
              clearInterval(intervalo);
              reject(new Error(dados.erro || 'Erro desconhecido na roteirização.'));
            }
          } catch (errPolling) {
            clearInterval(intervalo);
            reject(errPolling);
          }
        }, 1200);
      });
    } catch (err) {
      if (err?.response?.status === 401) return; // já voltou para o login, com o aviso
      const detalhe = err?.response?.data?.detail;
      alert((typeof detalhe === 'string' && detalhe) || err?.message || 'Não foi possível gerar as rotas. Verifique os endereços informados e tente de novo.');
    } finally {
      setLoading(false);
      setProgresso(null);
    }
  };

  // Confirma as rotas do resultado: uma rota por viagem, no nome do motorista de cada rota. Repetir não duplica.
  const confirmarRotas = async () => {
    if (!resultado?.execucao_id) return;
    setConfirmacao((c) => ({ ...c, enviando: true, erro: '' }));
    try {
      const { data } = await apiAuth.post('/rotas-realizadas/confirmar', { execucao_id: resultado.execucao_id });
      setConfirmacao({
        confirmada: true,
        linhas: data.motoristas.map((m) => linhaDeConfirmacao(m.nome, m.nesta_execucao, m.total_hoje)),
        enviando: false,
        erro: ''
      });
      carregarFrota();
    } catch (err) {
      if (err?.response?.status === 401) return; // já voltou para o login, com o aviso
      const detalhe = err?.response?.data?.detail;
      setConfirmacao((c) => ({ ...c, enviando: false, erro: (typeof detalhe === 'string' && detalhe) || 'Não foi possível confirmar as rotas agora. Tente de novo.' }));
    }
  };

  const desfazerConfirmacao = async () => {
    if (!resultado?.execucao_id) return;
    setConfirmacao((c) => ({ ...c, enviando: true, erro: '' }));
    try {
      const { data } = await apiAuth.post(`/rotas-realizadas/${encodeURIComponent(resultado.execucao_id)}/desfazer`);
      setConfirmacao({
        confirmada: false,
        linhas: data.motoristas.map((m) => linhaDeDesfazer(m.nome, m.total_hoje)),
        enviando: false,
        erro: ''
      });
      carregarFrota();
    } catch (err) {
      if (err?.response?.status === 401) return;
      const detalhe = err?.response?.data?.detail;
      setConfirmacao((c) => ({ ...c, enviando: false, erro: (typeof detalhe === 'string' && detalhe) || 'Não foi possível desfazer a confirmação agora. Tente de novo.' }));
    }
  };

  // Modelo padrão de pedidos em CSV (o mesmo do XLSX, mantido pelo servidor).
  const baixarPlanilhaModelo = async () => {
    try {
      const resposta = await apiAuth.get('/modelo-csv', { responseType: 'blob' });
      baixarBlob(resposta.data, 'modelo_pedidos_zubale.csv');
    } catch (err) {
      if (err?.response?.status === 401) return; // já voltou para o login, com o aviso
      alert('Não foi possível baixar o modelo agora. Tente novamente.');
    }
  };

  const baixarModeloXLSX = async () => {
    try {
      const resposta = await apiAuth.get('/modelo-xlsx', { responseType: 'blob' });
      baixarBlob(resposta.data, 'modelo_pedidos_zubale.xlsx');
    } catch (err) {
      if (err?.response?.status === 401) return; // já voltou para o login, com o aviso
      alert('Não foi possível baixar o modelo agora. Tente novamente.');
    }
  };

  // 1. Exportação em CSV Simples
  const exportarTabelaCsv = () => {
    if (!dadosCoberturaCeps || !dadosCoberturaCeps.pontos_cobertos || dadosCoberturaCeps.pontos_cobertos.length === 0) {
      alert('Calcule a cobertura no raio de 30 km primeiro.');
      return;
    }

    let csvContent = "data:text/csv;charset=utf-8,Codigo IBGE,UF,Cidade,Regiao_Bairro,Faixa Precificacao,CEP Inicial,CEP Final,Prazo Dias,Distancia KM,Cobertura\n";

    dadosCoberturaCeps.pontos_cobertos.forEach((p) => {
      const ibge = p.ibge || dadosCoberturaCeps.hub?.ibge || "";
      const uf = p.uf || dadosCoberturaCeps.hub?.uf || "";
      const cidade = p.cidade || dadosCoberturaCeps.hub?.cidade || "";
      const bairro = p.bairro || "Área Atendida";
      const cepIni = p.cep_inicial || "";
      const cepFim = p.cep_final || "";
      const prazo = p.dias_sla || (p.distancia_km <= 12 ? 1 : 2);
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
        dist,
        `"${p.cobertura || ""}"`
      ].join(',');
      csvContent += linha + "\n";
    });

    // Legenda e fonte no fim do arquivo (depois de uma linha em branco), como na aba "Cobertura e fonte" do XLSX.
    if (dadosCoberturaCeps.legenda_cobertura) {
      csvContent += `\n"${dadosCoberturaCeps.legenda_cobertura}"\n`;
    }
    if (dadosCoberturaCeps.fonte) {
      csvContent += `"${dadosCoberturaCeps.fonte}"\n`;
    }

    const nomeHubLimpo = nomeDoHub(lojaHub, origem, dadosCoberturaCeps.hub?.cidade)
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
      .replace(/[^a-z0-9]/g, '_').replace(/_+/g, '_').slice(0, 30);
    const numHubLimpo = !lojaHub && origem.numero ? `_${origem.numero}` : '';
    const dataAtual = new Date().toISOString().slice(0, 10);
    const nomeArquivo = `tabela_frete_${nomeHubLimpo}${numHubLimpo}_${dataAtual}.csv`;

    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', encodeURI(csvContent));
    downloadAnchor.setAttribute('download', nomeArquivo);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  // 2. Exportação em XLSX Completo (63 colunas)
  const exportarTabelaXlsx = async () => {
    if (!dadosCoberturaCeps || !dadosCoberturaCeps.pontos_cobertos || dadosCoberturaCeps.pontos_cobertos.length === 0) {
      alert('Calcule a cobertura no raio de 30 km primeiro.');
      return;
    }

    try {
      const response = await apiAuth.post(`/exportar-tabela-frete-xlsx`, {
        hub: dadosCoberturaCeps.hub,
        pontos_cobertos: dadosCoberturaCeps.pontos_cobertos
      }, { responseType: 'blob' });

      const nomeHubLimpo = nomeDoHub(lojaHub, origem, dadosCoberturaCeps.hub?.cidade)
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
        .replace(/[^a-z0-9]/g, '_').replace(/_+/g, '_').slice(0, 30);
      const numHubLimpo = !lojaHub && origem.numero ? `_${origem.numero}` : '';
      const dataAtual = new Date().toISOString().slice(0, 10);
      const nomeArquivo = `tabela_frete_completa_${nomeHubLimpo}${numHubLimpo}_${dataAtual}.xlsx`;

      baixarBlob(new Blob([response.data]), nomeArquivo);
    } catch (err) {
      if (err?.response?.status === 401) return; // já voltou para o login, com o aviso
      alert('Erro ao gerar planilha Excel completa.');
    }
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

  // Etapa 1 — Autenticação: sem operador logado, não renderiza o app,
  // mostra a tela de login/cadastro (já com fundo de tela cheia).
  if (!operador) {
    return <Login aviso={avisoLogin} onLoginSuccess={(op) => { setAvisoLogin(''); setOperador(op); }} />;
  }

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
          <div className="flex items-center gap-2 pl-3 border-l border-slate-800">
            <button
              onClick={() => setMostrarLojas(true)}
              className="flex items-center gap-1 text-[10px] font-semibold text-blue-300 hover:text-blue-200 bg-blue-500/10 border border-blue-500/20 px-2 py-1 rounded transition-colors"
              title="Cadastrar e editar as lojas"
            >
              <Store className="w-3 h-3" /> Lojas
            </button>
            <button
              onClick={() => setMostrarMotoristas(true)}
              className="flex items-center gap-1 text-[10px] font-semibold text-blue-300 hover:text-blue-200 bg-blue-500/10 border border-blue-500/20 px-2 py-1 rounded transition-colors"
              title="Cadastrar motoristas e ajustar o valor base dos veículos"
            >
              <Users className="w-3 h-3" /> Motoristas
            </button>
            <button
              onClick={() => setMostrarPesos(true)}
              className="flex items-center gap-1 text-[10px] font-semibold text-blue-300 hover:text-blue-200 bg-blue-500/10 border border-blue-500/20 px-2 py-1 rounded transition-colors"
              title="Conferir e editar o peso dos itens"
            >
              <Scale className="w-3 h-3" /> Pesos dos itens
            </button>
            <span className="text-slate-300 font-sans">{operador.nome}</span>
            <button
              onClick={handleLogout}
              className="text-[10px] font-semibold text-red-400 hover:text-red-300 bg-red-500/10 border border-red-500/20 px-2 py-1 rounded transition-colors"
            >
              Sair
            </button>
          </div>
        </div>
      </header>

      {relatorioPendente && (
        <RelatorioImportacao
          nomeArquivo={relatorioPendente.nome}
          relatorio={relatorioPendente.relatorio}
          onAceitar={aceitarLote}
          onCancelar={() => setRelatorioPendente(null)}
        />
      )}
      {mostrarLojas && (
        <Lojas api={apiAuth} onFechar={() => setMostrarLojas(false)} onMudou={carregarLojas} />
      )}

      {mostrarMotoristas && (
        <Motoristas api={apiAuth} onFechar={() => setMostrarMotoristas(false)} onMudou={carregarFrota} />
      )}

      {mostrarPesos && (
        <PesosItens api={apiAuth} onFechar={() => setMostrarPesos(false)} onSessaoExpirada={handleLogout} />
      )}

      {/* Espaço de Trabalho */}
      <div className="flex-1 flex flex-col lg:flex-row">

        {/* Painel Lateral */}
        <aside className="w-full lg:w-[420px] border-r border-slate-800/80 bg-slate-900/30 p-6 flex flex-col gap-6 backdrop-blur-sm overflow-y-auto">

          {/* 1. Hub / Loja Central: loja cadastrada (clique no mapa ou seletor) ou "Outro endereço" */}
          <div className="space-y-3">
            <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
              <MapPin className="w-3.5 h-3.5 text-blue-400" /> Loja Central / Hub de Origem
            </span>

            {lojas.length > 0 && (
              <SeletorLoja
                lojas={lojas}
                selecaoHub={selecaoHub}
                onEscolherLoja={escolherLoja}
                onOutroEndereco={() => trocarSelecaoHub('outro')}
              />
            )}

            {/* Raio X km: ao lado do nome da loja escolhida */}
            {(lojaHub || modoEndereco) && (
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-semibold text-slate-200 truncate" title={lojaHub?.nome || 'Outro endereço'}>
                  {lojaHub ? lojaHub.nome : 'Outro endereço'}
                </span>
                <div className="flex items-center gap-1.5 shrink-0">
                  <input
                    type="text"
                    inputMode="decimal"
                    value={raioTexto}
                    onChange={(e) => setRaioTexto(e.target.value)}
                    aria-label="Raio em km"
                    title="Raio da consulta, em km (de 1 a 200; padrão 30)"
                    className="w-14 text-[11px] text-center bg-slate-900/90 border border-slate-800 focus:border-emerald-500/60 rounded px-1.5 py-1 text-slate-100 focus:outline-none"
                  />
                  <button
                    onClick={() => consultarCoberturaCeps()}
                    disabled={loadingCeps || !hubDefinido}
                    className="text-[10px] font-semibold text-emerald-400 hover:text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 px-2 py-1 rounded transition-colors flex items-center gap-1 disabled:opacity-40"
                    title="Consultar as faixas de CEP até o raio escolhido"
                  >
                    {loadingCeps ? <Loader2 className="w-3 h-3 animate-spin" /> : <Compass className="w-3 h-3" />}
                    Raio X km
                  </button>
                </div>
              </div>
            )}

            {lojaHub && lojaHub.endereco && <p className="text-[11px] text-slate-500 truncate">{lojaHub.endereco}</p>}

            {modoEndereco && (
              <>
                <input
                  type="text"
                  value={origem.rua}
                  onChange={(e) => setOrigem({ ...origem, rua: e.target.value })}
                  placeholder="Logradouro (ex: Av. Paulista)"
                  className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2.5 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
                />
                <div className="grid grid-cols-2 gap-2">
                  <input
                    type="text"
                    value={origem.numero}
                    onChange={(e) => setOrigem({ ...origem, numero: e.target.value })}
                    placeholder="Número (ex: 1000)"
                    className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
                  />
                  <input
                    type="text"
                    value={origem.cep}
                    onChange={(e) => setOrigem({ ...origem, cep: e.target.value })}
                    placeholder="CEP (ex: 01310-100)"
                    className="w-full text-xs bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors"
                  />
                </div>
              </>
            )}

            {lojasCarregadas && lojas.length > 0 && !lojaHub && !modoEndereco && (
              <p className="text-[11px] text-slate-500">Clique numa loja no mapa ou escolha na lista para definir o ponto de partida e ver as faixas de CEP.</p>
            )}

            {/* Aviso explícito quando não há faixas de CEP reais cadastradas nesse raio
                (Etapa 2: o gerador sintético de 48 pontos foi removido — não inventamos
                mais CEPs fictícios para preencher esse painel). */}
            {dadosCoberturaCeps && dadosCoberturaCeps.aviso_ibge && (
              <div className="p-2.5 rounded-lg bg-amber-950/30 border border-amber-500/30 text-[11px] flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                <span className="text-amber-300">{dadosCoberturaCeps.aviso_ibge}</span>
              </div>
            )}
            {dadosCoberturaCeps && dadosCoberturaCeps.aviso && (
              <div className="p-2.5 rounded-lg bg-amber-950/30 border border-amber-500/30 text-[11px] flex items-start gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                <span className="text-amber-300">{dadosCoberturaCeps.aviso}</span>
              </div>
            )}

            {/* Painel Informativo da Consulta de Raio 30km com 2 Botões Lado a Lado */}
            {dadosCoberturaCeps && dadosCoberturaCeps.total_pontos > 0 && (
              <div className="p-2.5 rounded-lg bg-emerald-950/30 border border-emerald-500/30 text-[11px] space-y-2">
                <div className="flex justify-between items-center text-emerald-400 font-bold">
                  <span>Cobertura no raio:</span>
                  <span>{dadosCoberturaCeps.total_pontos} faixas de CEP em {dadosCoberturaCeps.raio_limite_km} km</span>
                </div>
                {dadosCoberturaCeps.resumo_cobertura && (
                  <div className="flex justify-between items-center text-emerald-300 font-semibold">
                    <span>Cobertura Total: {dadosCoberturaCeps.resumo_cobertura.total}</span>
                    <span className="text-amber-300">Parcial: {dadosCoberturaCeps.resumo_cobertura.parcial}</span>
                  </div>
                )}
                {dadosCoberturaCeps.legenda_cobertura && (
                  <p className="text-[10px] leading-snug text-slate-400">{dadosCoberturaCeps.legenda_cobertura}</p>
                )}
                {dadosCoberturaCeps.fonte && (
                  <p className="text-[10px] text-slate-500 italic">{dadosCoberturaCeps.fonte}</p>
                )}
                <div className="grid grid-cols-2 gap-2 pt-1">
                  <button
                    onClick={exportarTabelaCsv}
                    className="py-1.5 px-2 bg-slate-900 hover:bg-slate-800 text-emerald-400 border border-emerald-500/30 rounded font-semibold text-[10px] flex items-center justify-center gap-1 transition-colors"
                    title="Baixar CSV com colunas essenciais"
                  >
                    <FileDown className="w-3 h-3" /> Tabela CSV (Simples)
                  </button>
                  <button
                    onClick={exportarTabelaXlsx}
                    className="py-1.5 px-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-semibold text-[10px] flex items-center justify-center gap-1 transition-colors shadow-sm"
                    title="Baixar Excel (.xlsx) completo com 63 colunas"
                  >
                    <TableIcon className="w-3 h-3" /> Tabela XLSX (Completa)
                  </button>
                </div>
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
              <span className="text-[10px] text-slate-500">Use o modelo padrão (.csv ou .xlsx); você confere o arquivo antes de aceitar</span>
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
                      className={`flex items-center justify-between p-2.5 rounded-lg cursor-pointer border transition-all ${ativo
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
              <span className="text-slate-400">Pedidos marcados:</span>
              <span className={`font-mono font-semibold ${pedidosAtivos.length > 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                {pedidosAtivos.length} pedidos
              </span>
            </div>

            {loteSelecionado && (
              <ListaPedidos
                key={loteSelecionado.id}
                pedidos={loteSelecionado.pedidos}
                marcados={loteSelecionado.marcados}
                comErro={loteSelecionado.comErro}
                lojaId={lojaHubId}
                lojaNome={lojaHub?.nome}
                aoMudarMarcados={(marcados) => alterarLote(loteSelecionado.id, { marcados })}
                aoCorrigir={(id, campos) => alterarLote(loteSelecionado.id, (l) => {
                  const corrigido = corrigirEndereco(l.pedidos, l.comErro, id, campos);
                  return { pedidos: corrigido.pedidos, comErro: corrigido.comErro, marcados: new Set([...l.marcados, id]) };
                })}
              />
            )}
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

          {/* 4. Motoristas da roteirização: escolha múltipla entre os ATIVOS; só os marcados entram nas rotas */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-blue-400" /> Motoristas ({selecionados.length} de {motoristas.length} marcados)
              </span>
              <button
                onClick={() => setMostrarMotoristas(true)}
                className="flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 font-semibold px-2 py-1 rounded bg-blue-500/10 border border-blue-500/20 transition-colors"
              >
                <Settings className="w-3 h-3" /> Gerenciar
              </button>
            </div>

            {frotaCarregada && motoristas.length === 0 ? (
              <div className="p-2.5 rounded-lg bg-amber-950/30 border border-amber-500/30 text-[11px] text-amber-300 flex items-start gap-2">
                <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <span>Não há motoristas ativos. Cadastre ou ative pelo menos um em "Gerenciar" para poder gerar as rotas.</span>
              </div>
            ) : (
              <>
                <SeletorMotoristas
                  motoristas={motoristas}
                  lojaId={lojaHubId}
                  rotasHoje={rotasHoje}
                  selecionados={selecionados}
                  onMudar={setSelecionados}
                />

                <div className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-[11px] space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Capacidade por Saída Simultânea:</span>
                    <span className="font-mono font-bold text-slate-200">
                      {capacidadeSimultaneaFrota} pedidos / onda
                    </span>
                  </div>
                  {pedidosAtivos.length > capacidadeSimultaneaFrota && capacidadeSimultaneaFrota > 0 && (
                    <div className="flex items-center gap-1.5 text-blue-400 text-[10px] pt-1 border-t border-slate-800/80">
                      <Layers className="w-3.5 h-3.5 shrink-0" />
                      <span>Demanda maior que a frota: o sistema gerará <b>múltiplas viagens/ondas</b> por motorista.</span>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Botão de Execução + Barra de Progresso */}
          <div className="mt-auto space-y-2">
            {progresso && (
              <div className="space-y-1.5">
                <div className="flex justify-between items-center text-[10px] text-slate-400 font-mono">
                  <span className="truncate pr-2">{progresso.etapa}</span>
                  <span className="shrink-0">{progresso.atual}/{progresso.total}</span>
                </div>
                <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-blue-500 transition-all duration-300 ease-out rounded-full"
                    style={{
                      width: `${progresso.total > 0 ? Math.min(100, (progresso.atual / progresso.total) * 100) : 0}%`
                    }}
                  />
                </div>
              </div>
            )}
            <div className="space-y-1.5 p-2.5 rounded-lg bg-slate-950/60 border border-slate-800">
              <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Turno (escolha obrigatória)</p>
              <div className="flex rounded-lg overflow-hidden border border-slate-700 text-xs font-semibold" role="radiogroup" aria-label="Turno">
                {TURNOS.map((t) => (
                  <button key={t.valor} type="button" role="radio" aria-checked={turno === t.valor} onClick={() => setTurno(t.valor)}
                    className={`flex-1 px-2 py-1.5 ${turno === t.valor ? 'bg-blue-600 text-white' : 'bg-slate-900 text-slate-300 hover:bg-slate-800'}`}>
                    {t.rotulo} <span className="block text-[9px] font-normal opacity-70">{t.janela}</span>
                  </button>
                ))}
              </div>
              <label className="flex items-center justify-between gap-2 text-[11px] text-slate-400">
                Tempo por parada (min)
                <input type="text" inputMode="numeric" value={tempoPorParada} onChange={(e) => setTempoPorParada(e.target.value)} aria-label="Tempo por parada em minutos"
                  className="w-16 px-2 py-1 rounded bg-slate-950 border border-slate-700 text-slate-100 text-xs font-mono text-right focus:outline-none focus:border-blue-500" />
              </label>
            </div>
            <button
              onClick={handleOtimizar}
              disabled={loading || !podeExecutar({ hubDefinido, pedidos: pedidosAtivos.length, motoristas: selecionados.length, turno, tempoPorParada }).ok}
              className="w-full py-3.5 bg-blue-600 hover:bg-blue-500 active:scale-[0.99] transition-all rounded-xl font-bold text-xs flex items-center justify-center gap-2 shadow-lg shadow-blue-600/25 text-white disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4 fill-current" />}
              {loading ? (progresso ? progresso.etapa : 'Agrupando Polígonos & Otimizando...') : 'Executar Roteirização'}
            </button>
            {!loading && !turno && pedidosAtivos.length > 0 && hubDefinido && podeExecutarComMotoristas(selecionados) && (
              <p className="flex items-center gap-1.5 text-[11px] text-amber-300">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" /> {MSG_ESCOLHA_O_TURNO}
              </p>
            )}
            {frotaCarregada && motoristas.length > 0 && !podeExecutarComMotoristas(selecionados) && (
              <p className="flex items-center gap-1.5 text-[11px] text-amber-300">
                <AlertCircle className="w-3.5 h-3.5 shrink-0" /> {MSG_MARQUE_MOTORISTA}
              </p>
            )}
          </div>
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
                {resultado ? (
                  <span className="text-2xl font-black text-white font-mono">
                    {textoRotasEMotoristas(resultado.kpis.total_rotas_viagens, resultado.kpis.total_motoristas ?? resultado.kpis.total_veiculos)}
                  </span>
                ) : (
                  <>
                    <span className="text-2xl font-black text-white font-mono">--</span>
                    <span className="text-xs text-slate-500">
                      {selecionados.length === 1 ? '1 motorista marcado' : `${selecionados.length} motoristas marcados`}
                    </span>
                  </>
                )}
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
                <span className="text-[11px] font-semibold tracking-wider uppercase">Rotas por Motorista</span>
                <Users className="w-4 h-4 text-emerald-400" />
              </div>
              {(() => {
                const nestaRoteirizacao = resultado ? rotasPorMotoristaDoResultado(resultado.rotas) : [];
                const linhas = resultado
                  ? nestaRoteirizacao
                  : marcados.map((m) => ({ motorista_id: m.id, nome: m.nome, rotas: null }));
                if (linhas.length === 0) return <span className="text-2xl font-black text-white font-mono">--</span>;
                return (
                  <div className="space-y-1 max-h-28 overflow-y-auto">
                    {linhas.map((l) => {
                      const hoje = rotasHoje[String(l.motorista_id)] || 0;
                      return (
                        <p key={l.motorista_id} className="text-[11px] text-slate-300 leading-snug">
                          <span className="font-semibold text-white">{l.nome}</span>
                          {l.rotas !== null && <>: {l.rotas === 1 ? '1 rota' : `${l.rotas} rotas`} nesta roteirização</>}
                          <span className="text-slate-500"> • {hoje === 0 ? 'nenhuma rota hoje' : hoje === 1 ? '1 rota realizada hoje' : `${hoje} rotas realizadas hoje`}</span>
                        </p>
                      );
                    })}
                  </div>
                );
              })()}
            </div>
          </div>

          {/* Confirmar rotas: grava uma rota por viagem, no nome do motorista de cada uma. Só as confirmadas contam no "hoje". */}
          {resultado && resultado.execucao_id && (
            <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 space-y-2">
              <div className="flex flex-wrap items-center gap-3">
                {confirmacao.confirmada ? (
                  <button
                    onClick={desfazerConfirmacao}
                    disabled={confirmacao.enviando}
                    className="px-3 py-1.5 rounded-lg border border-amber-500/40 text-amber-300 hover:bg-amber-500/10 text-xs font-semibold disabled:opacity-40"
                  >
                    {confirmacao.enviando ? 'Desfazendo...' : 'Desfazer confirmação'}
                  </button>
                ) : (
                  <button
                    onClick={confirmarRotas}
                    disabled={confirmacao.enviando}
                    className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold disabled:opacity-40"
                  >
                    {confirmacao.enviando ? 'Confirmando...' : 'Confirmar rotas'}
                  </button>
                )}
                <span className="text-[11px] text-slate-400">
                  {confirmacao.confirmada
                    ? 'Rotas confirmadas: elas contam nas rotas de hoje de cada motorista.'
                    : 'Só as rotas confirmadas contam nas rotas realizadas de cada motorista.'}
                </span>
              </div>
              {confirmacao.linhas.length > 0 && (
                <ul className="text-[12px] text-emerald-300 space-y-0.5">
                  {confirmacao.linhas.map((linha) => <li key={linha}>{linha}</li>)}
                </ul>
              )}
              {confirmacao.erro && (
                <p className="flex items-center gap-1.5 text-[11px] text-amber-300"><AlertCircle className="w-3.5 h-3.5 shrink-0" /> {confirmacao.erro}</p>
              )}
            </div>
          )}

          {/* Aviso de pedidos que não puderam ser geocodificados (Etapa 2): ficam de
              fora do cálculo de rotas em vez de serem posicionados num lugar errado. */}
          {resultado && resultado.pedidos_sem_geocodificacao && resultado.pedidos_sem_geocodificacao.length > 0 && (
            <div className="bg-red-950/30 border border-red-500/30 rounded-xl p-4 space-y-2">
              <div className="flex items-center gap-2 text-red-400 font-bold text-xs uppercase tracking-wider">
                <AlertTriangle className="w-4 h-4" />
                {resultado.pedidos_sem_geocodificacao.length} pedido(s) fora da roteirização — {MSG_ERRO_ENDERECO}
              </div>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {resultado.pedidos_sem_geocodificacao.map((p) => (
                  <div key={p.id} className="text-[11px] text-red-300 bg-red-950/40 rounded px-2.5 py-1.5 flex flex-col">
                    <span className="font-semibold">#{p.id} — {p.Endereco || 'Endereço não informado'}, {p.Numero}</span>
                    <span className="text-red-400/80">{p.CEP ? `CEP ${p.CEP} • ` : ''}{p.motivo}</span>
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-red-400/70">Corrija o endereço desses pedidos na lista (botão "Corrigir") e rode a roteirização novamente para incluí-los.</p>
            </div>
          )}

          {/* Avisos da roteirização (Etapa 8): distâncias em linha reta, rotação de região, viagens extras, motoristas sem rota... */}
          {resultado && distanciasEmLinhaReta(resultado) && (
            <p className="flex items-center gap-2 text-[11px] text-amber-300 bg-amber-950/20 border border-amber-500/30 rounded-lg px-3 py-2">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" /> Distâncias e tempos em linha reta (estimativa): não foi possível consultar as ruas.
            </p>
          )}
          {resultado && avisosOrdenados(resultado.avisos).length > 0 && (
            <div className="bg-slate-900/50 border border-slate-800/80 rounded-xl p-4 space-y-1.5" aria-label="Avisos da roteirização">
              <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Avisos</p>
              {avisosOrdenados(resultado.avisos).map((a, i) => (
                <p key={`${a.tipo}-${i}`} className={`text-[11px] rounded px-2.5 py-1.5 ${a.gravidade === 'atencao' ? 'text-amber-200 bg-amber-950/20' : 'text-slate-300 bg-slate-950/50'}`}>
                  {a.mensagem}
                </p>
              ))}
            </div>
          )}

          {/* Visualizador do Mapa */}
          <div className="bg-slate-900/50 border border-slate-800/80 p-4 rounded-xl">
            <div className="flex items-center justify-between mb-3 px-1">
              <div>
                <h3 className="font-bold text-xs uppercase tracking-wider text-slate-200">Polígonos Espaciais & Raio de Cobertura</h3>
                <p className="text-[11px] text-slate-500">Lojas cadastradas, isolinhas de cobertura com cálculo de Haversine e traçado viário OSRM</p>
              </div>
              <span className="text-[10px] font-mono px-2 py-1 bg-slate-900 border border-slate-800 text-slate-400 rounded-md">
                Haversine + Polar VRP
              </span>
            </div>

            <MapaLeaflet
              origem={resultado
                ? resultado.origem
                : (dadosCoberturaCeps
                  ? dadosCoberturaCeps.hub
                  : (lojaHub ? { lat: lojaHub.lat, lon: lojaHub.lng, rua: lojaHub.nome, numero: '' } : null))}
              rotas={resultado ? resultado.rotas : []}
              lojas={lojas}
              lojaSelecionadaId={lojaHubId}
              onEscolherLoja={escolherLoja}
              focoLoja={focoMapa}
              raioKm={interpretarRaio(raioTexto).valor ?? RAIO_PADRAO_KM}
            />
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
                      <th className="p-3.5 font-semibold">Setores</th>
                      <th className="p-3.5 font-semibold">Quilometragem</th>
                      <th className="p-3.5 font-semibold">Tempo</th>
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
                        <td className="p-3.5 text-slate-300 font-sans">
                          <div className="flex items-center gap-2">
                            {r.qtd_pedidos} paradas
                            {(r.paradas || []).some(p => p.geocode_status === 'ALERTA_APROXIMADO') && (
                              <div
                                title="Uma ou mais paradas desta rota têm localização aproximada (só bairro/cidade, não o endereço exato)."
                                className="flex items-center justify-center p-1 bg-amber-500/10 rounded border border-amber-500/20 text-amber-400 cursor-help"
                              >
                                <AlertTriangle className="w-3.5 h-3.5" />
                              </div>
                            )}
                          </div>
                        </td>
                        <td className="p-3.5 text-slate-300 font-sans" title={(r.violacoes_rotacao || []).length ? 'Região em que o motorista já fez rota hoje em outro turno (veja os avisos).' : undefined}>
                          {textoDosSetores(r.setores)}
                          {(r.violacoes_rotacao || []).length > 0 && <AlertTriangle className="inline w-3.5 h-3.5 ml-1 text-amber-400" />}
                        </td>
                        <td className="p-3.5 text-slate-300">
                          <div className="flex items-center gap-2">
                            {r.km_total} km
                            {r.alerta_amplitude && (
                              <div 
                                title={`Rota muito extensa (Amplitude: ${r.amplitude_km}km). Considere adicionar mais veículos.`} 
                                className="flex items-center justify-center p-1 bg-amber-500/10 rounded border border-amber-500/20 text-amber-400 cursor-help"
                              >
                                <AlertTriangle className="w-3.5 h-3.5" />
                              </div>
                            )}
                          </div>
                        </td>
                        <td className="p-3.5 text-slate-400" title={r.tempo_min !== undefined ? `Deslocamento ${formatarMinutos(r.tempo_deslocamento_min)} + paradas ${formatarMinutos(r.tempo_paradas_min)}` : undefined}>{r.tempo_formatado}</td>
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

function capacityCheck(modais, motoristas) {
  return motoristas.reduce((acc, m) => acc + (modais[m.tipo_veiculo]?.capacidade || 0), 0);
}