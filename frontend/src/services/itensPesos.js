// Pesos dos itens: conferência do formulário "Novo item" e contas da importação por arquivo. Sem dependências, para ser testável com
// o `node --test`. O servidor confere tudo de novo. O peso é só informativo: nada aqui bloqueia ou avisa por capacidade.

export const PESO_MAXIMO_KG = 1000;
export const CONFIANCAS = [
  { valor: 'alta', rotulo: 'Conferido (alta)' },
  { valor: 'media', rotulo: 'Média' },
  { valor: 'baixa', rotulo: 'Incerto (baixa)' },
];
export const FORMULARIO_NOVO_ITEM = { id_sku: '', reference_code: '', nome: '', peso_kg: '', fonte: '', confianca: 'media' };

/** Peso em kg com vírgula ou ponto decimal ("1,5", "0.045"). Devolve null se não for número. */
export function numeroDoPeso(texto) {
  const t = String(texto ?? '').trim().toLowerCase().replace(/\s*kg$/, '').replace(/\s/g, '');
  if (!/^[0-9.,]+$/.test(t)) return null;
  let normal = t;
  if (t.includes(',') && t.includes('.')) {
    normal = t.lastIndexOf(',') > t.lastIndexOf('.') ? t.replace(/\./g, '').replace(',', '.') : t.replace(/,/g, '');
  } else if (t.includes(',')) {
    normal = t.replace(',', '.');
  } else if ((t.match(/\./g) || []).length > 1) {
    normal = t.replace(/\./g, '');
  }
  return /^\d+(\.\d+)?$/.test(normal) ? Number(normal) : null;
}

/** Confere o formulário do novo item; mensagens em linguagem do operador (as mesmas do servidor). */
export function validarNovoItem(form) {
  const erros = {};
  const codigo = String(form.id_sku ?? '').trim();
  if (!codigo) erros.id_sku = 'Informe o código do item.';
  else if (!/^[A-Za-z0-9._-]{1,40}$/.test(codigo)) erros.id_sku = 'O código do item pode ter até 40 letras, números, ponto, hífen ou sublinhado (sem espaços).';
  const nome = String(form.nome ?? '').trim();
  if (!nome) erros.nome = 'Informe o nome do item.';
  else if (nome.length > 300) erros.nome = 'O nome do item pode ter até 300 caracteres.';
  if (String(form.reference_code ?? '').trim().length > 60) erros.reference_code = 'O código de referência pode ter até 60 caracteres.';
  if (String(form.fonte ?? '').trim().length > 100) erros.fonte = 'A fonte pode ter até 100 caracteres.';
  const peso = String(form.peso_kg ?? '').trim();
  if (peso !== '') {
    const n = numeroDoPeso(peso);
    if (n === null || n <= 0 || n > PESO_MAXIMO_KG) erros.peso_kg = 'O peso precisa ser um número em kg, maior que 0 e até 1000 (use vírgula ou ponto, ex.: 1,5).';
  }
  if (!CONFIANCAS.some((c) => c.valor === form.confianca)) erros.confianca = 'Escolha a confiança: alta, média ou baixa.';
  return { ok: Object.keys(erros).length === 0, erros };
}

/** Corpo enviado ao servidor (campos vazios viram null; a vírgula decimal segue como digitada, o servidor entende). */
export function corpoNovoItem(form) {
  const vazioParaNulo = (v) => (String(v ?? '').trim() === '' ? null : String(v).trim());
  return {
    id_sku: String(form.id_sku ?? '').trim(),
    reference_code: vazioParaNulo(form.reference_code),
    nome: String(form.nome ?? '').trim(),
    peso_kg: vazioParaNulo(form.peso_kg),
    fonte: vazioParaNulo(form.fonte),
    confianca: form.confianca || 'media',
  };
}

/**
 * Quantos itens a importação vai gravar com as opções marcadas: os novos com peso, os novos sem peso (se "incluir itens sem peso")
 * e os já existentes que podem ser atualizados (se "atualizar também"); os preservados (peso editado na tela) nunca entram.
 */
export function quantosVaoSerImportados(resumo, { atualizar = false, incluirSemPeso = true } = {}) {
  const novos = resumo.novos_com_peso + (incluirSemPeso ? resumo.novos_sem_peso : 0);
  const atualizaveis = atualizar
    ? resumo.existentes_atualizaveis - (incluirSemPeso ? 0 : resumo.existentes_atualizaveis_sem_peso)
    : 0;
  return novos + Math.max(0, atualizaveis);
}

/** Linha do relatório de erros: "Linha 12 (código 99): motivo; motivo". */
export function textoDoErroDeLinha(erro) {
  return `Linha ${erro.linha}${erro.id ? ` (código ${erro.id})` : ''}: ${erro.motivos.join('; ')}`;
}

const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;

/** Resumo do que foi gravado, a partir da resposta da confirmação. */
export function textoDoResultado(r) {
  const partes = [];
  const novos = r.novos + r.novos_sem_peso;
  partes.push(plural(novos, 'item novo', 'itens novos'));
  if (r.atualizados) partes.push(plural(r.atualizados, 'atualizado', 'atualizados'));
  if (r.preservados) partes.push(`${plural(r.preservados, 'preservado', 'preservados')} (peso editado na tela)`);
  if (r.ja_existentes_ignorados) partes.push(`${plural(r.ja_existentes_ignorados, 'já existente ignorado', 'já existentes ignorados')}`);
  if (r.sem_peso_ignorados) partes.push(`${plural(r.sem_peso_ignorados, 'sem peso ignorado', 'sem peso ignorados')}`);
  if (r.invalidos) partes.push(`${plural(r.invalidos, 'linha com erro ficou de fora', 'linhas com erro ficaram de fora')}`);
  return `Importação concluída: ${partes.join(', ')}.`;
}
