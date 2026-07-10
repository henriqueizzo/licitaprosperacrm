import { Fragment, useEffect, useState } from 'react'
import { api } from '../api.js'

const brl = (v) =>
  v == null ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

// Por que esta licitação não virou oportunidade no Pipeline?
function motivoNoGo(l) {
  if (l.status_analise === 'descartada_filtro')
    return { cor: 'vermelho', texto: 'Fora do filtro de palavras-chave' }
  if (l.status_analise === 'erro')
    return { cor: 'amarelo', texto: 'Erro na análise — reanalise' }
  const a = l.analise
  if (!a) return { cor: 'pendente', texto: 'Aguardando análise IA' }
  if (a.classificacao_final === 'NÃO RECOMENDADO')
    return { cor: 'vermelho', texto: 'NÃO RECOMENDADO pela IA' }
  if (a.credenciamento_viavel === false)
    return { cor: 'vermelho', texto: 'Credenciamento inviável' }
  if (a.classificacao_final) {
    const maior = Math.max(a.score_beneficios ?? 0, a.score_pagamentos ?? 0)
    if (maior < 6)
      return { cor: 'amarelo', texto: `Score abaixo do corte — B ${a.score_beneficios}/10 · P ${a.score_pagamentos}/10` }
    return { cor: 'amarelo', texto: a.classificacao_final }
  }
  if (a.veredito === 'nao_participar')
    return { cor: 'vermelho', texto: 'Não participar (análise antiga)' }
  return { cor: 'amarelo', texto: 'Sem oportunidade criada' }
}

export default function NoGo() {
  const [itens, setItens] = useState(null)
  const [aberta, setAberta] = useState(null)
  const [msg, setMsg] = useState('')
  const [erro, setErro] = useState('')
  const [ocupada, setOcupada] = useState(null) // id da licitação com ação em andamento

  const carregar = () =>
    Promise.all([api.licitacoes(), api.oportunidades()])
      .then(([ls, ops]) => {
        const noPipeline = new Set(ops.map((o) => o.licitacao?.id).filter(Boolean))
        setItens(ls.filter((l) => !noPipeline.has(l.id)))
      })
      .catch((e) => setErro(e.message))

  useEffect(() => { carregar() }, [])

  async function promover(l) {
    setOcupada(l.id)
    setMsg(`Movendo "${l.orgao || l.objeto.slice(0, 40)}" para o Pipeline…`)
    try {
      await api.criarOportunidade(l.id)
      setMsg('✅ Movida para o Pipeline (estágio Identificada). A decisão da IA foi mantida no histórico.')
      await carregar()
    } catch (e) {
      setMsg(`Erro ao mover: ${e.message}`)
    } finally {
      setOcupada(null)
    }
  }

  async function reanalisar(l) {
    setOcupada(l.id)
    setMsg('Reanalisando com IA… isso pode levar um minuto.')
    try {
      const r = await api.reanalisar(l.id)
      setMsg(r.erro ? `⚠ ${r.erro}` : '✅ Reanálise concluída.')
      await carregar()
    } catch (e) {
      setMsg(`Erro na reanálise: ${e.message}`)
    } finally {
      setOcupada(null)
    }
  }

  if (erro) return <p className="erro">Backend indisponível: {erro}</p>
  if (itens === null) return <p className="pendente">Carregando…</p>
  if (!itens.length)
    return <p>Nenhuma licitação reprovada — todas as coletadas estão no Pipeline. 🎯</p>

  return (
    <>
      {msg && <div className="banner">{msg}</div>}
      <table className="tabela">
        <thead>
          <tr>
            <th>Órgão</th><th>Objeto</th><th>UF</th><th>Valor</th><th>Motivo do No Go</th><th>Ações</th>
          </tr>
        </thead>
        <tbody>
          {itens.map((l) => {
            const m = motivoNoGo(l)
            return (
              <Fragment key={l.id}>
                <tr className="linha" onClick={() => setAberta(aberta === l.id ? null : l.id)}>
                  <td>{l.orgao || '—'}</td>
                  <td className="objeto">{l.objeto}</td>
                  <td>{l.uf || '—'}</td>
                  <td>{brl(l.valor_estimado)}</td>
                  <td>
                    {m.cor === 'pendente'
                      ? <span className="pendente">{m.texto}</span>
                      : <span className={`veredito ${m.cor}`}>{m.texto}</span>}
                  </td>
                  <td>
                    <span className="acoes-nogo" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="btn-docs"
                        disabled={ocupada === l.id}
                        onClick={() => promover(l)}
                        title="Discordar da IA e criar a oportunidade no kanban"
                      >
                        → Pipeline
                      </button>
                      <button
                        type="button"
                        className="btn-docs"
                        disabled={ocupada === l.id}
                        onClick={() => reanalisar(l)}
                      >
                        reanalisar
                      </button>
                    </span>
                  </td>
                </tr>
                {aberta === l.id && (
                  <tr className="detalhe">
                    <td colSpan={6}>
                      {l.analise ? (
                        <>
                          {l.analise.justificativa && <p><strong>Justificativa da IA:</strong> {l.analise.justificativa}</p>}
                          {l.analise.credenciamento_analise && (
                            <p><strong>Credenciamento:</strong> {l.analise.credenciamento_analise}</p>
                          )}
                          {l.analise.alertas_impugnacao?.length > 0 && (
                            <p><strong>Alertas de impugnação:</strong> {l.analise.alertas_impugnacao.join(' · ')}</p>
                          )}
                        </>
                      ) : (
                        <p>Esta licitação ainda não tem análise da IA{l.status_analise === 'erro' ? ' (a última tentativa falhou)' : ''}. Use "reanalisar" para gerar.</p>
                      )}
                      <p>
                        <strong>Fonte:</strong> {l.fonte} · <strong>Encerramento:</strong> {l.data_encerramento?.slice(0, 10) || '—'}
                        {l.link && <> · <a href={l.link} target="_blank" rel="noreferrer">edital ↗</a></>}
                      </p>
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </>
  )
}
