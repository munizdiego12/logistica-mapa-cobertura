// Romaneio (.csv) da roteirização (Etapa 13): montagem do arquivo na tela, com funções puras. O arquivo NÃO passa pelo servidor.
// As 10 colunas antigas ficam iguais (mesmos nomes e mesma ordem, em ASCII); as novas entram só no fim. Separador vírgula, fim de linha \\n, UTF-8, SEM BOM
// (como o arquivo sempre foi). O nome do cliente vem do lote em memória (pelo id da parada) e só existe no arquivo baixado: nunca vai ao servidor,
// banco, log, console, armazenamento do navegador nem git. Nenhuma coluna de peso. Chegada e janela são ESTIMATIVAS calculadas na tela (Etapa 11).
import { janelaEfetivaDoPedido, minutosParaHora } from './janelas.js';

export const COLUNAS_ANTIGAS = ['Rota', 'Motorista', 'Viagem', 'Veiculo', 'Ordem_Parada', 'Endereco', 'Numero', 'Bairro', 'CEP', 'Volume'];
export const COLUNAS_NOVAS = ['ID_Pedido', 'Cliente', 'Latitude', 'Longitude', 'Chegada_Estimada', 'Janela_Inicio', 'Janela_Fim', 'Fora_do_Prazo'];
export const COLUNAS = [...COLUNAS_ANTIGAS, ...COLUNAS_NOVAS];

const SO_NUMERO = /^[-+]?\d+([.,]\d+)?$/;

/**
 * Texto do operador/lote que o Excel poderia tratar como fórmula (começa com =, +, -, @, tabulação ou retorno de carro) ganha um apóstrofo inicial.
 * Um texto que seja só um número ("-5", "+55") não é alterado.
 */
export function neutralizarFormula(valor) {
  const texto = String(valor ?? '');
  if (!texto) return '';
  if (/^[=@\t\r]/.test(texto)) return `'${texto}`;
  if (/^[-+]/.test(texto) && !SO_NUMERO.test(texto.trim())) return `'${texto}`;
  return texto;
}

/** Campo CSV (RFC 4180): entre aspas quando tem vírgula, aspas, quebra de linha ou espaço nas pontas (ou `sempreAspas`), com as aspas internas duplicadas. */
export function escaparCampo(valor, sempreAspas = false) {
  const texto = String(valor ?? '');
  const precisa = sempreAspas || /[",\n\r]/.test(texto) || texto !== texto.trim();
  return precisa ? `"${texto.replace(/"/g, '""')}"` : texto;
}

const textoSeguro = (valor) => escaparCampo(neutralizarFormula(valor), true);
const horaOuVazio = (minutos) => (minutos === null || minutos === undefined ? '' : minutosParaHora(minutos));
const numeroOuVazio = (valor) => (valor === null || valor === undefined || valor === '' || !Number.isFinite(Number(valor)) ? '' : Number(valor).toFixed(6));

/**
 * Linhas do romaneio (cada uma é a lista de campos já escapados, na ordem de COLUNAS). `rotas`: as rotas efetivas (motorista, veículo e viagem FINAIS, depois das
 * trocas); `pedidos`: o lote da tela (cliente e janela do pedido, por id; pedido fora do lote = vazios); `relatorio`: o de `relatorioDeJanelas` (chegada e
 * fora do prazo por parada); `loja` e `turno`: para a janela da loja quando o pedido não trouxe a dele.
 */
export function linhasDoRomaneio({ rotas, pedidos, relatorio, loja, turno }) {
  const porId = new Map((pedidos ?? []).map((p) => [String(p.id), p]));
  const linhas = [];
  for (const r of rotas ?? []) {
    (r.paradas ?? []).forEach((p, indice) => {
      const pedido = porId.get(String(p.id));
      const calculada = relatorio?.porParada?.[r.id]?.[indice];
      const confere = calculada && calculada.pedidoId === String(p.id) ? calculada : null;
      const janela = janelaEfetivaDoPedido(pedido, loja, turno);
      linhas.push([
        escaparCampo(`Rota ${r.id}`),
        textoSeguro(r.motorista_base || r.motorista),
        escaparCampo(`Viagem ${r.viagem_num || 1}`),
        textoSeguro(r.modal),
        indice + 1,
        textoSeguro(p.Endereco || p.rua || ''),
        textoSeguro(p.Numero || p.numero || ''),
        textoSeguro(p.Bairro || p.bairro || ''),
        textoSeguro(p.CEP || p.cep || ''),
        p.Volume || 1,
        textoSeguro(p.id),
        textoSeguro(pedido?.cliente ?? ''),
        numeroOuVazio(p.lat),
        numeroOuVazio(p.lon),
        escaparCampo(confere ? confere.horaTexto : ''),
        horaOuVazio(janela ? janela.inicio : null),
        horaOuVazio(janela ? janela.fim : null),
        confere ? (confere.fora === true ? 'Sim' : confere.fora === false ? 'Não' : '') : '',
      ]);
    });
  }
  return linhas;
}

/** O arquivo inteiro como texto: cabeçalho + uma linha por parada, cada uma terminando em \n. */
export function montarCsv(dados) {
  return `${COLUNAS.join(',')}\n${linhasDoRomaneio(dados).map((campos) => `${campos.join(',')}\n`).join('')}`;
}

/** Nome do arquivo (o mesmo de sempre): romaneio_expedicao_zubale_AAAA-MM-DD.csv */
export const nomeDoArquivo = (dataIso) => `romaneio_expedicao_zubale_${dataIso}.csv`;

/** Aviso ao lado do botão: deixa claro que a chegada é estimativa e que o arquivo traz o nome dos clientes. */
export function avisoDoRomaneio(relatorio, tempoPorParada) {
  const clientes = 'O arquivo inclui o nome dos clientes.';
  if (!relatorio || relatorio.saidaUsada === null || relatorio.saidaUsada === undefined) {
    return `A chegada no arquivo fica em branco até você informar a hora de saída. ${clientes}`;
  }
  return `A chegada no arquivo é uma estimativa (saída às ${minutosParaHora(relatorio.saidaUsada)}, ${tempoPorParada} min por parada). ${clientes}`;
}
