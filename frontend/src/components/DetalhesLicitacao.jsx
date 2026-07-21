// Detalhes completos de uma licitação + análise, com ações do time:
// suspender/reativar o certame, editar campos (vencimento etc.) e anexar a
// análise em PDF (relatório do time) que atualiza o card e o checklist de docs.
// Usado no modal do kanban (clique no card) e na linha expandida da aba Licitações.
import { useRef, useState } from 'react'
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

// aoMudar: callback do pai para recarregar a lista após editar/suspender/importar análise.
// aoFechar: fecha o modal/linha após excluir (opcional).
export default function DetalhesLicitacao({ licitacao, aoMudar, aoFechar }) {
  const [l, setL] = useState(licitacao)
  const [editando, setEditando] = useState(false)
  const [salvando, setSalvando] = useState(false)
  const [importando, setImportando] = useState(false)
  const [msg, setMsg] = useState('')
  const inputAnalise = useRef(null)
  const [form, setForm] = useState({
    data_encerramento: (licitacao.data_encerramento || '').slice(0, 10),
    data_abertura: (licitacao.data_abertura || '').slice(0, 10),
    valor_estimado: licitacao.valor_estimado ?? '',
    link: licitacao.link || '',
    sistema: licitacao.sistema || '',
    endereco_licitacao: licitacao.endereco_licitacao || '',
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
        : '▶ Reativada. Confira o vencimento (edite se o edital mudou) e, se houver análise nova, anexe o PDF.')
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
        sistema: form.sistema,
        endereco_licitacao: form.endereco_licitacao,
      })
      setL(nova)
      setEditando(false)
      setMsg('✅ Campos atualizados. Se o edital mudou, anexe a análise nova em PDF.')
      aoMudar?.()
    } catch (e) {
      setMsg(`Erro ao salvar: ${e.message}`)
    } finally {
      setSalvando(false)
    }
  }

  async function importarAnalise(e) {
    const arquivo = e.target.files?.[0]
    e.target.value = '' // permite reanexar o mesmo arquivo depois
    if (!arquivo) return
    setImportando(true)
    setMsg('📄 Lendo o PDF da análise e atualizando o card… pode levar 1 a 2 minutos.')
    try {
      const nova = await api.importarAnalisePdf(l.id, arquivo)
      setL(nova)
      const nDocs = nova.analise?.documentos_habilitacao?.length || 0
      setMsg(
        `✅ Análise importada (${nova.analise?.classificacao_final || 'sem classificação'}` +
        (nDocs ? `, ${nDocs} documentos no checklist` : '') +
        ') — card atualizado.'
      )
      aoMudar?.()
    } catch (err) {
      setMsg(
        err.message.includes('422')
          ? '⚠ Este PDF não parece ser o relatório de análise do edital — anexe o PDF da nossa análise.'
          : /50[24]/.test(err.message)
            ? '⚠ A leitura demorou além do limite do servidor. Aguarde alguns segundos e anexe de novo.'
            : `Erro ao importar a análise: ${err.message}`
      )
    } finally {
      setImportando(false)
    }
  }

  async function excluir() {
    const nome = [l.orgao, l.municipio && `${l.municipio}/${l.uf}`].filter(Boolean).join(' — ')
    if (!window.confirm(
      `Excluir DEFINITIVAMENTE a licitação?\n\n${nome}\n\n` +
      'O card, a análise da IA e os documentos anexados serão apagados, ' +
      'e a coleta automática não vai trazê-la de volta. Essa ação não tem desfazer.'
    )) return
    setSalvando(true)
    setMsg('')
    try {
      await api.excluirLicitacao(l.id)
      aoMudar?.()
      aoFechar?.()
    } catch (e) {
      setMsg(`Erro ao excluir: ${e.message}`)
      setSalvando(false)
    }
  }

  const ocupado = salvando || importando
  return (
    <div className="detalhes-lic">
      <div className="detalhes-cabecalho">
        <div>
          <strong>{l.orgao || 'Órgão não informado'}</strong>
          <small>
            {[l.municipio && `${l.municipio}/${l.uf}`, l.modalidade,
              l.sistema && `Sistema: ${l.sistema}`,
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
        <button type="button" disabled={ocupado} onClick={() => inputAnalise.current?.click()}
          title="Anexe o PDF do relatório de análise do time — atualiza classificação, scores e o checklist de documentação">
          {importando ? '⏳ Importando…' : '📄 Anexar análise (PDF)'}
        </button>
        <input ref={inputAnalise} type="file" accept="application/pdf,.pdf"
          style={{ display: 'none' }} onChange={importarAnalise} />
        <button type="button" className="btn-excluir" disabled={ocupado} onClick={excluir}
          title="Exclui a licitação, o card, a análise e os documentos — sem desfazer">
          🗑 Excluir
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
          <label>
            Sistema (onde a disputa corre)
            <input value={form.sistema} placeholder="Ex.: BLL, Portal de Compras Publicas"
              onChange={(e) => setForm({ ...form, sistema: e.target.value })} />
          </label>
          <label>
            Endereço da licitação (link no sistema)
            <input type="url" value={form.endereco_licitacao} placeholder="https://…"
              onChange={(e) => setForm({ ...form, endereco_licitacao: e.target.value })} />
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
          {a.exigencias_habilitacao?.length > 0 && (
            <p><strong>Exigências de habilitação:</strong> {a.exigencias_habilitacao.join(' • ')}</p>
          )}
          {a.exigencias_tecnicas?.length > 0 && (
            <p><strong>Exigências técnicas:</strong> {a.exigencias_tecnicas.join(' • ')}</p>
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
          Ainda sem análise — anexe o PDF do relatório de análise pelo botão acima
          para preencher o card e o checklist de documentação.
        </p>
      )}

      <p className="detalhes-links">
        {l.endereco_licitacao && (
          <a href={l.endereco_licitacao} target="_blank" rel="noreferrer">
            🔗 Abrir a licitação no sistema{l.sistema ? ` (${l.sistema})` : ''} ↗
          </a>
        )}
        {l.link && <a href={l.link} target="_blank" rel="noreferrer">Abrir no portal ↗</a>}
      </p>
    </div>
  )
}
