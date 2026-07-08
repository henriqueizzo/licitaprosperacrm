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
  criar_oportunidade: true,
  analisar: false,
}

const MODALIDADES = [
  'Pregão Eletrônico', 'Pregão Presencial', 'Concorrência', 'Dispensa de Licitação',
  'Inexigibilidade', 'Credenciamento', 'Leilão', 'Diálogo Competitivo',
]

export default function CadastroManual() {
  const [form, setForm] = useState(FORM_VAZIO)
  const [salvando, setSalvando] = useState(false)
  const [msg, setMsg] = useState('')

  const set = (campo) => (e) => setForm({ ...form, [campo]: e.target.value })
  const setCheck = (campo) => (e) => setForm({ ...form, [campo]: e.target.checked })

  async function salvar() {
    if (!form.objeto.trim()) {
      setMsg('⚠ Informe o objeto/título da licitação.')
      return
    }
    setSalvando(true)
    setMsg(form.analisar ? 'Cadastrando e analisando com IA… isso pode levar um minuto.' : 'Cadastrando…')
    try {
      const r = await api.criarLicitacao({
        ...form,
        uf: form.uf.trim().toUpperCase(),
        valor_estimado: form.valor_estimado === '' ? null : Number(form.valor_estimado),
        edital_url: form.link,
      })
      let texto = `✅ Licitação cadastrada (nº ${r.id_externo})`
      texto += r.oportunidade_id ? ' e oportunidade criada no Pipeline.' : '.'
      if (r.analise_pipeline?.erro) texto += ` ⚠ ${r.analise_pipeline.erro}`
      else if (r.analise_pipeline) texto += ` Análise IA concluída: ${r.analise_pipeline.analisadas} analisada(s).`
      setMsg(texto)
      setForm(FORM_VAZIO)
    } catch (e) {
      setMsg(
        e.message.includes('409')
          ? '⚠ Já existe uma licitação manual com esse número de certame.'
          : `Erro ao cadastrar: ${e.message}`
      )
    } finally {
      setSalvando(false)
    }
  }

  return (
    <div className="perfil">
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
          Data de encerramento (prazo)
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
      <label className="check">
        <input type="checkbox"
          checked={form.criar_oportunidade} onChange={setCheck('criar_oportunidade')} />
        Criar oportunidade no Pipeline
      </label>
      <label className="check">
        <input type="checkbox"
          checked={form.analisar} onChange={setCheck('analisar')} />
        Analisar com IA após cadastrar (usa o link do edital, se houver)
      </label>
      <button className="primario" onClick={salvar} disabled={salvando}>
        {salvando ? '⏳ Cadastrando…' : 'Cadastrar licitação'}
      </button>
      {msg && <p className="form-msg">{msg}</p>}
    </div>
  )
}
