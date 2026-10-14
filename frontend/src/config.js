// Fonte única da URL do backend, usada pelo App.jsx e pelo services/api.js (tela de Login): login, cadastro e as
// demais chamadas partem desta mesma URL base, então nunca apontam para endereços diferentes.
//
// Prioridade: variável de ambiente VITE_API_URL (se definida, na Vercel ou num .env local)
// > URL de produção do Render (padrão). Regras de limpeza do valor em services/urlBase.js.
import { resolverUrlBase } from './services/urlBase';

export const API_BASE_URL = resolverUrlBase(import.meta.env.VITE_API_URL);

// Mesma base com o prefixo /api embutido, para as chamadas do App.jsx (ex.: `${API_BASE}/upload`).
export const API_BASE = `${API_BASE_URL}/api`;
