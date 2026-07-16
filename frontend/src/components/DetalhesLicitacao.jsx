// Detalhes completos de uma licitação + análise da IA.
// Usado no modal do kanban (clique no card) e na linha expandida da aba Licitações.

const brl = (v) =>
  v == null ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

const dataBr = (iso) => {
  if (!iso) return '—'
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a}` : '—'
}

const CORES_CLASSIFICACAO = {
  'EXCELENTE OPORTUNIDADE': 'verde',
  'BOA OPORTUNIDADE': 'azul',
  'OPORTUNIDADE MODERADA': 'amarelo',
  'ALTO RISCO': 'amarelo',
  'NÃO RECOMENDADO': 'vermelho',
}

const FONTES = { pncp: 'PNCP', fiesc: 'FIESC', fiergs: 'FIERGS', fiems: 'FIEMS', manual: 'Cadastro manual' }

export default function DetalhesLicitacao({ licitacao: l }) {
  const a = l.analise
  return (
    <div className="detalhes-lic">
      <div className="detalhes-cabecalho">
        <div>
          <strong>{l.orgao || 'Órgão não informado'}</strong>
          <small>
            {[l.municipio && `${l.municipio}/${l.uf}`, l.modalidade,
              l.id_externo && `nº ${l.id_externo}`, FONTES[l.fonte] || l.fonte]
              .filter(Boolean).join(' · ')}
          </small>
        </div>
        {a?.classificacao_final && (
          <span className={`veredito ${CORES_CLASSIFICACAO[a.classificacao_final] || 'amarelo'}`}>
            {a.classificacao_final}
          </span>
        )}
      </div>

      <div className="detalhes-meta">
        <span><small>Valor estimado</small><strong>{brl(l.valor_estimado)}</strong></span>
        <span><small>Identificada em</small><strong>{dataBr(l.criado_em)}</strong></span>
        <span><small>Abertura</small><strong>{dataBr(l.data_abertura)}</strong></span>
        <span><small>Vence em</small><strong>{dataBr(l.data_encerramento)}</strong></span>
        {a?.classificacao_final && (
          <span><small>Scores da IA</small>
            <strong>B {a.score_beneficios}/10 · P {a.score_pagamentos}/10</strong></span>
        )}
      </div>

      <p><strong>Objeto:</strong> {l.objeto || '—'}</p>

      {a ? (
        <>
          {a.objeto_resumido && <p><strong>Resumo da IA:</strong> {a.objeto_resumido}</p>}
          {a.credenciamento_analise && (
            <p><strong>Credenciamento:</strong> {a.credenciamento_analise}</p>
          )}
          {a.custo_emissao_cartoes && (
            <p><strong>Custo estimado de emissão:</strong> {a.custo_emissao_cartoes}</p>
          )}
          {a.alertas_impugnacao?.length > 0 && (
            <p><strong>Alertas de impugnação:</strong> {a.alertas_impugnacao.join(' • ')}</p>
          )}
          {a.justificativa && <p><strong>Justificativa:</strong> {a.justificativa}</p>}
          {a.prazos?.length > 0 && (
            <p><strong>Prazos:</strong> {a.prazos.map((p) => `${p.descricao}: ${p.data_ou_prazo}`).join(' • ')}</p>
          )}
          {a.atestados_exigidos?.length > 0 && (
            <p><strong>Atestados:</strong> {a.atestados_exigidos.join(' • ')}</p>
          )}
          {a.riscos?.length > 0 && <p><strong>⚠ Riscos:</strong> {a.riscos.join(' • ')}</p>}
          {a.analise_completa && (
            <details>
              <summary><strong>Análise completa (tabelas e seções)</strong></summary>
              <pre style={{ whiteSpace: 'pre-wrap', overflowX: 'auto' }}>{a.analise_completa}</pre>
            </details>
          )}
        </>
      ) : (
        <p className="pendente">
          {l.status_analise === 'manual'
            ? 'Cadastro manual — sem análise IA (use "reanalisar" na aba Licitações se quiser uma).'
            : 'Ainda sem análise da IA.'}
        </p>
      )}

      {l.link && <a href={l.link} target="_blank" rel="noreferrer">Abrir no portal ↗</a>}
    </div>
  )
}
