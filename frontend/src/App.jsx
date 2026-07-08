import { useEffect, useState } from 'react'
import Pipeline from './components/Pipeline.jsx'
import Licitacoes from './components/Licitacoes.jsx'
import CadastroManual from './components/CadastroManual.jsx'
import Perfil from './components/Perfil.jsx'
import Usuarios from './components/Usuarios.jsx'
import Login from './components/Login.jsx'
import TrocarSenha from './components/TrocarSenha.jsx'
import { api, definirAo401 } from './api.js'

const ABAS = [
  { id: 'pipeline', rotulo: 'Pipeline' },
  { id: 'licitacoes', rotulo: 'Licitações' },
  { id: 'cadastro', rotulo: 'Cadastro Manual' },
  { id: 'perfil', rotulo: 'Perfil da Empresa' },
]

export default function App() {
  const [usuario, setUsuario] = useState(undefined) // undefined=verificando | null=deslogado
  const [aba, setAba] = useState('pipeline')
  const [rodando, setRodando] = useState(false)
  const [msg, setMsg] = useState('')
  const [trocandoSenha, setTrocandoSenha] = useState(false)

  useEffect(() => {
    definirAo401(() => setUsuario(null)) // sessão expirou em qualquer chamada -> login
    api.me().then(setUsuario).catch(() => setUsuario(null))
  }, [])

  async function sair() {
    try {
      await api.logout()
    } catch {
      /* mesmo com falha, volta para o login */
    }
    setUsuario(null)
    setAba('pipeline')
    setMsg('')
  }

  async function rodarPipeline() {
    setRodando(true)
    setMsg('Coletando e analisando… isso pode levar alguns minutos.')
    try {
      const r = await api.executarPipeline()
      const resumo =
        r.erro ??
        `Coleta: ${r.novas_licitacoes} novas • Analisadas: ${r.analisadas} • Oportunidades: ${r.oportunidades_criadas} • Erros: ${r.erros}`
      const avisos = r.avisos?.length ? ` ⚠ ${r.avisos.join(' | ')}` : ''
      setMsg(resumo + avisos)
    } catch (e) {
      setMsg(`Falha ao executar pipeline: ${e.message}`)
    } finally {
      setRodando(false)
    }
  }

  if (usuario === undefined) {
    return <div className="login-fundo"><div className="login-carregando">Carregando…</div></div>
  }
  if (usuario === null) {
    return <Login aoEntrar={(u) => setUsuario(u)} />
  }

  const abas = usuario.is_admin ? [...ABAS, { id: 'usuarios', rotulo: 'Usuários' }] : ABAS

  return (
    <div className="app">
      <header>
        <div className="marca">
          <img src="/prospera-logo.png" alt="Próspera" className="logo" />
          <span className="marca-sub">CRM de Licitações</span>
        </div>
        <nav>
          {abas.map((a) => (
            <button key={a.id} className={aba === a.id ? 'ativo' : ''} onClick={() => setAba(a.id)}>
              {a.rotulo}
            </button>
          ))}
        </nav>
        <button className="primario" onClick={rodarPipeline} disabled={rodando}>
          {rodando ? '⏳ Rodando…' : '▶ Buscar e analisar agora'}
        </button>
        <div className="usuario-area">
          <span className="usuario-nome" title={usuario.email}>{usuario.nome || usuario.email}</span>
          <button className="usuario-btn" onClick={() => setTrocandoSenha(true)}>Trocar senha</button>
          <button className="usuario-btn" onClick={sair}>Sair</button>
        </div>
      </header>
      {msg && <div className="banner">{msg}</div>}
      <main>
        {aba === 'pipeline' && <Pipeline />}
        {aba === 'licitacoes' && <Licitacoes />}
        {aba === 'cadastro' && <CadastroManual />}
        {aba === 'perfil' && <Perfil />}
        {aba === 'usuarios' && usuario.is_admin && <Usuarios usuarioLogado={usuario} />}
      </main>
      {trocandoSenha && <TrocarSenha aoFechar={() => setTrocandoSenha(false)} />}
    </div>
  )
}
