import { useState } from 'react'
import { api } from '../api.js'

export default function TrocarSenha({ aoFechar }) {
  const [senhaAtual, setSenhaAtual] = useState('')
  const [senhaNova, setSenhaNova] = useState('')
  const [confirmar, setConfirmar] = useState('')
  const [msg, setMsg] = useState(null) // { texto, ok }
  const [enviando, setEnviando] = useState(false)

  async function salvar(e) {
    e.preventDefault()
    if (senhaNova.length < 6) {
      setMsg({ texto: 'A nova senha deve ter pelo menos 6 caracteres.', ok: false })
      return
    }
    if (senhaNova !== confirmar) {
      setMsg({ texto: 'A confirmação não confere com a nova senha.', ok: false })
      return
    }
    setEnviando(true)
    setMsg(null)
    try {
      await api.trocarSenha(senhaAtual, senhaNova)
      setMsg({ texto: 'Senha alterada com sucesso!', ok: true })
      setTimeout(aoFechar, 1200)
    } catch (err) {
      setMsg({ texto: err.message, ok: false })
      setEnviando(false)
    }
  }

  return (
    <div className="modal-fundo" onClick={aoFechar}>
      <div className="modal modal-estreito" onClick={(e) => e.stopPropagation()}>
        <form className="perfil" onSubmit={salvar}>
          <div className="docs-topo">
            <strong>Trocar senha</strong>
            <button type="button" className="doc-fechar" onClick={aoFechar} aria-label="Fechar">✕</button>
          </div>
          <label>
            Senha atual
            <input
              type="password"
              value={senhaAtual}
              onChange={(e) => setSenhaAtual(e.target.value)}
              autoComplete="current-password"
              autoFocus
            />
          </label>
          <label>
            Nova senha (mínimo 6 caracteres)
            <input
              type="password"
              value={senhaNova}
              onChange={(e) => setSenhaNova(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          <label>
            Confirmar nova senha
            <input
              type="password"
              value={confirmar}
              onChange={(e) => setConfirmar(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          {msg && <div className={msg.ok ? 'form-msg' : 'login-erro'}>{msg.texto}</div>}
          <button type="submit" className="primario" disabled={enviando}>
            {enviando ? 'Salvando…' : 'Salvar nova senha'}
          </button>
        </form>
      </div>
    </div>
  )
}
