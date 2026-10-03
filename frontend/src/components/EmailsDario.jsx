// Aba "E-mails do Dario": boletins de licitação encaminhados por e-mail (BLL
// "Divulgador de editais" e Portal de Compras Públicas "Alerta de Licitações").
// O agente do backend lê cada e-mail, confere se a licitação já veio pela coleta
// pública, avalia a aderência ao perfil e importa para o pipeline o que faz
// sentido — sinalizando a origem. Aqui o time acompanha e corrige (importar
// mesmo assim / ignorar).
import { useEffect, useState } from 'react'
import { api } from '../api.js'
import Janela from './Janela.jsx'

const SITUACOES = {
  importada: { rotulo: 'No pipeline', tom: 'verde' },
  ja_na_base: { rotulo: 'Já na base', tom: 'azul' },
  fora_do_perfil: { rotulo: 'Fora do perfil', tom: 'amarelo' },
  aguardando_ia: { rotulo: 'Aguardando IA', tom: 'cinza' },
  repetido: { rotulo: 'Repetido', tom: 'cinza' },
  ignorado: { rotulo: 'Ignorado', tom: 'cinza' },
  novo: { rotulo: 'Novo', tom: 'cinza' },
}

const TIPOS = {
  bll: 'BLL · Divulgador de editais',
  pcp: 'Portal de Compras Públicas · Alerta de Licitações',
  desconhecido: 'Formato não reconhecido',
}

// ISO (YYYY-MM-DD ou datetime) → DD/MM/AAAA
const dataBr = (iso) => {
  if (!iso) return '—'
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a}` : '—'
}

const dataHoraBr = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d) ? '—' : d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const tempoRelativo = (iso) => {
  if (!iso) return null
  const min = Math.round((Date.now() - new Date(iso)) / 60000)
  if (min < 1) return 'agora'
  if (min < 60) return `há ${min} min`
  const h = Math.round(min / 60)
  return h < 48 ? `há ${h} h` : `há ${Math.round(h / 24)} dias`
}

function Situacao({ item }) {
  const s = SITUACOES[item.situacao] || SITUACOES.novo
  const sufixo = item.licitacao_id && (item.situacao === 'importada' || item.situacao === 'ja_na_base' || item.situacao === 'repetido')
    ? ` #${item.licitacao_id}` : ''
  return (
    <>
      <span className={`veredito ${s.tom}`} title={item.motivo || s.rotulo}>
        {s.rotulo}{sufixo}
        {item.score_ia != null && item.situacao !== 'ja_na_base' && ` · ${item.score_ia}/10`}
      </span>
      {item.motivo && <small className="motivo-ia">{item.motivo}</small>}
    </>
  )
}

export default function EmailsDario() {
  const [status, setStatus] = useState(null)
  const [emails, setEmails] = useState(null)
  const [aberto, setAberto] = useState(null)
  const [erro, setErro] = useState('')
  const [msg, setMsg] = useState('')
  const [ocupado, setOcupado] = useState(false)
  const [colando, setColando] = useState(false)
  const [conteudo, setConteudo] = useState('')
  const [agindo, setAgindo] = useState(null) // id do item com ação em curso

  const carregar = () =>
    Promise.all([api.emailsStatus(), api.emails()])
      .then(([s, e]) => {
        setStatus(s)
        setEmails(e)
        if (aberto === null && e.length) setAberto(e[0].id)
      })
      .catch((e) => setErro(e.message))
  useEffect(() => { carregar() }, [])

  const resumoTriagem = (r) => {
    const partes = []
    if (r.emails_novos != null) partes.push(`${r.emails_novos} e-mail(s) novo(s)`)
    if (r.itens_novos != null) partes.push(`${r.itens_novos} licitação(ões) lida(s)`)
    if (r.importadas) partes.push(`${r.importadas} importada(s) para o pipeline`)
    if (r.fora_do_perfil) partes.push(`${r.fora_do_perfil} fora do perfil`)
    if (r.aguardando_ia) partes.push(`${r.aguardando_ia} aguardando IA`)
    return partes.join(' • ') || 'nada novo'
  }

  async function sincronizar() {
    setOcupado(true)
    setMsg('📨 Lendo os boletins novos no Gmail e avaliando com a IA… isso leva alguns segundos.')
    try {
      const r = await api.sincronizarEmails()
      setMsg(`✔ Sincronizado: ${resumoTriagem(r)}${r.aviso ? ` ⚠ ${r.aviso}` : ''}`)
      await carregar()
    } catch (e) {
      setMsg(`Falha ao sincronizar: ${e.message}`)
    } finally {
      setOcupado(false)
    }
  }

  async function colar() {
    if (conteudo.trim().length < 40) {
      setMsg('⚠ Cole o conteúdo do e-mail (selecione tudo no Gmail, copie e cole aqui).')
      return
    }
    setOcupado(true)
    setMsg('📨 Lendo o e-mail colado e avaliando com a IA…')
    try {
      const r = await api.colarEmail(conteudo)
      setColando(false)
      setConteudo('')
      setMsg(`✔ E-mail lido (${TIPOS[r.email.tipo] || r.email.tipo}): ${r.email.total_itens} licitação(ões) • ${resumoTriagem(r)}${r.aviso ? ` ⚠ ${r.aviso}` : ''}`)
      await carregar()
      setAberto(r.email.id)
    } catch (e) {
      setMsg(`Falha ao ler o e-mail: ${e.message}`)
    } finally {
      setOcupado(false)
    }
  }

  async function importar(item) {
    setAgindo(item.id)
    try {
      await api.importarItemEmail(item.id)
      setMsg(`✔ "${item.orgao || item.objeto.slice(0, 60)}" entrou no pipeline como Identificada (origem: e-mail do Dario).`)
      await carregar()
    } catch (e) {
      setMsg(`Não foi possível importar: ${e.message}`)
    } finally {
      setAgindo(null)
    }
  }

  async function ignorar(item) {
    setAgindo(item.id)
    try {
      await api.ignorarItemEmail(item.id)
      await carregar()
    } catch (e) {
      setMsg(`Não foi possível ignorar: ${e.message}`)
    } finally {
      setAgindo(null)
    }
  }

  if (erro) return <p className="erro">Backend indisponível: {erro}</p>
  if (!status || emails === null) return <p>Carregando…</p>

  const por = status.por_situacao || {}
  const totalItens = Object.values(por).reduce((s, n) => s + n, 0)

  return (
    <>
      {colando && (
        <Janela titulo="Colar e-mail do Dario" aoFechar={() => !ocupado && setColando(false)}>
          <div className="colar-email">
            <p className="auto-dica">
              No Gmail, abra o e-mail encaminhado (“Divulgador de editais” ou “Alerta de Licitações”),
              selecione todo o conteúdo (Ctrl+A no corpo), copie e cole abaixo. O agente identifica as
              licitações, confere se já estão na base e avalia a aderência ao perfil.
            </p>
            <textarea
              value={conteudo}
              onChange={(e) => setConteudo(e.target.value)}
              placeholder="Cole aqui o e-mail completo…"
              disabled={ocupado}
            />
            <div className="acoes">
              <button type="button" onClick={() => setColando(false)} disabled={ocupado}>Cancelar</button>
              <button type="button" className="primario" onClick={colar} disabled={ocupado}>
                {ocupado ? '⏳ Lendo…' : 'Processar e-mail'}
              </button>
            </div>
          </div>
        </Janela>
      )}

      {msg && <div className="banner">{msg}</div>}

      <div className="cockpit">
        <div className="tile">
          <span className="tile-k"><span className={status.gmail_configurado ? 'led' : 'led led-alerta'} /> E-mails lidos</span>
          <span className="tile-v">{status.total_emails}</span>
          <span className="tile-d">
            {status.gmail_configurado
              ? `Gmail conectado · de ${status.remetente}`
              : 'Gmail não conectado — use “Colar e-mail”'}
          </span>
        </div>
        <div className="tile">
          <span className="tile-k">Licitações nos e-mails</span>
          <span className="tile-v">{totalItens}</span>
          <span className="tile-d">{por.repetido ? `${por.repetido} repetidas entre e-mails` : 'itens citados nos boletins'}</span>
        </div>
        <div className="tile">
          <span className="tile-k">Importadas p/ pipeline</span>
          <span className="tile-v">{por.importada || 0}</span>
          <span className="tile-d">aderentes ao perfil · selo “✉ Dario” no card</span>
        </div>
        <div className="tile">
          <span className="tile-k">Já na base</span>
          <span className="tile-v">{por.ja_na_base || 0}</span>
          <span className="tile-d">a coleta pública já tinha</span>
        </div>
        <div className="tile">
          <span className="tile-k">Fora do perfil</span>
          <span className="tile-v">{por.fora_do_perfil || 0}</span>
          <span className="tile-d">{por.aguardando_ia ? `${por.aguardando_ia} aguardando IA` : 'UF ou objeto fora do perfil'}</span>
        </div>
      </div>

      <div className="emails-acoes">
        <button
          type="button" className="primario" onClick={sincronizar}
          disabled={ocupado || !status.gmail_configurado}
          title={status.gmail_configurado ? 'Lê os boletins novos da caixa e avalia' : 'Configure o Gmail no servidor (GMAIL_CLIENT_ID / SECRET / REFRESH_TOKEN) para ler a caixa automaticamente'}
        >
          {ocupado ? '⏳ Processando…' : '📨 Sincronizar Gmail agora'}
        </button>
        <button type="button" className="btn-docs" onClick={() => setColando(true)} disabled={ocupado}>
          📋 Colar e-mail
        </button>
        <span className="dica">
          {status.gmail_configurado
            ? `Leitura automática a cada coleta${status.ultima_sincronizacao ? ` · última ${tempoRelativo(status.ultima_sincronizacao)}` : ''}${status.ultima_sincronizacao_erro ? ` · ⚠ ${status.ultima_sincronizacao_erro}` : ''}`
            : 'Sem conexão com o Gmail, cole o e-mail encaminhado — o agente faz o resto.'}
          {!status.ia_configurada && ' · ⚠ IA não configurada: a triagem fica “aguardando IA”.'}
        </span>
      </div>

      {!emails.length && (
        <p>Nenhum e-mail processado ainda. Sincronize o Gmail ou cole um e-mail encaminhado pelo Dario.</p>
      )}

      {emails.map((e) => {
        const expandido = aberto === e.id
        const r = e.resumo || {}
        return (
          <div className="email-bloco" key={e.id}>
            <div className="email-cab" onClick={() => setAberto(expandido ? null : e.id)}>
              <span className="email-data" title={`Recebido em ${dataHoraBr(e.recebido_em)} · processado ${dataHoraBr(e.processado_em)}`}>
                {dataBr(e.recebido_em || e.processado_em)}
              </span>
              <span className={`selo-portal ${e.tipo}`}>{e.tipo === 'bll' ? 'BLL' : e.tipo === 'pcp' ? 'Portal de Compras Públicas' : '?'}</span>
              <strong title={e.assunto}>{e.assunto || TIPOS[e.tipo] || 'E-mail'}</strong>
              {e.origem === 'colado' && <span className="selo-suspensa" title="Texto colado na tela (não lido do Gmail)">colado</span>}
              <span className="email-resumo">
                <span className="veredito cinza">{e.total_itens} lic.</span>
                {r.importada > 0 && <span className="veredito verde">{r.importada} no pipeline</span>}
                {r.ja_na_base > 0 && <span className="veredito azul">{r.ja_na_base} já na base</span>}
                {r.fora_do_perfil > 0 && <span className="veredito amarelo">{r.fora_do_perfil} fora</span>}
                {r.aguardando_ia > 0 && <span className="veredito cinza">{r.aguardando_ia} aguard. IA</span>}
                {r.repetido > 0 && <span className="veredito cinza">{r.repetido} repet.</span>}
              </span>
              <span className="email-seta">{expandido ? '▾' : '▸'}</span>
            </div>
            {expandido && (
              <div className="email-itens">
                {e.erro && <p className="docs-aviso">⚠ {e.erro}</p>}
                {e.itens.length > 0 && (
                  <table className="tabela">
                    <thead>
                      <tr>
                        <th>Órgão</th><th>Local</th><th>Certame</th><th>Objeto</th><th>Sessão / fim</th><th>Situação</th><th>Ações</th>
                      </tr>
                    </thead>
                    <tbody>
                      {e.itens.map((i) => {
                        const podeImportar = ['fora_do_perfil', 'aguardando_ia', 'ignorado', 'novo'].includes(i.situacao)
                          || (i.situacao === 'repetido' && !i.licitacao_id)
                        const podeIgnorar = ['fora_do_perfil', 'aguardando_ia', 'novo'].includes(i.situacao)
                        return (
                          <tr key={i.id} className={i.situacao === 'importada' ? 'linha-importada' : ''}>
                            <td>{i.orgao || '—'}</td>
                            <td>{[i.municipio, i.uf].filter(Boolean).join('/') || '—'}</td>
                            <td>
                              {i.modalidade && <div>{i.modalidade}</div>}
                              {i.numero_certame && <small className="texto-mudo">nº {i.numero_certame}</small>}
                            </td>
                            <td className="objeto" title={i.objeto}>{i.objeto}</td>
                            <td>{dataBr(i.data_encerramento)}</td>
                            <td><Situacao item={i} /></td>
                            <td>
                              <span className="acoes-linha">
                                {i.link && (
                                  <a className="btn-docs" href={i.link} target="_blank" rel="noreferrer"
                                    title={`Abrir no ${i.portal}`}>↗</a>
                                )}
                                {podeImportar && (
                                  <button type="button" className="btn-docs" disabled={agindo === i.id}
                                    title="Entra no pipeline como Identificada mesmo fora do perfil"
                                    onClick={() => importar(i)}>Importar</button>
                                )}
                                {podeIgnorar && (
                                  <button type="button" className="btn-docs" disabled={agindo === i.id}
                                    onClick={() => ignorar(i)}>Ignorar</button>
                                )}
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </div>
        )
      })}
    </>
  )
}
