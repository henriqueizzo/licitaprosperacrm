import { useEffect, useState } from 'react'
import { api } from '../api.js'

const NOVO = { nome: '', email: '', senha: '', is_admin: false }

export default function Usuarios({ usuarioLogado }) {
  const [usuarios, setUsuarios] = useState([])
  const [novo, setNovo] = useState(NOVO)
  const [msg, setMsg] = useState(null) // { texto, ok }
  const [salvando, setSalvando] = useState(false)

  async function carregar() {
    try {
      setUsuarios(await api.usuarios())
    } catch (e) {
      setMsg({ texto: `Falha ao listar usuários: ${e.message}`, ok: false })
    }
  }

  useEffect(() => {
    carregar()
  }, [])

  async function criar(e) {
    e.preventDefault()
    if (!novo.nome.trim() || !novo.email.trim() || novo.senha.length < 6) {
      setMsg({ texto: 'Preencha nome, email e uma senha com pelo menos 6 caracteres.', ok: false })
      return
    }
    setSalvando(true)
    setMsg(null)
    try {
      await api.criarUsuario({ ...novo, nome: novo.nome.trim(), email: novo.email.trim() })
      setNovo(NOVO)
      setMsg({ texto: 'Usuário criado. Informe a senha a ele com segurança.', ok: true })
      await carregar()
    } catch (err) {
      setMsg({ texto: err.message, ok: false })
    } finally {
      setSalvando(false)
    }
  }

  async function alternarAtivo(u) {
    const acao = u.ativo ? 'Desativar' : 'Reativar'
    if (!window.confirm(`${acao} o acesso de ${u.nome || u.email}?`)) return
    try {
      await api.atualizarUsuario(u.id, { ativo: !u.ativo })
      await carregar()
    } catch (err) {
      setMsg({ texto: err.message, ok: false })
    }
  }

  async function alternarAdmin(u) {
    try {
      await api.atualizarUsuario(u.id, { is_admin: !u.is_admin })
      await carregar()
    } catch (err) {
      setMsg({ texto: err.message, ok: false })
    }
  }

  async function resetarSenha(u) {
    const senha = window.prompt(`Nova senha para ${u.nome || u.email} (mínimo 6 caracteres):`)
    if (senha === null) return
    if (senha.length < 6) {
      setMsg({ texto: 'A senha deve ter pelo menos 6 caracteres.', ok: false })
      return
    }
    try {
      await api.atualizarUsuario(u.id, { senha })
      setMsg({ texto: `Senha de ${u.nome || u.email} redefinida. As sessões dele foram encerradas.`, ok: true })
    } catch (err) {
      setMsg({ texto: err.message, ok: false })
    }
  }

  return (
    <div className="usuarios">
      {msg && <div className={msg.ok ? 'form-msg' : 'banner erro'}>{msg.texto}</div>}

      <table className="tabela">
        <thead>
          <tr>
            <th>Nome</th>
            <th>Email</th>
            <th>Perfil</th>
            <th>Status</th>
            <th>Ações</th>
          </tr>
        </thead>
        <tbody>
          {usuarios.map((u) => {
            const souEu = u.email === usuarioLogado.email
            return (
              <tr key={u.id}>
                <td>{u.nome || '—'}{souEu && <small className="pendente"> (você)</small>}</td>
                <td>{u.email}</td>
                <td>
                  <span className={`veredito ${u.is_admin ? 'verde' : 'amarelo'}`}>
                    {u.is_admin ? 'Administrador' : 'Usuário'}
                  </span>
                </td>
                <td>
                  <span className={`veredito ${u.ativo ? 'verde' : 'vermelho'}`}>
                    {u.ativo ? 'Ativo' : 'Desativado'}
                  </span>
                </td>
                <td>
                  <div className="acoes">
                    <button onClick={() => resetarSenha(u)}>Resetar senha</button>
                    <button onClick={() => alternarAdmin(u)} disabled={souEu}
                            title={souEu ? 'Você não pode alterar seu próprio perfil' : ''}>
                      {u.is_admin ? 'Tornar usuário' : 'Tornar admin'}
                    </button>
                    <button onClick={() => alternarAtivo(u)} disabled={souEu}
                            title={souEu ? 'Você não pode desativar a si mesmo' : ''}>
                      {u.ativo ? 'Desativar' : 'Reativar'}
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
          {usuarios.length === 0 && (
            <tr><td colSpan={5} className="pendente">Carregando…</td></tr>
          )}
        </tbody>
      </table>

      <form className="perfil usuarios-novo" onSubmit={criar}>
        <strong>Novo usuário</strong>
        <div className="grade">
          <label>
            Nome
            <input value={novo.nome} onChange={(e) => setNovo({ ...novo, nome: e.target.value })}
                   placeholder="Nome completo" />
          </label>
          <label>
            Email (usado no login)
            <input type="email" value={novo.email}
                   onChange={(e) => setNovo({ ...novo, email: e.target.value })}
                   placeholder="pessoa@empresa.com" autoComplete="off" />
          </label>
          <label>
            Senha inicial (mínimo 6 caracteres)
            <input type="password" value={novo.senha}
                   onChange={(e) => setNovo({ ...novo, senha: e.target.value })}
                   autoComplete="new-password" />
          </label>
        </div>
        <label className="check">
          <input type="checkbox" checked={novo.is_admin}
                 onChange={(e) => setNovo({ ...novo, is_admin: e.target.checked })} />
          Administrador (pode gerenciar usuários)
        </label>
        <div>
          <button type="submit" className="primario" disabled={salvando}>
            {salvando ? 'Criando…' : 'Criar usuário'}
          </button>
        </div>
      </form>
    </div>
  )
}
