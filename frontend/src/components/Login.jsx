// frontend/src/components/Login.jsx
import React, { useState } from 'react';

export default function Login({ onLoginSuccess }) {
  const [isRegistering, setIsRegistering] = useState(false);
  const [nome, setNome] = useState('');
  const [email, setEmail] = useState('');
  const [senha, setSenha] = useState('');
  const [erro, setErro] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErro('');
    const endpoint = isRegistering ? '/api/auth/register' : '/api/auth/login';
    
    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(isRegistering ? { nome, email, senha } : { email, senha })
      });
      const data = await resp.json();

      if (!resp.ok) throw new Error(data.detail || 'Erro na operação');

      if (isRegistering) {
        setIsRegistering(false);
        setErro('Operador criado com sucesso! Faça login.');
      } else {
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('operador', JSON.stringify(data.operador));
        onLoginSuccess(data.operador);
      }
    } catch (err) {
      setErro(err.message);
    }
  };

  return (
    <div className="fixed inset-0 bg-slate-900 bg-opacity-75 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
        <h2 className="text-xl font-bold mb-4 text-slate-800 text-center">
          {isRegistering ? 'Cadastrar Operador' : 'Login de Operador'}
        </h2>
        
        {erro && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded">
            {erro}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {isRegistering && (
            <div>
              <label className="block text-sm font-medium text-slate-700">Nome Completo</label>
              <input
                type="text"
                required
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                className="mt-1 block w-full rounded-md border-slate-300 shadow-sm border p-2 text-sm"
              />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-700">E-mail</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 block w-full rounded-md border-slate-300 shadow-sm border p-2 text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700">Senha</label>
            <input
              type="password"
              required
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              className="mt-1 block w-full rounded-md border-slate-300 shadow-sm border p-2 text-sm"
            />
          </div>

          <button
            type="submit"
            className="w-full bg-orange-600 text-white py-2 px-4 rounded-md hover:bg-orange-700 font-medium text-sm transition"
          >
            {isRegistering ? 'Cadastrar' : 'Entrar'}
          </button>
        </form>

        <div className="mt-4 text-center">
          <button
            type="button"
            onClick={() => { setIsRegistering(!isRegistering); setErro(''); }}
            className="text-xs text-orange-600 hover:underline"
          >
            {isRegistering ? 'Já tem uma conta? Faça login' : 'Novo operador? Criar conta'}
          </button>
        </div>
      </div>
    </div>
  );
}