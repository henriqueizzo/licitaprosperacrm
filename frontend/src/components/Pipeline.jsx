import { useEffect, useState } from 'react'
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

const brlCompacto = (v) =>
  v == null
    ? null
    : v.toLocaleString('pt-BR', {
        style: 'currency',
        currency: 'BRL',
        notation: 'compact',
        maximumFractionDigits: 1,
      })

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

  const carregar = () => api.oportunidades().then(setOps).catch((e) => setErro(e.message))
  useEffect(() => {
    carregar()
    api.licitacoes().then(setLics).catch(() => {})
  }, [])

  const abertas = ops.filter((o) => o.estagio !== 'ganhou' && o.estagio !== 'perdeu_nogo')
  const ganhas = ops.filter((o) => o.estagio === 'ganhou')
  const perdidas = ops.filter((o) => o.estagio === 'perdeu_nogo')
  const valorEmDisputa = abertas.reduce((soma, o) => soma + (o.licitacao?.valor_estimado || 0), 0)

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

  async function mover(op, direcao) {
    const i = ESTAGIOS.findIndex((e) => e.id === op.estagio)
    const destino = ESTAGIOS[i + direcao]
    if (!destino) return
    await api.moverOportunidade(op.id, destino.id)
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
        <DetalhesLicitacao licitacao={detalheLic} aoMudar={carregar} />
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
    <div className="kanban">
      {ESTAGIOS.map((est) => (
        <div key={est.id} className="coluna">
          <h3>{est.rotulo} <span>{opsVisiveis.filter((o) => o.estagio === est.id).length}</span></h3>
          {opsVisiveis.filter((o) => o.estagio === est.id).map((op) => {
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
            return (
            <div
              key={op.id}
              className={`cartao clicavel${prazo ? ` ${prazo}` : ''}`}
              title="Clique para ver os detalhes da licitação"
              onClick={() => lic && setDetalheLic(lic)}
            >
              <div className="cartao-topo">
                <strong className="cartao-titulo" title={titulo}>{titulo}</strong>
                {lic?.suspensa && <span className="selo-suspensa">Suspensa</span>}
                {prazo === 'prazo-vencida' && <span className="selo-vencida">Vencida</span>}
              </div>
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
                {vencimento && (
                  <span className="cartao-venc" title={`Vence em ${vencimento}`}>Vence {vencimento}</span>
                )}
              </small>
              <div className="acoes" onClick={(e) => e.stopPropagation()}>
                <button title="Voltar estágio" aria-label="Voltar estágio" onClick={() => mover(op, -1)}>←</button>
                {lic && (
                  <button onClick={() => setDocsLic(lic)}>docs</button>
                )}
                {lic?.link && (
                  <a href={lic.link} target="_blank" rel="noreferrer">edital ↗</a>
                )}
                <button title="Avançar estágio" aria-label="Avançar estágio" onClick={() => mover(op, 1)}>→</button>
              </div>
            </div>
            )
          })}
        </div>
      ))}
    </div>
    </>
  )
}
