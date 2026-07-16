import { useState } from 'react'
import { api } from '../api.js'

const FORM_VAZIO = {
  objeto: '',
  orgao: '',
  municipio: '',
  uf: '',
  modalidade: '',
  numero_certame: '',
  valor_estimado: '',
  data_abertura: '',
  data_encerramento: '',
  link: '',
  observacoes: '',
  responsavel: '',
}

// ISO (YYYY-MM-DD ou datetime) → DD/MM/AAAA
const dataBr = (iso) => {
  if (!iso) return null
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a}` : null
}

const MODALIDADES = [
  'Pregão Eletrônico', 'Pregão Presencial', 'Concorrência', 'Dispensa de Licitação',
  'Inexigibilidade', 'Credenciamento', 'Leilão', 'Diálogo Competitivo',
]

export default function CadastroManual() {
  const [form, setForm] = useState(FORM_VAZIO)
  const [resumo, setResumo] = useState('')
  const [linkAuto, setLinkAuto] = useState('')
  const [pdfAuto, setPdfAuto] = useState(null)
  const [extraindo, setExtraindo] = useState(false)
  const [salvando, setSalvando] = useState(false)
  const [msg, setMsg] = useState('')

  const set = (campo) => (e) => setForm({ ...form, [campo]: e.target.value })

  async function preencherAutomatico() {
    if (!pdfAuto && !resumo.trim() && !linkAuto.trim()) {
      setMsg('⚠ Anexe o PDF do edital, cole o resumo ou informe o link para preencher automaticamente.')
      return
    }
    setExtraindo(true)
    setMsg(
      pdfAuto
        ? '🔎 Lendo o PDF do edital e preenchendo os campos… PDFs grandes podem levar 1 a 2 minutos.'
        : '🔎 Lendo o conteúdo e preenchendo os campos… isso leva alguns segundos.'
    )
    try {
      const c = pdfAuto
        ? await api.extrairLicitacaoPdf(pdfAuto)
        : await api.extrairLicitacao(resumo, linkAuto)
      setForm((f) => ({
        ...f,
        objeto: c.objeto || f.objeto,
        orgao: c.orgao || f.orgao,
        municipio: c.municipio || f.municipio,
        uf: c.uf || f.uf,
        modalidade: c.modalidade || f.modalidade,
        numero_certame: c.numero_certame || f.numero_certame,
        valor_estimado: c.valor_estimado ?? f.valor_estimado,
        data_abertura: c.data_abertura || f.data_abertura,
        data_encerramento: c.data_encerramento || f.data_encerramento,
        link: c.link || f.link,
        responsavel: c.responsavel || f.responsavel,
        observacoes: c.observacoes || f.observacoes,
      }))
      setMsg('✅ Campos preenchidos — revise abaixo e clique em "Cadastrar licitação".')
    } catch (e) {
      setMsg(`⚠ Não consegui preencher automaticamente: ${e.message}`)
    } finally {
      setExtraindo(false)
    }
  }

  async function salvar() {
    if (!form.objeto.trim()) {
      setMsg('⚠ Informe o objeto/título da licitação.')
      return
    }
    setSalvando(true)
    setMsg('Cadastrando…')
    try {
      const r = await api.criarLicitacao({
        ...form,
        uf: form.uf.trim().toUpperCase(),
        valor_estimado: form.valor_estimado === '' ? null : Number(form.valor_estimado),
        edital_url: form.link,
      })
      const identificada = dataBr(r.criado_em)
      setMsg(
        `✅ Licitação cadastrada (nº ${r.id_externo})` +
        (identificada ? ` — identificada em ${identificada}` : '') +
        ' — e adicionada ao Pipeline.'
      )
      setForm(FORM_VAZIO)
      setResumo('')
      setLinkAuto('')
      setPdfAuto(null)
    } catch (e) {
      setMsg(
        e.message.includes('409')
          ? '⚠ Essa licitação já está no pipeline (mesmo número de certame).'
          : `Erro ao cadastrar: ${e.message}`
      )
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="perfil">
      <div className="auto-preencher">
        <h3>Preenchimento automático</h3>
        <p className="auto-dica">
          Cole o resumo/aviso da licitação ou o link do portal — a IA preenche o formulário
          para você revisar.
        </p>
        <label>
          Resumo / texto da licitação
          <textarea rows={4} value={resumo} onChange={(e) => setResumo(e.target.value)}
            placeholder="Cole aqui o aviso, o resumo do edital ou qualquer texto com os dados da licitação…" />
        </label>
        <label>
          Ou o link da licitação (página do portal ou PDF do edital)
          <input type="url" value={linkAuto} onChange={(e) => setLinkAuto(e.target.value)}
            placeholder="https://…" />
        </label>
        <label>
          Ou anexe o PDF do edital (até 19 MB) — tem prioridade sobre o resumo/link
          <input
            type="file"
            accept="application/pdf,.pdf"
            onChange={(e) => setPdfAuto(e.target.files?.[0] || null)}
          />
        </label>
        {pdfAuto && (
          <p className="auto-dica">
            📎 {pdfAuto.name} ({(pdfAuto.size / 1024 / 1024).toFixed(1)} MB){' '}
            <button type="button" className="doc-excluir" title="Remover PDF"
              onClick={() => setPdfAuto(null)}>×</button>
          </p>
        )}
        <button className="primario" onClick={preencherAutomatico} disabled={extraindo || salvando}>
          {extraindo ? '⏳ Preenchendo…' : '✨ Preencher automaticamente'}
        </button>
      </div>

      <div className="grade">
        <label>
          Objeto / título da licitação *
          <textarea rows={3} value={form.objeto} onChange={set('objeto')}
            placeholder="Ex.: Contratação de empresa para fornecimento de vale-alimentação aos servidores…" />
        </label>
        <label>
          Órgão
          <input value={form.orgao} onChange={set('orgao')} placeholder="Ex.: Prefeitura Municipal de Caxias do Sul" />
        </label>
        <label>
          Modalidade
          <input list="modalidades" value={form.modalidade} onChange={set('modalidade')} placeholder="Ex.: Pregão Eletrônico" />
          <datalist id="modalidades">
            {MODALIDADES.map((m) => <option key={m} value={m} />)}
          </datalist>
        </label>
        <label>
          Município
          <input value={form.municipio} onChange={set('municipio')} />
        </label>
        <label>
          UF
          <input value={form.uf} onChange={set('uf')} maxLength={2} placeholder="Ex.: RS" />
        </label>
        <label>
          Número do certame
          <input value={form.numero_certame} onChange={set('numero_certame')} placeholder="Ex.: PE 45/2026" />
        </label>
        <label>
          Valor estimado (R$)
          <input type="number" min="0" step="0.01" value={form.valor_estimado} onChange={set('valor_estimado')} />
        </label>
        <label>
          Data de abertura
          <input type="date" value={form.data_abertura} onChange={set('data_abertura')} />
        </label>
        <label>
          Data de vencimento (limite de propostas)
          <input type="date" value={form.data_encerramento} onChange={set('data_encerramento')} />
        </label>
        <label>
          Link do edital / portal
          <input type="url" value={form.link} onChange={set('link')} placeholder="https://…" />
        </label>
        <label>
          Responsável
          <input value={form.responsavel} onChange={set('responsavel')} />
        </label>
        <label>
          Observações
          <textarea rows={3} value={form.observacoes} onChange={set('observacoes')}
            placeholder="Notas internas — vão para o cartão da oportunidade no Pipeline" />
        </label>
      </div>
      <p className="auto-dica">
        O registro manual entra direto como oportunidade no Pipeline, sem passar pela análise IA.
      </p>
      <button className="primario" onClick={salvar} disabled={salvando || extraindo}>
        {salvando ? '⏳ Cadastrando…' : 'Cadastrar licitação'}
      </button>
      {msg && <p className="form-msg">{msg}</p>}
    </div>
  )
}
