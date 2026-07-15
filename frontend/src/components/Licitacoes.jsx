import { Fragment, useEffect, useState } from 'react'
import { api } from '../api.js'
import Documentacao from './Documentacao.jsx'
import CampoBusca, { normalizar, contemTermo } from './CampoBusca.jsx'

const brl = (v) =>
  v == null ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

// ISO (YYYY-MM-DD ou datetime) → DD/MM/AAAA
const dataBr = (iso) => {
  if (!iso) return '—'
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a}` : '—'
}

const CORES_VEREDITO = {
  participar: 'verde',
  nao_participar: 'vermelho',
  revisar_manual: 'amarelo',
}

const ROTULO_STATUS = {
  pendente: 'aguardando análise',
  manual: 'cadastro manual',
  erro: 'erro na análise',
}

const CORES_CLASSIFICACAO = {
  'EXCELENTE OPORTUNIDADE': 'verde',
  'BOA OPORTUNIDADE': 'verde',
  'OPORTUNIDADE MODERADA': 'amarelo',
  'ALTO RISCO': 'amarelo',
  'NÃO RECOMENDADO': 'vermelho',
}

export default function Licitacoes() {
  const [itens, setItens] = useState([])
  const [aberta, setAberta] = useState(null)
  const [docsAberta, setDocsAberta] = useState(null)
  const [erro, setErro] = useState('')
  const [msg, setMsg] = useState('')
  const [reanalisando, setReanalisando] = useState(null) // id da licitação em reanálise
  const [busca, setBusca] = useState('')

  const carregar = () => api.licitacoes().then(setItens).catch((e) => setErro(e.message))
  useEffect(() => { carregar() }, [])

  async function reanalisar(l) {
    setReanalisando(l.id)
    setMsg('Reanalisando com IA… isso pode levar um minuto.')
    try {
      const r = await api.reanalisar(l.id)
      setMsg(r.erro ? `⚠ ${r.erro}` : '✅ Reanálise concluída.')
      await carregar()
    } catch (e) {
      setMsg(`Erro na reanálise: ${e.message}`)
    } finally {
      setReanalisando(null)
    }
  }

  // Busca client-side, sem acento — mesmos campos do kanban
  const termo = normalizar(busca.trim())
  const visiveis = !termo
    ? itens
    : itens.filter((l) =>
        contemTermo(termo, [
          l.objeto,
          l.analise?.objeto_resumido,
          l.orgao,
          l.municipio,
          l.uf,
          l.id_externo,
        ])
      )

  if (erro) return <p className="erro">Backend indisponível: {erro}</p>
  if (!itens.length) return <p>Nenhuma licitação coletada ainda. Clique em “Buscar e analisar agora”.</p>

  return (
    <>
    {msg && <div className="banner">{msg}</div>}
    <div className="barra-busca">
      <CampoBusca
        valor={busca}
        aoMudar={setBusca}
        placeholder="Buscar por órgão, objeto, município, UF ou pregão…"
      />
      {termo && (
        <span className="busca-contagem">
          {visiveis.length} de {itens.length} licitações
        </span>
      )}
    </div>
    {!visiveis.length && <p>Nenhuma licitação corresponde à busca.</p>}
    {visiveis.length > 0 && (
    <table className="tabela">
      <thead>
        <tr>
          <th>Órgão</th><th>Objeto</th><th>UF</th><th>Valor</th><th>Identificada em</th><th>Vence em</th><th>Análise IA</th><th>Ações</th>
        </tr>
      </thead>
      <tbody>
        {visiveis.map((l) => (
          <Fragment key={l.id}>
            <tr onClick={() => setAberta(aberta === l.id ? null : l.id)} className="linha">
              <td>{l.orgao}</td>
              <td className="objeto">{l.objeto}</td>
              <td>{l.uf}</td>
              <td>{brl(l.valor_estimado)}</td>
              <td>{dataBr(l.criado_em)}</td>
              <td>{dataBr(l.data_encerramento)}</td>
              <td>
                {l.analise ? (
                  l.analise.classificacao_final ? (
                    <span className={`veredito ${CORES_CLASSIFICACAO[l.analise.classificacao_final] || 'amarelo'}`}>
                      B {l.analise.score_beneficios}/10 • P {l.analise.score_pagamentos}/10 • {l.analise.classificacao_final}
                    </span>
                  ) : (
                    <span className={`veredito ${CORES_VEREDITO[l.analise.veredito]}`}>
                      {l.analise.score} • {l.analise.veredito.replace('_', ' ')}
                    </span>
                  )
                ) : (
                  <span className="pendente">{ROTULO_STATUS[l.status_analise] || l.status_analise}</span>
                )}
              </td>
              <td>
                <span className="acoes-linha" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    className={`btn-docs${docsAberta === l.id ? ' ativo' : ''}`}
                    onClick={() => setDocsAberta(docsAberta === l.id ? null : l.id)}
                  >
                    Documentação
                  </button>
                  <button
                    type="button"
                    className="btn-docs"
                    disabled={reanalisando === l.id}
                    onClick={() => reanalisar(l)}
                    title="Refazer a análise IA desta licitação"
                  >
                    {reanalisando === l.id ? 'reanalisando…' : 'reanalisar'}
                  </button>
                </span>
              </td>
            </tr>
            {docsAberta === l.id && (
              <tr className="detalhe">
                <td colSpan={8}>
                  <Documentacao licitacao={l} aoFechar={() => setDocsAberta(null)} />
                </td>
              </tr>
            )}
            {aberta === l.id && l.analise && (
              <tr className="detalhe">
                <td colSpan={8}>
                  <p><strong>Resumo:</strong> {l.analise.objeto_resumido}</p>
                  {l.analise.classificacao_final && (
                    <p>
                      <strong>Scores:</strong> Prospera Benefícios {l.analise.score_beneficios}/10 •{' '}
                      Prospera Pagamentos {l.analise.score_pagamentos}/10 •{' '}
                      <strong>Classificação:</strong> {l.analise.classificacao_final}
                    </p>
                  )}
                  {l.analise.credenciamento_analise && (
                    <p><strong>Credenciamento:</strong> {l.analise.credenciamento_analise}</p>
                  )}
                  {l.analise.custo_emissao_cartoes && (
                    <p><strong>Custo estimado de emissão:</strong> {l.analise.custo_emissao_cartoes}</p>
                  )}
                  {l.analise.alertas_impugnacao?.length > 0 && (
                    <p><strong>Alertas de impugnação:</strong> {l.analise.alertas_impugnacao.join(' • ')}</p>
                  )}
                  <p><strong>Justificativa:</strong> {l.analise.justificativa}</p>
                  {l.analise.prazos?.length > 0 && (
                    <p><strong>Prazos:</strong> {l.analise.prazos.map((p) => `${p.descricao}: ${p.data_ou_prazo}`).join(' • ')}</p>
                  )}
                  {l.analise.atestados_exigidos?.length > 0 && (
                    <p><strong>Atestados:</strong> {l.analise.atestados_exigidos.join(' • ')}</p>
                  )}
                  {l.analise.riscos?.length > 0 && (
                    <p><strong>⚠ Riscos:</strong> {l.analise.riscos.join(' • ')}</p>
                  )}
                  {l.analise.analise_completa && (
                    <details>
                      <summary><strong>Análise completa (tabelas e seções)</strong></summary>
                      <pre style={{ whiteSpace: 'pre-wrap', overflowX: 'auto' }}>{l.analise.analise_completa}</pre>
                    </details>
                  )}
                  {l.link && <a href={l.link} target="_blank" rel="noreferrer">Abrir no portal ↗</a>}
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
    )}
    </>
  )
}
