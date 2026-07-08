import { Fragment, useEffect, useState } from 'react'
import { api } from '../api.js'
import Documentacao from './Documentacao.jsx'

const brl = (v) =>
  v == null ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

const CORES_VEREDITO = {
  participar: 'verde',
  nao_participar: 'vermelho',
  revisar_manual: 'amarelo',
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

  useEffect(() => {
    api.licitacoes().then(setItens).catch((e) => setErro(e.message))
  }, [])

  if (erro) return <p className="erro">Backend indisponível: {erro}</p>
  if (!itens.length) return <p>Nenhuma licitação coletada ainda. Clique em “Buscar e analisar agora”.</p>

  return (
    <table className="tabela">
      <thead>
        <tr>
          <th>Órgão</th><th>Objeto</th><th>UF</th><th>Valor</th><th>Encerramento</th><th>Análise IA</th><th>Docs</th>
        </tr>
      </thead>
      <tbody>
        {itens.map((l) => (
          <Fragment key={l.id}>
            <tr onClick={() => setAberta(aberta === l.id ? null : l.id)} className="linha">
              <td>{l.orgao}</td>
              <td className="objeto">{l.objeto}</td>
              <td>{l.uf}</td>
              <td>{brl(l.valor_estimado)}</td>
              <td>{l.data_encerramento?.slice(0, 10) || '—'}</td>
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
                  <span className="pendente">{l.status_analise}</span>
                )}
              </td>
              <td>
                <button
                  type="button"
                  className={`btn-docs${docsAberta === l.id ? ' ativo' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    setDocsAberta(docsAberta === l.id ? null : l.id)
                  }}
                >
                  Documentação
                </button>
              </td>
            </tr>
            {docsAberta === l.id && (
              <tr className="detalhe">
                <td colSpan={7}>
                  <Documentacao licitacao={l} aoFechar={() => setDocsAberta(null)} />
                </td>
              </tr>
            )}
            {aberta === l.id && l.analise && (
              <tr className="detalhe">
                <td colSpan={7}>
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
  )
}
