// frontend/src/components/Login.jsx
import React, { useState } from 'react';
import { ShieldCheck, AlertCircle, Loader2 } from 'lucide-react';
import api from '../services/api';

export default function Login({ onLoginSuccess }) {
  const [isRegistering, setIsRegistering] = useState(false);
  const [nome, setNome] = useState('');
  const [email, setEmail] = useState('');
  const [senha, setSenha] = useState('');
  const [codigoConvite, setCodigoConvite] = useState('');
  const [erro, setErro] = useState('');
  const [sucesso, setSucesso] = useState('');
  const [carregando, setCarregando] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErro('');
    setSucesso('');
    setCarregando(true);

    try {
      if (isRegistering) {
        // Registro usa JSON normal
        await api.post('/api/auth/register', { nome, email, senha, codigo_convite: codigoConvite });
        setIsRegistering(false);
        setSucesso('Operador criado com sucesso! Faça login.');
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

  const inputClass =
    "w-full text-sm bg-slate-900/90 border border-slate-800 focus:border-blue-500/80 rounded-lg px-3 py-2.5 text-slate-100 placeholder:text-slate-500 focus:outline-none transition-colors";
  const labelClass = "block text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1.5";

  return (
    <div className="min-h-screen bg-[#030712] flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-slate-900/60 backdrop-blur-sm border border-slate-800/80 rounded-2xl shadow-2xl shadow-black/40 p-8">

        <div className="flex flex-col items-center mb-6">
          <div className="w-12 h-12 rounded-xl overflow-hidden flex items-center justify-center bg-blue-500/10 border border-blue-500/20 shadow-md shadow-blue-950/40 p-2 mb-3">
            <img src="logo-zubale.svg" alt="Zubale Logo" className="w-full h-full object-contain" />
          </div>
          <h2 className="text-lg font-bold text-slate-100 text-center">
            {isRegistering ? 'Cadastrar Operador' : 'Login de Operador'}
          </h2>
          <p className="text-[11px] text-slate-500 mt-1">Inteligência Logística • Operations & Routing</p>
        </div>

        {erro && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs flex items-start gap-2">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{erro}</span>
          </div>
        )}

        {sucesso && (
          <div className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs flex items-start gap-2">
            <ShieldCheck className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{sucesso}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {isRegistering && (
            <div>
              <label className={labelClass}>Nome Completo</label>
              <input
                type="text"
                required
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                className={inputClass}
              />
            </div>
          )}

          {isRegistering && (
            <div>
              <label className={labelClass}>Código de Convite</label>
              <input
                type="text"
                required
                value={codigoConvite}
                onChange={(e) => setCodigoConvite(e.target.value)}
                placeholder="Fornecido pelo administrador"
                className={inputClass}
              />
            </div>
          )}

          <div>
            <label className={labelClass}>E-mail</label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </div>

          <div>
            <label className={labelClass}>Senha</label>
            <input
              type="password"
              required
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              className={inputClass}
            />
          </div>

          <button
            type="submit"
            disabled={carregando}
            className="w-full flex items-center justify-center gap-2 bg-blue-600 text-white py-2.5 px-4 rounded-lg hover:bg-blue-500 font-semibold text-sm transition-colors shadow-sm shadow-blue-950/40 disabled:opacity-60"
          >
            {carregando && <Loader2 className="w-4 h-4 animate-spin" />}
            {carregando ? 'Aguarde...' : (isRegistering ? 'Cadastrar' : 'Entrar')}
          </button>
        </form>

        <div className="mt-5 text-center">
          <button
            type="button"
            onClick={() => { setIsRegistering(!isRegistering); setErro(''); setSucesso(''); }}
            className="text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors"
          >
            {isRegistering ? 'Já tem uma conta? Faça login' : 'Novo operador? Criar conta'}
          </button>
        </div>
      </div>
    </div>
  );
}
