// Tratamento da sessão do operador: quando o servidor responde 401 (token ausente, inválido ou vencido),
// limpa o que ficou guardado e avisa o app para voltar à tela de login. Sem dependências, para ser testável.

export const MENSAGEM_SESSAO_EXPIRADA = 'Sua sessão expirou. Entre novamente.';

// Login e cadastro não têm sessão ainda: um erro neles é erro de formulário, não sessão vencida.
const CAMINHOS_ABERTOS = ['/auth/login', '/auth/register'];

/**
 * Se o erro é um 401 de rota protegida, apaga token e operador e chama `aoExpirar` (uma vez: só quando ainda
 * havia token, para respostas atrasadas de uma sessão já encerrada não repetirem o aviso). Devolve true se era 401.
 */
export function tratarErroDeSessao(erro, aoExpirar, armazenamento = globalThis.localStorage) {
  if (erro?.response?.status !== 401) return false;
  const url = String(erro?.config?.url ?? '');
  if (CAMINHOS_ABERTOS.some((caminho) => url.includes(caminho))) return false;

  let haviaToken;
  try {
    haviaToken = Boolean(armazenamento?.getItem('token'));
    armazenamento?.removeItem('token');
    armazenamento?.removeItem('operador');
  } catch {
    haviaToken = true;
  }
  if (haviaToken) aoExpirar?.();
  return true;
}

/** Liga o tratamento de 401 em toda resposta de erro de uma instância do axios. Devolve o id para `eject`. */
export function instalarTratamento401(instancia, aoExpirar) {
  return instancia.interceptors.response.use(
    (resposta) => resposta,
    (erro) => {
      tratarErroDeSessao(erro, aoExpirar);
      return Promise.reject(erro);
    },
  );
}
