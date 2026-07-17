import { useEffect, useRef, useState } from 'react'
import {
  DndContext,
  DragOverlay,
  MouseSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import { api } from '../api.js'
import Documentacao from './Documentacao.jsx'
import CampoBusca, { normalizar, contemTermo } from './CampoBusca.jsx'
import DetalhesLicitacao from './DetalhesLicitacao.jsx'
import Janela from './Janela.jsx'
import FiltrosSelects, { diasParaVencer, passaClassificacao, passaSituacao, passaVencimento } from './Filtros.jsx'

const ESTAGIOS = [
  { id: 'identificada', rotulo: 'Identificada' },
  { id: 'em_analise', rotulo: 'Em análise' },
  { id: 'impugnacao', rotulo: 'Impugnação' },
  { id: 'proposta_enviada', rotulo: 'Proposta enviada' },
  { id: 'disputa', rotulo: 'Disputa' },
  { id: 'ganhou', rotulo: 'Ganhou 🏆' },
  { id: 'perdeu_nogo', rotulo: 'Perdeu / No Go' },
]

// Classificação da IA → rótulo curto + matiz pastel (verde/azul/amarelo/vermelho)
const CLASSIFICACAO_VISUAL = {
  'EXCELENTE OPORTUNIDADE': { rotulo: 'Excelente oportunidade', tom: 'verde' },
  'BOA OPORTUNIDADE': { rotulo: 'Boa oportunidade', tom: 'azul' },
  'OPORTUNIDADE MODERADA': { rotulo: 'Moderada — revisar', tom: 'amarelo' },
  'ALTO RISCO': { rotulo: 'Alto risco — revisar', tom: 'amarelo' },
  'NÃO RECOMENDADO': { rotulo: 'Não recomendado', tom: 'vermelho' },
}

// ISO (YYYY-MM-DD ou datetime) → DD/MM/AAAA
const dataBr = (iso) => {
  if (!iso) return null
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a}` : null
}

// Estado visual do cartão pela proximidade do vencimento — só em estágios ativos.
// Certame suspenso: prazo antigo não vale, alerta silenciado até reativar.
const estadoPrazo = (op) => {
  if (op.licitacao?.suspensa) return ''
  if (op.estagio === 'ganhou' || op.estagio === 'perdeu_nogo') return ''
  const dias = diasParaVencer(op.licitacao?.data_encerramento)
  if (dias == null) return ''
  if (dias < 0) return 'prazo-vencida'
  if (dias <= 7) return 'prazo-vermelho'
  if (dias <= 14) return 'prazo-amarelo'
  return ''
}

// Contagem regressiva no lugar da data ("Vence em 5d") — a data completa fica no title
const textoVencimento = (dias) => {
  if (dias == null) return null
  if (dias < 0) return dias === -1 ? 'Venceu ontem' : `Venceu há ${-dias}d`
  if (dias === 0) return 'Vence hoje'
  if (dias === 1) return 'Vence amanhã'
  return `Vence em ${dias}d`
}

// Iniciais do responsável para o chip ("Matheus Silva" → "MS")
const iniciais = (nome) => {
  const partes = String(nome).trim().split(/\s+/).filter(Boolean)
  return partes.length ? (partes[0][0] + (partes[1]?.[0] || '')).toUpperCase() : '?'
}

const brlCompacto = (v) =>
  v == null
    ? null
    : v.toLocaleString('pt-BR', {
        style: 'currency',
        currency: 'BRL',
        notation: 'compact',
        maximumFractionDigits: 1,
      })

// Coluna do kanban: alvo de soltura do drag & drop (realce quando o cartão paira)
function Coluna({ estagio, rotulo, contagem, children }) {
  const { setNodeRef, isOver } = useDroppable({ id: estagio })
  return (
    <div ref={setNodeRef} className={`coluna${isOver ? ' solta-aqui' : ''}`}>
      <h3>{rotulo} <span>{contagem}</span></h3>
      {children}
    </div>
  )
}

// Conteúdo do cartão, sem hooks de arraste: usado dentro da coluna (via Cartao)
// e clonado no DragOverlay — que segue o ponteiro por cima de tudo, sem ser
// recortado pela rolagem vertical das colunas
function CartaoVisual({
  op, aoAbrir, aoAbrirDocs, aoMover, aoExcluir, aoSalvarResponsavel,
  foiArraste, refArraste, atributos, classesExtra,
}) {
  const [editandoResp, setEditandoResp] = useState(false)

  const prazo = estadoPrazo(op)
  const lic = op.licitacao
  const analise = lic?.analise
  const visual = CLASSIFICACAO_VISUAL[analise?.classificacao_final]
  const titulo = [
    lic?.orgao || 'Órgão não informado',
    lic?.municipio ? `${lic.municipio}/${lic.uf}` : null,
  ].filter(Boolean).join(' — ')
  const identificada = dataBr(lic?.criado_em)
  const vencimento = dataBr(lic?.data_encerramento)
  const contagemVenc = textoVencimento(diasParaVencer(lic?.data_encerramento))
  const docs = lic?.documentos
  const docsRotulo =
    docs?.itens > 0 ? `docs ${docs.anexados}/${docs.itens}`
    : docs?.avulsos > 0 ? `docs (${docs.avulsos})`
    : 'docs'
  const docsCompleto = docs?.itens > 0 && docs.anexados >= docs.itens

  async function enviarResponsavel(e) {
    e.preventDefault()
    const nome = new FormData(e.target).get('nome').trim()
    setEditandoResp(false)
    if (nome !== (op.responsavel || '')) await aoSalvarResponsavel?.(op, nome)
  }

  return (
    <div
      ref={refArraste}
      {...atributos}
      className={[
        'cartao clicavel',
        prazo,
        visual ? `faixa-${visual.tom}` : '',
        classesExtra || '',
      ].filter(Boolean).join(' ')}
      title="Clique para ver os detalhes · arraste para mudar de estágio"
      onClick={() => !foiArraste?.() && lic && aoAbrir?.(lic)}
    >
      <div className="cartao-topo">
        <strong className="cartao-titulo" title={titulo}>{titulo}</strong>
        <span
          className={`resp-chip${op.responsavel ? '' : ' vazio'}`}
          title={op.responsavel ? `Responsável: ${op.responsavel} — clique para trocar` : 'Atribuir responsável'}
          onClick={(e) => { e.stopPropagation(); setEditandoResp((v) => !v) }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {op.responsavel ? iniciais(op.responsavel) : '+'}
        </span>
        {lic?.suspensa && <span className="selo-suspensa">Suspensa</span>}
        {prazo === 'prazo-vencida' && <span className="selo-vencida">Vencida</span>}
      </div>
      {editandoResp && (
        <form
          className="resp-form"
          onSubmit={enviarResponsavel}
          onClick={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <input
            name="nome"
            list="resp-sugestoes"
            defaultValue={op.responsavel || ''}
            placeholder="Nome do responsável"
            autoFocus
          />
          <button type="submit" title="Salvar responsável">ok</button>
          <button type="button" title="Cancelar" onClick={() => setEditandoResp(false)}>×</button>
        </form>
      )}
      <p className="cartao-resumo">{analise?.objeto_resumido || lic?.objeto}</p>
      <div className="cartao-ia">
        {visual ? (
          <>
            <span className={`veredito ${visual.tom}`} title={analise.classificacao_final}>
              {visual.rotulo}
            </span>
            {analise.score_beneficios != null && analise.score_pagamentos != null && (
              <small className="cartao-scores">
                B {analise.score_beneficios} · P {analise.score_pagamentos}
              </small>
            )}
          </>
        ) : (
          <span className="veredito cinza">aguardando análise</span>
        )}
      </div>
      <small className="cartao-meta">
        {brlCompacto(lic?.valor_estimado) && (
          <span className="cartao-valor">{brlCompacto(lic.valor_estimado)}</span>
        )}
        {identificada && (
          <span title={`Identificada em ${identificada}`}>Ident. {identificada}</span>
        )}
        {contagemVenc && (
          <span className="cartao-venc" title={`Vencimento: ${vencimento}`}>{contagemVenc}</span>
        )}
      </small>
      <div className="acoes" onClick={(e) => e.stopPropagation()} onPointerDown={(e) => e.stopPropagation()}>
        <button title="Voltar estágio" aria-label="Voltar estágio" onClick={() => aoMover?.(op, -1)}>←</button>
        {lic && (
          <button className={docsCompleto ? 'docs-completo' : ''} onClick={() => aoAbrirDocs?.(lic)}>
            {docsRotulo}
          </button>
        )}
        {lic?.link && (
          <a href={lic.link} target="_blank" rel="noreferrer">edital ↗</a>
        )}
        <button className="btn-excluir" title="Exclui a licitação, o card, a análise e os documentos — sem desfazer"
          aria-label="Excluir licitação" onClick={() => aoExcluir?.(op)}>🗑</button>
        <button title="Avançar estágio" aria-label="Avançar estágio" onClick={() => aoMover?.(op, 1)}>→</button>
      </div>
    </div>
  )
}

// Casca arrastável do cartão: registra o drag e apaga o original enquanto o
// clone anda no DragOverlay
function Cartao(props) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: props.op.id })
  return (
    <CartaoVisual
      {...props}
      refArraste={setNodeRef}
      atributos={{ ...listeners, ...attributes }}
      classesExtra={isDragging ? 'fantasma' : ''}
    />
  )
}

export default function Pipeline() {
  const [ops, setOps] = useState([])
  const [lics, setLics] = useState(null)
  const [erro, setErro] = useState('')
  const [docsLic, setDocsLic] = useState(null) // licitação com modal de documentação aberto
  const [detalheLic, setDetalheLic] = useState(null) // licitação com modal de detalhes aberto
  const [busca, setBusca] = useState('')
  const [ufFiltro, setUfFiltro] = useState('todas')
  const [classFiltro, setClassFiltro] = useState('todas')
  const [vencFiltro, setVencFiltro] = useState('qualquer')
  const [sitFiltro, setSitFiltro] = useState('todas')
  const [opArrastada, setOpArrastada] = useState(null) // clone no DragOverlay
  // Momento do fim do último arraste: o click que o navegador dispara logo
  // depois do drop não deve abrir o modal de detalhes
  const fimArraste = useRef(0)

  // Mouse: 6px de tolerância separa clique de arraste; touch: segurar 250ms
  // inicia o arraste sem brigar com a rolagem das colunas
  const sensores = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
  )

  const carregar = () => api.oportunidades().then(setOps).catch((e) => setErro(e.message))
  useEffect(() => {
    carregar()
    api.licitacoes().then(setLics).catch(() => {})
  }, [])

  const abertas = ops.filter((o) => o.estagio !== 'ganhou' && o.estagio !== 'perdeu_nogo')
  const ganhas = ops.filter((o) => o.estagio === 'ganhou')
  const perdidas = ops.filter((o) => o.estagio === 'perdeu_nogo')
  const valorEmDisputa = abertas.reduce((soma, o) => soma + (o.licitacao?.valor_estimado || 0), 0)
  const responsaveis = [...new Set(ops.map((o) => (o.responsavel || '').trim()).filter(Boolean))].sort()

  // Busca client-side (dados já carregados): texto sem acento + filtros rápidos
  // de UF, classificação da IA e proximidade do vencimento
  const termo = normalizar(busca.trim())
  const filtroAtivo =
    termo !== '' || ufFiltro !== 'todas' || classFiltro !== 'todas' ||
    vencFiltro !== 'qualquer' || sitFiltro !== 'todas'
  const opsVisiveis = !filtroAtivo
    ? ops
    : ops.filter((o) => {
        const lic = o.licitacao
        if (ufFiltro !== 'todas' && lic?.uf !== ufFiltro) return false
        if (!passaClassificacao(lic?.analise, classFiltro)) return false
        if (!passaVencimento(lic?.data_encerramento, vencFiltro)) return false
        if (!passaSituacao(lic, sitFiltro)) return false
        if (!termo) return true
        return contemTermo(termo, [
          lic?.objeto,
          lic?.analise?.objeto_resumido,
          lic?.orgao,
          lic?.municipio,
          lic?.uf,
          lic?.id_externo,
          o.responsavel,
        ])
      })

  async function mudarEstagio(op, destino) {
    // Atualização otimista: o cartão fica na coluna de destino enquanto a API responde
    setOps((prev) => prev.map((o) => (o.id === op.id ? { ...o, estagio: destino } : o)))
    try {
      await api.moverOportunidade(op.id, destino)
    } catch (e) {
      window.alert(`Não foi possível mover: ${e.message}`)
    }
    carregar()
  }

  async function mover(op, direcao) {
    const i = ESTAGIOS.findIndex((e) => e.id === op.estagio)
    const destino = ESTAGIOS[i + direcao]
    if (!destino) return
    await mudarEstagio(op, destino.id)
  }

  function aoIniciarArraste(ev) {
    setOpArrastada(ops.find((o) => o.id === ev.active.id) || null)
  }

  function aoTerminarArraste(ev) {
    setOpArrastada(null)
    fimArraste.current = Date.now()
    const destino = ev.over?.id
    const op = ops.find((o) => o.id === ev.active.id)
    if (!destino || !op || op.estagio === destino) return
    mudarEstagio(op, destino)
  }

  async function excluir(op) {
    const lic = op.licitacao
    if (!lic) return
    const nome = [lic.orgao, lic.municipio && `${lic.municipio}/${lic.uf}`].filter(Boolean).join(' — ')
    if (!window.confirm(
      `Excluir DEFINITIVAMENTE a licitação?\n\n${nome}\n\n` +
      'O card, a análise da IA e os documentos anexados serão apagados, ' +
      'e a coleta automática não vai trazê-la de volta. Essa ação não tem desfazer.'
    )) return
    try {
      await api.excluirLicitacao(lic.id)
    } catch (e) {
      window.alert(`Não foi possível excluir: ${e.message}`)
    }
    carregar()
    api.licitacoes().then(setLics).catch(() => {})
  }

  async function salvarResponsavel(op, nome) {
    try {
      await api.atualizarOportunidade(op.id, { responsavel: nome })
    } catch (e) {
      window.alert(`Não foi possível salvar o responsável: ${e.message}`)
    }
    carregar()
  }

  if (erro) return <p className="erro">Backend indisponível: {erro}</p>

  return (
    <>
    {docsLic && (
      <div className="modal-fundo" onClick={() => setDocsLic(null)}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <Documentacao licitacao={docsLic} aoFechar={() => setDocsLic(null)} />
        </div>
      </div>
    )}
    {detalheLic && (
      <Janela
        titulo={[detalheLic.orgao || 'Licitação',
          detalheLic.municipio && `${detalheLic.municipio}/${detalheLic.uf}`]
          .filter(Boolean).join(' — ')}
        aoFechar={() => setDetalheLic(null)}
      >
        <DetalhesLicitacao licitacao={detalheLic} aoMudar={carregar}
          aoFechar={() => setDetalheLic(null)} />
      </Janela>
    )}
    <div className="cockpit">
      <div className="tile">
        <span className="tile-k"><span className="led" /> Licitações coletadas</span>
        <span className="tile-v">{lics === null ? '—' : lics.length}</span>
        <span className="tile-d">
          {lics === null
            ? 'PNCP · FIESC · FIERGS · FIEMS · manual'
            : `${abertas.length} em andamento · ${ganhas.length + perdidas.length} finalizadas`}
        </span>
      </div>
      <div className="tile">
        <span className="tile-k">Oportunidades ativas</span>
        <span className="tile-v">{abertas.length}</span>
        <span className="tile-d">no pipeline agora</span>
      </div>
      <div className="tile">
        <span className="tile-k">Valor em disputa</span>
        <span className="tile-v">{valorEmDisputa > 0 ? brlCompacto(valorEmDisputa) : '—'}</span>
        <span className="tile-d">soma das oportunidades abertas</span>
      </div>
      <div className="tile">
        <span className="tile-k">Perdeu / No Go</span>
        <span className="tile-v">{perdidas.length}</span>
        <span className="tile-d">descartadas pelo time — histórico no kanban</span>
      </div>
      <div className="tile">
        <span className="tile-k">Ganhas</span>
        <span className="tile-v">{ganhas.length}</span>
        <span className="tile-d">contratos conquistados</span>
      </div>
    </div>
    <div className="barra-busca">
      <CampoBusca
        valor={busca}
        aoMudar={setBusca}
        placeholder="Buscar por órgão, objeto, município, pregão ou responsável…"
      />
      <FiltrosSelects
        uf={ufFiltro} setUf={setUfFiltro}
        cls={classFiltro} setCls={setClassFiltro}
        venc={vencFiltro} setVenc={setVencFiltro}
        sit={sitFiltro} setSit={setSitFiltro}
      />
      {filtroAtivo && (
        <span className="busca-contagem">
          {opsVisiveis.length} de {ops.length} oportunidades
        </span>
      )}
    </div>
    <datalist id="resp-sugestoes">
      {responsaveis.map((r) => <option key={r} value={r} />)}
    </datalist>
    <DndContext
      sensors={sensores}
      onDragStart={aoIniciarArraste}
      onDragEnd={aoTerminarArraste}
      onDragCancel={() => setOpArrastada(null)}
    >
      <div className="kanban">
        {ESTAGIOS.map((est) => {
          const doEstagio = opsVisiveis.filter((o) => o.estagio === est.id)
          return (
            <Coluna key={est.id} estagio={est.id} rotulo={est.rotulo} contagem={doEstagio.length}>
              {doEstagio.map((op) => (
                <Cartao
                  key={op.id}
                  op={op}
                  aoAbrir={setDetalheLic}
                  aoAbrirDocs={setDocsLic}
                  aoMover={mover}
                  aoExcluir={excluir}
                  aoSalvarResponsavel={salvarResponsavel}
                  foiArraste={() => Date.now() - fimArraste.current < 300}
                />
              ))}
            </Coluna>
          )
        })}
      </div>
      <DragOverlay>
        {opArrastada && <CartaoVisual op={opArrastada} classesExtra="arrastando" />}
      </DragOverlay>
    </DndContext>
    </>
  )
}
