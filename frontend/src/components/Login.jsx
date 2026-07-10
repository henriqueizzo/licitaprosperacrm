import { useState } from 'react'
import { api } from '../api.js'

export default function Login({ aoEntrar }) {
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function entrar(e) {
    e.preventDefault()
    if (!email.trim() || !senha) {
      setErro('Informe email e senha.')
      return
    }
    setEnviando(true)
    setErro('')
    try {
      const usuario = await api.login(email.trim(), senha)
      aoEntrar(usuario)
    } catch (err) {
      setErro(err.message === 'Credenciais inválidas' ? 'Email ou senha incorretos.' : err.message)
      setEnviando(false)
    }
  }

  return (
    <div className="login-fundo">
      <form className="login-card" onSubmit={entrar}>
        <span className="logo-chip login-logo-chip">
          <img src="/prospera-logo.png" alt="Próspera" className="login-logo" />
        </span>
        <p className="login-sub">CRM de Licitações</p>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="voce@empresa.com"
            autoComplete="username"
            autoFocus
          />
        </label>
        <label>
          Senha
          <input
            type="password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            placeholder="••••••••"
            autoComplete="current-password"
          />
        </label>
        {erro && <div className="login-erro">{erro}</div>}
        <button type="submit" className="primario" disabled={enviando}>
          {enviando ? 'Entrando…' : 'Entrar'}
        </button>
      </form>
    </div>
  )
}
