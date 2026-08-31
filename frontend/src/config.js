// Fonte única da URL do backend, usada tanto pelo App.jsx quanto pelo
// services/api.js (usado pela tela de Login). Evita que as duas partes do
// frontend apontem para endereços diferentes.
//
// Prioridade: variável de ambiente VITE_API_URL (se configurada na Vercel)
// > URL de produção do Render (fallback padrão).
export const API_BASE_URL = import.meta.env.VITE_API_URL || 'https://routeflow-backend-v5ji.onrender.com';

// Mantido por compatibilidade com o App.jsx, que já usa as rotas com o
// prefixo /api embutido na constante (ex: `${API_BASE}/upload`).
export const API_BASE = `${API_BASE_URL}/api`;
