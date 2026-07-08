import { useEffect, useState } from 'react'
import { api } from '../api.js'

const CATEGORIAS_ORDEM = [
  'HABILITAÇÃO JURÍDICA',
  'REGULARIDADE FISCAL E TRABALHISTA',
  'QUALIFICAÇÃO TÉCNICA',
  'QUALIFICAÇÃO ECONÔMICO-FINANCEIRA',
  'OUTROS DOCUMENTOS / DECLARAÇÕES',
]

const MAX_MB = 25

const fmtTamanho = (b) =>
  b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`

function Anexo({ anexo, aoExcluir }) {
  return (
    <span className="doc-anexo">
      <a href={api.urlDownloadDocumento(anexo.id)} title={`Baixar (${fmtTamanho(anexo.tamanho)})`}>
        {anexo.nome_arquivo}
      </a>
      <small>{fmtTamanho(anexo.tamanho)}</small>
      <button type="button" className="doc-excluir" title="Excluir anexo" onClick={() => aoExcluir(anexo)}>
        ×
      </button>
    </span>
  )
}

function BotaoAnexar({ rotulo, aoEscolher, desabilitado }) {
  return (
    <label className={`btn-anexar${desabilitado ? ' desabilitado' : ''}`}>
      {rotulo}
      <input
        type="file"
        hidden
        disabled={desabilitado}
        onChange={(e) => {
          const arquivo = e.target.files?.[0]
          e.target.value = ''
          if (arquivo) aoEscolher(arquivo)
        }}
      />
    </label>
  )
}

export default function Documentacao({ licitacao, aoFechar }) {
  const [dados, setDados] = useState(null)
  const [erro, setErro] = useState('')
  const [msg, setMsg] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [reanalisando, setReanalisando] = useState(false)
  const [itemAvulso, setItemAvulso] = useState('')

  const carregar = () =>
    api.documentos(licitacao.id).then(setDados).catch((e) => setErro(e.message))

  useEffect(() => {
    carregar()
  }, [licitacao.id])

  async function anexar(arquivo, itemChecklist = '') {
    if (arquivo.size > MAX_MB * 1024 * 1024) {
      setMsg(`"${arquivo.name}" excede o limite de ${MAX_MB} MB.`)
      return
    }
    setEnviando(true)
    setMsg('')
    try {
      await api.anexarDocumento(licitacao.id, arquivo, itemChecklist)
      await carregar()
    } catch (e) {
      setMsg(`Falha ao anexar "${arquivo.name}": ${e.message}`)
    } finally {
      setEnviando(false)
    }
  }

  async function reanalisar() {
    setReanalisando(true)
    setMsg('')
    try {
      await api.reanalisar(licitacao.id)
      await carregar()
    } catch (e) {
      setMsg(`Falha ao reanalisar: ${e.message}`)
    } finally {
      setReanalisando(false)
    }
  }

  async function excluir(anexo) {
    if (!window.confirm(`Excluir o anexo "${anexo.nome_arquivo}"?`)) return
    setMsg('')
    try {
      await api.excluirDocumento(anexo.id)
      await carregar()
    } catch (e) {
      setMsg(`Falha ao excluir: ${e.message}`)
    }
  }

  if (erro) return <p className="erro">Falha ao carregar a documentação: {erro}</p>
  if (!dados) return <p className="pendente">Carregando documentação…</p>

  const { checklist, anexos_avulsos: avulsos } = dados
  const categorias = [...CATEGORIAS_ORDEM, ...checklist.map((i) => i.categoria)]
    .filter((c, i, arr) => arr.indexOf(c) === i)
    .map((cat) => ({ cat, itens: checklist.filter((i) => i.categoria === cat) }))
    .filter((g) => g.itens.length > 0)
  const concluidos = checklist.filter((i) => i.anexos.length > 0).length

  return (
    <div className="docs">
      <div className="docs-topo">
        <strong>Documentação para habilitação</strong>
        {dados.tem_checklist && (
          <span className="docs-progresso">
            {concluidos}/{checklist.length} documentos anexados
          </span>
        )}
        {aoFechar && (
          <button type="button" className="doc-fechar" title="Fechar" onClick={aoFechar}>
            ✕
          </button>
        )}
      </div>

      {msg && <div className="form-msg">{msg}</div>}

      {!dados.tem_checklist && (
        <div className="docs-aviso">
          {reanalisando ? (
            <>Reanalisando o edital com a IA — pode levar 1 a 2 minutos…</>
          ) : (
            <>
              Esta licitação ainda não tem checklist de documentos. Reanalise-a para extrair o
              checklist do edital. Enquanto isso, você pode anexar documentos avulsos abaixo.
            </>
          )}
          <button type="button" className="primario" disabled={reanalisando} onClick={reanalisar}>
            {reanalisando ? 'Reanalisando…' : 'Reanalisar agora'}
          </button>
        </div>
      )}

      {categorias.map(({ cat, itens }) => (
        <div key={cat} className="docs-categoria">
          <h4>{cat}</h4>
          {itens.map((item) => (
            <div key={item.documento} className="doc-item">
              <span className={`doc-status ${item.anexos.length ? 'ok' : ''}`}>
                {item.anexos.length ? '✓' : '○'}
              </span>
              <div className="doc-info">
                <span className="doc-nome">{item.documento}</span>
                {item.referencia_edital && <small>Ref.: {item.referencia_edital}</small>}
                {item.anexos.length > 0 && (
                  <div className="doc-anexos">
                    {item.anexos.map((a) => (
                      <Anexo key={a.id} anexo={a} aoExcluir={excluir} />
                    ))}
                  </div>
                )}
              </div>
              <BotaoAnexar
                rotulo={enviando ? '…' : item.anexos.length ? '+ Anexar outro' : '+ Anexar'}
                desabilitado={enviando}
                aoEscolher={(arq) => anexar(arq, item.documento)}
              />
            </div>
          ))}
        </div>
      ))}

      <div className="docs-avulso">
        <h4>Anexos avulsos</h4>
        {avulsos.length > 0 && (
          <div className="doc-anexos">
            {avulsos.map((a) => (
              <div key={a.id} className="doc-item avulso">
                <span className="doc-status ok">✓</span>
                <div className="doc-info">
                  {a.item_checklist && <span className="doc-nome">{a.item_checklist}</span>}
                  <div className="doc-anexos">
                    <Anexo anexo={a} aoExcluir={excluir} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="docs-avulso-form">
          <input
            type="text"
            placeholder="Descrição do documento (opcional)"
            value={itemAvulso}
            onChange={(e) => setItemAvulso(e.target.value)}
          />
          <BotaoAnexar
            rotulo={enviando ? 'Enviando…' : '+ Anexar avulso'}
            desabilitado={enviando}
            aoEscolher={(arq) => {
              anexar(arq, itemAvulso.trim())
              setItemAvulso('')
            }}
          />
        </div>
        <small className="doc-limite">Qualquer formato, até {MAX_MB} MB por arquivo. Os arquivos ficam salvos na base de dados.</small>
      </div>
    </div>
  )
}
