// Única URL base do backend para todo o frontend (login, cadastro e as demais chamadas).
// Padrão: o backend do Render. Pode ser trocada pela variável VITE_API_URL (ex.: na Vercel, ou num .env local para
// testar um backend na própria máquina). Sem dependências, para ser testável com o `node --test` do Node.

export const URL_PADRAO = 'https://routeflow-backend-v5ji.onrender.com';

/**
 * Limpa o valor de VITE_API_URL: tira espaços, barras e um "/api" no final (as rotas já levam o prefixo /api).
 * Vazio ou que não comece com http:// ou https:// volta para o padrão (sem esquema, o navegador trataria como
 * endereço relativo e as chamadas iriam para o lugar errado).
 */
export function resolverUrlBase(valor) {
  const texto = String(valor ?? '').trim().replace(/\/+$/, '').replace(/\/api$/i, '').replace(/\/+$/, '');
  return /^https?:\/\/[^\s/]+/i.test(texto) ? texto : URL_PADRAO;
}
