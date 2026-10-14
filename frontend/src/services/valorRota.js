// Valor por rota informado pelo operador na roteirização, por tipo de veículo.
// Campo vazio = vale o "valor base" cadastrado em "Motoristas e veículos". Aceita vírgula decimal.
// Sem dependências, para ser testável com o `node --test` do Node.

const NUMERO = /^\d+([.,]\d+)?$/;

/** "Carro de passeio" -> "Passeio"; "Fiorino/Utilitário" -> "Utilitário"; outro nome fica como está. */
export function rotuloDoTipo(nome) {
  const texto = String(nome ?? '');
  if (/passeio/i.test(texto)) return 'Passeio';
  if (/utilit/i.test(texto)) return 'Utilitário';
  return texto;
}

/** Confere o texto digitado. Vazio é válido (usa o valor base); zero é válido; negativo ou texto, não. */
export function validarValorRota(texto) {
  const valor = String(texto ?? '').trim();
  if (valor === '') return { ok: true, vazio: true, mensagem: '' };
  if (valor.startsWith('-')) return { ok: false, vazio: false, mensagem: 'O valor por rota não pode ser negativo.' };
  if (!NUMERO.test(valor)) {
    return { ok: false, vazio: false, mensagem: 'Digite o valor em reais, por exemplo 130 ou 130,50 (ou deixe em branco).' };
  }
  return { ok: true, vazio: false, mensagem: '' };
}

/** Primeira mensagem de erro entre os campos (ou ''), na ordem dos tipos. */
export function primeiroErroDeValores(valores) {
  for (const [nome, texto] of Object.entries(valores ?? {})) {
    const { ok, mensagem } = validarValorRota(texto);
    if (!ok) return `${rotuloDoTipo(nome)}: ${mensagem}`;
  }
  return '';
}

/** Só os campos preenchidos, para enviar ao servidor (os vazios ficam de fora: valem o valor base). */
export function montarValoresPorRota(valores) {
  const saida = {};
  for (const [nome, texto] of Object.entries(valores ?? {})) {
    const valor = String(texto ?? '').trim();
    if (valor !== '') saida[nome] = valor;
  }
  return saida;
}

/** Dica do campo vazio: "padrão R$ 260,00". */
export function dicaValorBase(valorBase) {
  const numero = Number(valorBase);
  if (!Number.isFinite(numero)) return 'valor base';
  return `padrão ${numero.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}`;
}

/**
 * Origem do valor da rota, como mostrada nas rotas e no resumo: "informado nesta roteirização" (digitado na tela),
 * "valor do motorista" (valor próprio do cadastro) ou "padrão" (valor base do tipo de veículo).
 */
export function rotuloDaOrigem(origem) {
  if (origem === 'informado') return 'informado nesta roteirização';
  if (origem === 'motorista') return 'valor do motorista';
  return 'padrão';
}

/** Cor do rótulo da origem (classes do Tailwind), para destacar o que não é o padrão. */
export function corDaOrigem(origem) {
  if (origem === 'informado') return 'text-blue-300';
  if (origem === 'motorista') return 'text-amber-300';
  return 'text-slate-500';
}

/** Valor em reais para mostrar ao lado do campo (ex.: "R$ 130,00"); vazio se não for número. */
export function formatarReais(valor) {
  const numero = Number(valor);
  if (valor === null || valor === undefined || valor === '' || !Number.isFinite(numero)) return '';
  return numero.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}
