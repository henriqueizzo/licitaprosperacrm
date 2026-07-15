import { useEffect, useState } from 'react'
import Dashboard from './components/Dashboard.jsx'
import Pipeline from './components/Pipeline.jsx'
import Licitacoes from './components/Licitacoes.jsx'
import CadastroManual from './components/CadastroManual.jsx'
import Perfil from './components/Perfil.jsx'
import Usuarios from './components/Usuarios.jsx'
import Atividade from './components/Atividade.jsx'
import Login from './components/Login.jsx'
import TrocarSenha from './components/TrocarSenha.jsx'
import { api, definirAo401 } from './api.js'

const ABAS = [
  { id: 'dashboard', rotulo: 'Dashboard' },
  { id: 'pipeline', rotulo: 'Pipeline' },
  { id: 'licitacoes', rotulo: 'Licitações' },
  { id: 'cadastro', rotulo: 'Cadastro Manual' },
  { id: 'perfil', rotulo: 'Perfil da Empresa' },
]

// "há 2 h" / "em ~40 min" a partir de um ISO UTC vindo do backend
function tempoRelativo(iso, futuro = false) {
  const min = Math.round(Math.abs(new Date(iso) - Date.now()) / 60000)
  if (futuro && new Date(iso) <= Date.now()) return 'a qualquer momento'
  const texto = min < 60 ? `${Math.max(min, 1)} min` : `${Math.round(min / 60)} h`
  return futuro ? `em ~${texto}` : `há ${texto}`
}

export default function App() {
  const [usuario, setUsuario] = useState(undefined) // undefined=verificando | null=deslogado
  const [aba, setAba] = useState('dashboard') // tela inicial após o login
  const [rodando, setRodando] = useState(false)
  const [msg, setMsg] = useState('')
  const [trocandoSenha, setTrocandoSenha] = useState(false)
  const [coleta, setColeta] = useState(null)
  const [, setTique] = useState(0) // re-renderiza a cada minuto p/ atualizar o "há X min"

  const carregarColeta = () => api.statusPipeline().then(setColeta).catch(() => {})

  useEffect(() => {
    definirAo401(() => setUsuario(null)) // sessão expirou em qualquer chamada -> login
    api.me().then(setUsuario).catch(() => setUsuario(null))
  }, [])

  useEffect(() => {
    if (!usuario) return
    carregarColeta()
    const id = setInterval(() => setTique((t) => t + 1), 60000)
    return () => clearInterval(id)
  }, [usuario])

  async function sair() {
    try {
      await api.logout()
    } catch {
      /* mesmo com falha, volta para o login */
    }
    setUsuario(null)
    setAba('dashboard')
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
      carregarColeta()
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

  const abas = usuario.is_admin
    ? [...ABAS, { id: 'usuarios', rotulo: 'Usuários' }, { id: 'atividade', rotulo: 'Atividade' }]
    : ABAS

  return (
    <div className="app">
      <header>
        <div className="marca">
          <span className="logo-chip">
            <img src="/prospera-logo.png" alt="Próspera" className="logo" />
          </span>
          <span className="marca-sub">CRM de Licitações</span>
        </div>
        <nav>
          {abas.map((a) => (
            <button key={a.id} className={aba === a.id ? 'ativo' : ''} onClick={() => setAba(a.id)}>
              {a.rotulo}
            </button>
          ))}
        </nav>
        <div className="acao-pipeline">
          <button className="primario" onClick={rodarPipeline} disabled={rodando}>
            {rodando ? '⏳ Rodando…' : '▶ Buscar e analisar agora'}
          </button>
          <span className="coleta-status">
            {coleta?.ultima_execucao ? (
              <>
                <span className={coleta.ultimo_resultado?.avisos?.length ? 'led led-alerta' : 'led'} />
                {' '}última coleta {tempoRelativo(coleta.ultima_execucao)}
                {coleta.ultimo_resultado && <> · {coleta.ultimo_resultado.novas_licitacoes} novas</>}
                {coleta.ultimo_resultado?.avisos?.length > 0 && (
                  <button
                    className="coleta-aviso"
                    title="Ver avisos da última coleta"
                    onClick={() => setMsg(`⚠ Avisos da última coleta: ${coleta.ultimo_resultado.avisos.join(' • ')}`)}
                  >⚠</button>
                )}
                {coleta.proxima_estimada && <> · próxima {tempoRelativo(coleta.proxima_estimada, true)}</>}
              </>
            ) : coleta ? (
              <>coleta automática a cada {coleta.intervalo_horas} h</>
            ) : null}
          </span>
        </div>
        <div className="usuario-area">
          <span className="usuario-nome" title={usuario.email}>{usuario.nome || usuario.email}</span>
          <button className="usuario-btn" onClick={() => setTrocandoSenha(true)}>Trocar senha</button>
          <button className="usuario-btn" onClick={sair}>Sair</button>
        </div>
      </header>
      {msg && <div className="banner">{msg}</div>}
      <main>
        {aba === 'dashboard' && <Dashboard />}
        {aba === 'pipeline' && <Pipeline />}
        {aba === 'licitacoes' && <Licitacoes />}
        {aba === 'cadastro' && <CadastroManual />}
        {aba === 'perfil' && <Perfil />}
        {aba === 'usuarios' && usuario.is_admin && <Usuarios usuarioLogado={usuario} />}
        {aba === 'atividade' && usuario.is_admin && <Atividade />}
      </main>
      {trocandoSenha && <TrocarSenha aoFechar={() => setTrocandoSenha(false)} />}
    </div>
  )
}
