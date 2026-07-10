import { useEffect, useState } from 'react'
import { api } from '../api.js'
import Documentacao from './Documentacao.jsx'

const ESTAGIOS = [
  { id: 'identificada', rotulo: 'Identificada' },
  { id: 'em_analise', rotulo: 'Em análise' },
  { id: 'proposta', rotulo: 'Proposta' },
  { id: 'disputa', rotulo: 'Disputa' },
  { id: 'ganhou', rotulo: 'Ganhou 🏆' },
  { id: 'perdeu', rotulo: 'Perdeu' },
]

const brl = (v) =>
  v == null ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

const brlCompacto = (v) =>
  v.toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    notation: 'compact',
    maximumFractionDigits: 1,
  })

export default function Pipeline() {
  const [ops, setOps] = useState([])
  const [totalLicitacoes, setTotalLicitacoes] = useState(null)
  const [erro, setErro] = useState('')
  const [docsLic, setDocsLic] = useState(null) // licitação com modal de documentação aberto

  const carregar = () => api.oportunidades().then(setOps).catch((e) => setErro(e.message))
  useEffect(() => {
    carregar()
    api.licitacoes().then((ls) => setTotalLicitacoes(ls.length)).catch(() => {})
  }, [])

  const abertas = ops.filter((o) => o.estagio !== 'ganhou' && o.estagio !== 'perdeu')
  const ganhas = ops.filter((o) => o.estagio === 'ganhou')
  const valorEmDisputa = abertas.reduce((soma, o) => soma + (o.licitacao?.valor_estimado || 0), 0)

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
    <div className="cockpit">
      <div className="tile">
        <span className="tile-k"><span className="led" /> Licitações coletadas</span>
        <span className="tile-v">{totalLicitacoes ?? '—'}</span>
        <span className="tile-d">PNCP · FIESC · FIERGS · FIEMS · manual</span>
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
        <span className="tile-k">Ganhas</span>
        <span className="tile-v">{ganhas.length}</span>
        <span className="tile-d">contratos conquistados</span>
      </div>
    </div>
    <div className="kanban">
      {ESTAGIOS.map((est) => (
        <div key={est.id} className="coluna">
          <h3>{est.rotulo} <span>{ops.filter((o) => o.estagio === est.id).length}</span></h3>
          {ops.filter((o) => o.estagio === est.id).map((op) => (
            <div key={op.id} className="cartao">
              <div className="cartao-topo">
                <strong>{op.licitacao?.orgao || 'Órgão não informado'}</strong>
                {op.licitacao?.analise && (
                  <span className={`score s${Math.floor(op.licitacao.analise.score / 20)}`}>
                    {op.licitacao.analise.classificacao_final
                      ? `B ${op.licitacao.analise.score_beneficios} • P ${op.licitacao.analise.score_pagamentos}`
                      : op.licitacao.analise.score}
                  </span>
                )}
              </div>
              {op.licitacao?.analise?.classificacao_final && (
                <small><strong>{op.licitacao.analise.classificacao_final}</strong></small>
              )}
              <p>{op.licitacao?.analise?.objeto_resumido || op.licitacao?.objeto}</p>
              <small>
                {op.licitacao?.municipio}/{op.licitacao?.uf} • {brl(op.licitacao?.valor_estimado)}
                {op.licitacao?.data_encerramento && <> • propostas até {op.licitacao.data_encerramento.slice(0, 10)}</>}
              </small>
              <div className="acoes">
                <button onClick={() => mover(op, -1)}>←</button>
                {op.licitacao && (
                  <button onClick={() => setDocsLic(op.licitacao)}>docs</button>
                )}
                {op.licitacao?.link && (
                  <a href={op.licitacao.link} target="_blank" rel="noreferrer">edital ↗</a>
                )}
                <button onClick={() => mover(op, 1)}>→</button>
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
    </>
  )
}
