// frontend/src/components/Login.jsx
import React, { useState } from 'react';
import api from '../services/api';

export default function Login({ onLoginSuccess }) {
  const [isRegistering, setIsRegistering] = useState(false);
  const [nome, setNome] = useState('');
  const [email, setEmail] = useState('');
  const [senha, setSenha] = useState('');
  const [codigoConvite, setCodigoConvite] = useState('');
  const [erro, setErro] = useState('');
  const [carregando, setCarregando] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErro('');
    setCarregando(true);

    try {
      if (isRegistering) {
        // Registro usa JSON normal
        await api.post('/api/auth/register', { nome, email, senha, codigo_convite: codigoConvite });
        setIsRegistering(false);
        setErro('Operador criado com sucesso! Faça login.');
      } else {
        // Login usa o contrato OAuth2PasswordRequestForm do backend:
        // exige form-urlencoded com os campos "username" e "password"
        // (não JSON, e não "email"/"senha").
        const form = new URLSearchParams();
        form.append('username', email);
        form.append('password', senha);

        const resp = await api.post('/api/auth/login', form, {
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        });

        localStorage.setItem('token', resp.data.access_token);
        localStorage.setItem('operador', JSON.stringify(resp.data.operador));
        onLoginSuccess(resp.data.operador);
      }
    } catch (err) {
      setErro(err?.response?.data?.detail || err.message || 'Erro na operação');
    } finally {
      setCarregando(false);
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

          {isRegistering && (
            <div>
              <label className="block text-sm font-medium text-slate-700">Código de Convite</label>
              <input
                type="text"
                required
                value={codigoConvite}
                onChange={(e) => setCodigoConvite(e.target.value)}
                placeholder="Fornecido pelo administrador"
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
            disabled={carregando}
            className="w-full bg-orange-600 text-white py-2 px-4 rounded-md hover:bg-orange-700 font-medium text-sm transition disabled:opacity-60"
          >
            {carregando ? 'Aguarde...' : (isRegistering ? 'Cadastrar' : 'Entrar')}
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