import { useEffect, useState } from 'react'
import { api } from '../api.js'

const PERIODOS = [
  { dias: 7, rotulo: '7 dias' },
  { dias: 30, rotulo: '30 dias' },
  { dias: 90, rotulo: '90 dias' },
]

// Rótulos pt-BR dos tipos de evento (mesmos valores gravados pelo backend)
const TIPOS = {
  login: 'Login',
  ver_documentos: 'Documentação',
  download_documento: 'Download de documento',
  upload_documento: 'Upload de documento',
  mover_estagio: 'Mudança de estágio',
  cadastro_manual: 'Cadastro manual',
  coleta_manual: 'Coleta manual',
  reanalise: 'Reanálise IA',
  importar_analise: 'Análise importada (PDF)',
  extracao_cadastro: 'Extração de cadastro',
}

const rotuloTipo = (tipo) => TIPOS[tipo] || tipo

function tempoUso(min) {
  if (!min) return '—'
  if (min < 60) return `${min} min`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h} h ${m} min` : `${h} h`
}

function dataHora(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', {
    day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

// 'YYYY-MM-DD' (dia já no fuso do Brasil) → 'seg, 20/07/26'
function dataDia(dia) {
  const [a, m, d] = dia.split('-')
  const rotulo = new Date(Number(a), Number(m) - 1, Number(d)).toLocaleDateString('pt-BR', {
    weekday: 'short', day: '2-digit', month: '2-digit', year: '2-digit',
  })
  return rotulo.replace('.', '')
}

export default function Atividade() {
  const [dias, setDias] = useState(30)
  const [usuarios, setUsuarios] = useState(null) // null = carregando
  const [selecionado, setSelecionado] = useState(null) // usuário da tabela-resumo
  const [eventos, setEventos] = useState(null)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    let ativo = true
    setUsuarios(null)
    setMsg('')
    api.atividade(dias)
      .then((r) => { if (ativo) setUsuarios(r.usuarios) })
      .catch((e) => { if (ativo) { setUsuarios([]); setMsg(`Falha ao carregar a atividade: ${e.message}`) } })
    return () => { ativo = false }
  }, [dias])

  useEffect(() => {
    if (!selecionado) return
    let ativo = true
    setEventos(null)
    api.atividadeEventos({ usuarioId: selecionado.usuario_id, dias, limit: 100 })
      .then((r) => { if (ativo) setEventos(r.eventos) })
      .catch((e) => { if (ativo) { setEventos([]); setMsg(`Falha ao carregar os eventos: ${e.message}`) } })
    return () => { ativo = false }
  }, [selecionado, dias])

  function selecionar(u) {
    setSelecionado(selecionado?.usuario_id === u.usuario_id ? null : u)
  }

  return (
    <div className="atividade">
      {msg && <div className="banner erro">{msg}</div>}

      <div className="atividade-topo">
        <span className="atividade-legenda">
          Uso do sistema por usuário — eventos registrados nas ações principais
          (login, documentação, pipeline, cadastros). Clique num usuário para ver
          as horas de uso por dia e os eventos.
        </span>
        <div className="segmentado" role="tablist" aria-label="Período">
          {PERIODOS.map((p) => (
            <button key={p.dias} className={dias === p.dias ? 'ativo' : ''}
                    onClick={() => setDias(p.dias)}>
              {p.rotulo}
            </button>
          ))}
        </div>
      </div>

      <table className="tabela">
        <thead>
          <tr>
            <th>Usuário</th>
            <th>Último acesso</th>
            <th>Eventos</th>
            <th>Licitações acessadas</th>
            <th>Dias ativos</th>
            <th>Tempo de uso (est.)</th>
            <th>Atividade por tipo</th>
          </tr>
        </thead>
        <tbody>
          {(usuarios || []).map((u) => (
            <tr key={u.usuario_id}
                className={`clicavel ${selecionado?.usuario_id === u.usuario_id ? 'selecionada' : ''}`}
                onClick={() => selecionar(u)}>
              <td>
                {u.nome || u.email}
                {!u.ativo && <span className="veredito cinza atividade-pilula">Desativado</span>}
                <div className="atividade-detalhe">{u.email}</div>
              </td>
              <td>{dataHora(u.ultimo_acesso)}</td>
              <td>{u.total_eventos}</td>
              <td>{u.licitacoes_distintas}</td>
              <td>{u.uso_por_dia?.length || 0}</td>
              <td>{tempoUso(u.tempo_uso_minutos)}</td>
              <td>
                <div className="atividade-tipos">
                  {Object.entries(u.eventos_por_tipo)
                    .sort((a, b) => b[1] - a[1])
                    .map(([tipo, qtd]) => (
                      <span key={tipo} className="veredito azul atividade-pilula">
                        {rotuloTipo(tipo)} · {qtd}
                      </span>
                    ))}
                  {u.total_eventos === 0 && <span className="pendente">Sem atividade no período</span>}
                </div>
              </td>
            </tr>
          ))}
          {usuarios === null && (
            <tr><td colSpan={7} className="pendente">Carregando…</td></tr>
          )}
          {usuarios?.length === 0 && (
            <tr><td colSpan={7} className="pendente">Nenhum usuário encontrado.</td></tr>
          )}
        </tbody>
      </table>

      {selecionado && (
        <div className="perfil atividade-eventos">
          <div className="atividade-topo">
            <strong>Atividade de {selecionado.nome || selecionado.email} — últimos {dias} dias</strong>
            <button className="usuario-btn" onClick={() => setSelecionado(null)}>Fechar</button>
          </div>

          <h4 className="atividade-subtitulo">Horas de uso por dia</h4>
          <table className="tabela atividade-uso-dia">
            <thead>
              <tr>
                <th>Dia</th>
                <th>Tempo de uso (est.)</th>
                <th>Eventos</th>
              </tr>
            </thead>
            <tbody>
              {(selecionado.uso_por_dia || []).map((d) => (
                <tr key={d.dia}>
                  <td>{dataDia(d.dia)}</td>
                  <td>{tempoUso(d.minutos)}</td>
                  <td>{d.eventos}</td>
                </tr>
              ))}
              {(selecionado.uso_por_dia || []).length === 0 && (
                <tr><td colSpan={3} className="pendente">Sem uso registrado no período.</td></tr>
              )}
            </tbody>
          </table>

          <h4 className="atividade-subtitulo">Eventos</h4>
          <table className="tabela">
            <thead>
              <tr>
                <th>Quando</th>
                <th>Ação</th>
                <th>Licitação</th>
                <th>Detalhe</th>
              </tr>
            </thead>
            <tbody>
              {(eventos || []).map((e) => (
                <tr key={e.id}>
                  <td>{dataHora(e.criado_em)}</td>
                  <td><span className="veredito azul atividade-pilula">{rotuloTipo(e.tipo)}</span></td>
                  <td>
                    {e.licitacao_id ? (
                      <div className="atividade-obj" title={e.licitacao_objeto || ''}>
                        {e.licitacao_objeto || `Licitação #${e.licitacao_id}`}
                        {e.licitacao_orgao && <div className="atividade-detalhe">{e.licitacao_orgao}</div>}
                      </div>
                    ) : '—'}
                  </td>
                  <td className="atividade-detalhe">{e.detalhe || '—'}</td>
                </tr>
              ))}
              {eventos === null && (
                <tr><td colSpan={4} className="pendente">Carregando…</td></tr>
              )}
              {eventos?.length === 0 && (
                <tr><td colSpan={4} className="pendente">Nenhum evento no período.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
