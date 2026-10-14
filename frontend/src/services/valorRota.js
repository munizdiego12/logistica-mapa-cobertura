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

/** "informado" ou "padrão", como mostrado nas rotas e no resumo. */
export function rotuloDaOrigem(origem) {
  return origem === 'informado' ? 'informado' : 'padrão';
}
