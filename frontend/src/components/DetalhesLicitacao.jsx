// Detalhes completos de uma licitação + análise da IA, com ações do time:
// suspender/reativar o certame, editar campos (vencimento etc.) e reanalisar.
// Usado no modal do kanban (clique no card) e na linha expandida da aba Licitações.
import { useState } from 'react'
import { api } from '../api.js'

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

// aoMudar: callback do pai para recarregar a lista após editar/suspender/reanalisar
export default function DetalhesLicitacao({ licitacao, aoMudar }) {
  const [l, setL] = useState(licitacao)
  const [editando, setEditando] = useState(false)
  const [salvando, setSalvando] = useState(false)
  const [reanalisando, setReanalisando] = useState(false)
  const [msg, setMsg] = useState('')
  const [form, setForm] = useState({
    data_encerramento: (licitacao.data_encerramento || '').slice(0, 10),
    data_abertura: (licitacao.data_abertura || '').slice(0, 10),
    valor_estimado: licitacao.valor_estimado ?? '',
    link: licitacao.link || '',
  })
  const a = l.analise

  async function alternarSuspensa() {
    setSalvando(true)
    setMsg('')
    try {
      const nova = await api.atualizarLicitacao(l.id, { suspensa: !l.suspensa })
      setL(nova)
      setMsg(nova.suspensa
        ? '⏸ Marcada como suspensa — o alerta de prazo fica silenciado até reativar.'
        : '▶ Reativada. Confira o vencimento (edite se o edital mudou) e reanalise.')
      aoMudar?.()
    } catch (e) {
      setMsg(`Erro: ${e.message}`)
    } finally {
      setSalvando(false)
    }
  }

  async function salvarEdicao() {
    setSalvando(true)
    setMsg('')
    try {
      const nova = await api.atualizarLicitacao(l.id, {
        data_encerramento: form.data_encerramento,
        data_abertura: form.data_abertura,
        valor_estimado: form.valor_estimado === '' ? null : Number(form.valor_estimado),
        link: form.link,
      })
      setL(nova)
      setEditando(false)
      setMsg('✅ Campos atualizados. Se o edital mudou, vale reanalisar.')
      aoMudar?.()
    } catch (e) {
      setMsg(`Erro ao salvar: ${e.message}`)
    } finally {
      setSalvando(false)
    }
  }

  async function reanalisar() {
    setReanalisando(true)
    setMsg('🔎 Reanalisando com a IA — pode levar 1 a 2 minutos…')
    try {
      const r = await api.reanalisar(l.id)
      setMsg(r.erro ? `⚠ ${r.erro}` : '✅ Reanálise concluída — recarregue os detalhes para ver o resultado novo.')
      aoMudar?.()
    } catch (e) {
      setMsg(`Erro na reanálise: ${e.message}`)
    } finally {
      setReanalisando(false)
    }
  }

  const ocupado = salvando || reanalisando
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
        <span className="detalhes-selos">
          {l.suspensa && <span className="selo-suspensa">Suspensa</span>}
          {a?.classificacao_final && (
            <span className={`veredito ${CORES_CLASSIFICACAO[a.classificacao_final] || 'amarelo'}`}>
              {a.classificacao_final}
            </span>
          )}
        </span>
      </div>

      <div className="detalhes-acoes">
        <button type="button" disabled={ocupado} onClick={alternarSuspensa}>
          {l.suspensa ? '▶ Reativar' : '⏸ Suspender'}
        </button>
        <button type="button" disabled={ocupado} onClick={() => setEditando(!editando)}>
          ✏️ {editando ? 'Cancelar edição' : 'Editar campos'}
        </button>
        <button type="button" disabled={ocupado} onClick={reanalisar}
          title="Refazer a análise IA (use após o edital mudar)">
          {reanalisando ? '⏳ Reanalisando…' : '🔁 Reanalisar'}
        </button>
      </div>
      {msg && <div className="form-msg">{msg}</div>}

      {editando && (
        <div className="detalhes-editar">
          <label>
            Data de vencimento (limite de propostas)
            <input type="date" value={form.data_encerramento}
              onChange={(e) => setForm({ ...form, data_encerramento: e.target.value })} />
          </label>
          <label>
            Data de abertura
            <input type="date" value={form.data_abertura}
              onChange={(e) => setForm({ ...form, data_abertura: e.target.value })} />
          </label>
          <label>
            Valor estimado (R$)
            <input type="number" min="0" step="0.01" value={form.valor_estimado}
              onChange={(e) => setForm({ ...form, valor_estimado: e.target.value })} />
          </label>
          <label>
            Link do edital / portal
            <input type="url" value={form.link}
              onChange={(e) => setForm({ ...form, link: e.target.value })} />
          </label>
          <button type="button" className="primario" disabled={ocupado} onClick={salvarEdicao}>
            {salvando ? '⏳ Salvando…' : 'Salvar alterações'}
          </button>
        </div>
      )}

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
