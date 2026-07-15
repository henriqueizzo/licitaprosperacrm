import { useEffect, useState } from 'react'
import { api } from '../api.js'

// Dashboard executivo (primeira aba): KPIs do período, funil do pipeline,
// coletas por dia, distribuições e vencimentos — pronto para virar report
// impresso ao CEO (botão "Imprimir report" + @media print no styles.css).
// Gráficos sem biblioteca: divs com largura/altura proporcionais, sempre com
// o valor numérico ao lado da barra (o visual nunca é a única leitura).

const PERIODOS = [
  { dias: 7, rotulo: '7 dias' },
  { dias: 30, rotulo: '30 dias' },
  { dias: 90, rotulo: '90 dias' },
]

// Estágios na ordem do kanban: azul = ativo (neutro), verde = ganhou, vermelho = perdeu
const ESTAGIOS = {
  identificada: { rotulo: 'Identificada', tom: 'azul' },
  em_analise: { rotulo: 'Em análise', tom: 'azul' },
  impugnacao: { rotulo: 'Impugnação', tom: 'azul' },
  proposta_enviada: { rotulo: 'Proposta enviada', tom: 'azul' },
  disputa: { rotulo: 'Disputa', tom: 'azul' },
  ganhou: { rotulo: 'Ganhou', tom: 'verde' },
  perdeu_nogo: { rotulo: 'Perdeu / No Go', tom: 'vermelho' },
}

// Classificações da IA → rótulo curto + matiz semântico (mesma régua do kanban)
const CLASSIFICACOES = {
  'EXCELENTE OPORTUNIDADE': { rotulo: 'Excelente', tom: 'verde' },
  'BOA OPORTUNIDADE': { rotulo: 'Boa', tom: 'azul' },
  'OPORTUNIDADE MODERADA': { rotulo: 'Moderada', tom: 'amarelo' },
  'ALTO RISCO': { rotulo: 'Alto risco', tom: 'amarelo' },
  'NÃO RECOMENDADO': { rotulo: 'Não recomendado', tom: 'vermelho' },
  'SEM ANÁLISE': { rotulo: 'Sem análise', tom: 'cinza' },
}

const FONTES = { pncp: 'PNCP', fiesc: 'FIESC', fiergs: 'FIERGS', fiems: 'FIEMS', manual: 'Manual' }

const brlCompacto = (v) =>
  v == null || v === 0
    ? null
    : v.toLocaleString('pt-BR', {
        style: 'currency', currency: 'BRL', notation: 'compact', maximumFractionDigits: 1,
      })

// ISO (YYYY-MM-DD) → DD/MM e DD/MM/AAAA
const diaMes = (iso) => {
  const [, m, d] = String(iso).slice(0, 10).split('-')
  return d && m ? `${d}/${m}` : iso
}
const dataBr = (iso) => {
  const [a, m, d] = String(iso).slice(0, 10).split('-')
  return a && m && d ? `${d}/${m}/${a}` : '—'
}
const dataHora = (iso) =>
  iso
    ? new Date(iso).toLocaleString('pt-BR', {
        day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit',
      })
    : '—'

function tempoUso(min) {
  if (!min) return '—'
  if (min < 60) return `${min} min`
  const h = Math.floor(min / 60)
  const m = min % 60
  return m ? `${h} h ${m} min` : `${h} h`
}

// Série diária → barras do gráfico; acima de 31 dias agrega por semana para
// os números continuarem legíveis em cada barra
function agruparSerie(serie, dias) {
  if (dias <= 31) {
    return serie.map((p) => ({ chave: p.dia, rotulo: diaMes(p.dia), quantidade: p.quantidade }))
  }
  const grupos = []
  for (let i = 0; i < serie.length; i += 7) {
    const bloco = serie.slice(i, i + 7)
    grupos.push({
      chave: bloco[0].dia,
      rotulo: `${diaMes(bloco[0].dia)}–${diaMes(bloco[bloco.length - 1].dia)}`,
      quantidade: bloco.reduce((s, p) => s + p.quantidade, 0),
    })
  }
  return grupos
}

// Barra horizontal com rótulo à esquerda e valor numérico sempre visível à direita
function BarraH({ rotulo, quantidade, extra, frac, tom = 'azul', titulo }) {
  const largura = quantidade > 0 ? Math.max(frac * 100, 2.5) : 0
  return (
    <div className="dash-barra" title={titulo || rotulo}>
      <span className="dash-barra-rotulo">{rotulo}</span>
      <div className="dash-barra-trilho">
        <div className={`dash-barra-fill ${tom}`} style={{ width: `${largura}%` }} />
      </div>
      <span className="dash-barra-num">
        {quantidade}
        {extra && <small> · {extra}</small>}
      </span>
    </div>
  )
}

function Vazio({ children }) {
  return <p className="dash-vazio">{children}</p>
}

export default function Dashboard() {
  const [dias, setDias] = useState(30)
  const [dados, setDados] = useState(null) // null = carregando
  const [msg, setMsg] = useState('')

  useEffect(() => {
    let ativo = true
    setDados(null)
    setMsg('')
    api.dashboard(dias)
      .then((r) => { if (ativo) setDados(r) })
      .catch((e) => { if (ativo) setMsg(`Falha ao carregar o dashboard: ${e.message}`) })
    return () => { ativo = false }
  }, [dias])

  if (msg) return <div className="banner erro">{msg}</div>
  if (!dados) return <p className="pendente">Carregando o dashboard…</p>

  const ind = dados.indicadores
  const funilMax = Math.max(...dados.funil.map((f) => f.quantidade), 1)
  const temOportunidades = dados.funil.some((f) => f.quantidade > 0)

  const serie = agruparSerie(dados.coletas_por_dia, dados.dias)
  const serieMax = Math.max(...serie.map((p) => p.quantidade), 1)
  const totalColetas = serie.reduce((s, p) => s + p.quantidade, 0)
  const passoRotulo = Math.max(1, Math.ceil(serie.length / 8)) // eixo X sem poluição

  // Top 8 UFs + "Outras" agregado (report enxuto)
  const ufs = dados.por_uf.slice(0, 8)
  const outrasUf = dados.por_uf.slice(8).reduce((s, u) => s + u.quantidade, 0)
  if (outrasUf > 0) ufs.push({ uf: 'Outras', quantidade: outrasUf })
  const ufMax = Math.max(...ufs.map((u) => u.quantidade), 1)

  const classifs = dados.classificacoes
  const classifMax = Math.max(...classifs.map((c) => c.quantidade), 1)
  const fonteMax = Math.max(...dados.por_fonte.map((f) => f.quantidade), 1)

  const usuariosAtividade = dados.atividade?.usuarios

  return (
    <div className="dashboard">
      <div className="dash-topo">
        <span className="dash-legenda">
          Report executivo — últimos {dados.dias} dias · gerado em {dataHora(dados.gerado_em)}
        </span>
        <div className="dash-controles">
          <div className="segmentado" role="tablist" aria-label="Período">
            {PERIODOS.map((p) => (
              <button key={p.dias} className={dias === p.dias ? 'ativo' : ''}
                      onClick={() => setDias(p.dias)}>
                {p.rotulo}
              </button>
            ))}
          </div>
          <button className="usuario-btn" onClick={() => window.print()}>🖨 Imprimir report</button>
        </div>
      </div>

      {/* ---- KPIs do período ---- */}
      <div className="cockpit">
        <div className="tile">
          <span className="tile-k">Licitações coletadas</span>
          <span className="tile-v">{ind.licitacoes_coletadas}</span>
          <span className="tile-d">entraram no radar no período</span>
        </div>
        <div className="tile">
          <span className="tile-k">Oportunidades novas</span>
          <span className="tile-v">{ind.oportunidades_novas}</span>
          <span className="tile-d">entraram no pipeline no período</span>
        </div>
        <div className="tile">
          <span className="tile-k">Valor em disputa</span>
          <span className="tile-v">{brlCompacto(ind.valor_em_disputa) || '—'}</span>
          <span className="tile-d">soma dos estágios ativos hoje</span>
        </div>
        <div className="tile">
          <span className="tile-k">Valor ganho</span>
          <span className="tile-v verde">{brlCompacto(ind.valor_ganho) || '—'}</span>
          <span className="tile-d">{ind.ganhas} conquistada{ind.ganhas === 1 ? '' : 's'} no período</span>
        </div>
        <div className="tile">
          <span className="tile-k">Perdido / No Go</span>
          <span className="tile-v vermelho">{brlCompacto(ind.valor_perdido) || '—'}</span>
          <span className="tile-d">{ind.perdidas} finalizada{ind.perdidas === 1 ? '' : 's'} sem êxito</span>
        </div>
        <div className="tile">
          <span className="tile-k">Taxa de vitória</span>
          <span className="tile-v">{ind.taxa_vitoria != null ? `${ind.taxa_vitoria}%` : '—'}</span>
          <span className="tile-d">
            {ind.taxa_vitoria != null
              ? 'das que chegaram ao fim no período'
              : 'nenhuma finalizada no período'}
          </span>
        </div>
      </div>

      {/* ---- Funil + coletas por dia ---- */}
      <div className="dash-grade">
        <section className="dash-cartao">
          <h3>Funil do pipeline <small>quantidade e valor por estágio (foto atual)</small></h3>
          {temOportunidades ? (
            dados.funil.map((f) => {
              const est = ESTAGIOS[f.estagio] || { rotulo: f.estagio, tom: 'azul' }
              return (
                <BarraH key={f.estagio} rotulo={est.rotulo} tom={est.tom}
                        quantidade={f.quantidade} frac={f.quantidade / funilMax}
                        extra={brlCompacto(f.valor)}
                        titulo={`${est.rotulo}: ${f.quantidade} oportunidade(s)${brlCompacto(f.valor) ? ` · ${brlCompacto(f.valor)}` : ''}`} />
              )
            })
          ) : (
            <Vazio>Nenhuma oportunidade no pipeline ainda — rode uma coleta para começar.</Vazio>
          )}
        </section>

        <section className="dash-cartao">
          <h3>
            Licitações coletadas {dados.dias <= 31 ? 'por dia' : 'por semana'}{' '}
            <small>{totalColetas} no total do período</small>
          </h3>
          {totalColetas > 0 ? (
            <>
              <div className="dash-vbarras" role="img"
                   aria-label={`Coletas ${dados.dias <= 31 ? 'por dia' : 'por semana'}: ${totalColetas} no período`}>
                {serie.map((p) => (
                  <div key={p.chave} className="dash-vbar" title={`${p.rotulo}: ${p.quantidade}`}>
                    <span className="dash-vbar-num">{p.quantidade > 0 ? p.quantidade : ''}</span>
                    <div className="dash-vbar-fill"
                         style={{ height: `${p.quantidade > 0 ? Math.max((p.quantidade / serieMax) * 100, 4) : 0}%` }} />
                  </div>
                ))}
              </div>
              <div className="dash-vbar-eixo">
                {serie.map((p, i) => (
                  <span key={p.chave} className="dash-vbar-dia">
                    {i % passoRotulo === 0 || i === serie.length - 1 ? diaMes(p.chave) : ''}
                  </span>
                ))}
              </div>
            </>
          ) : (
            <Vazio>Nenhuma licitação coletada no período.</Vazio>
          )}
        </section>
      </div>

      {/* ---- Distribuições ---- */}
      <div className="dash-grade tres">
        <section className="dash-cartao">
          <h3>Por UF <small>licitações do período</small></h3>
          {ufs.length > 0 ? (
            ufs.map((u) => (
              <BarraH key={u.uf} rotulo={u.uf} quantidade={u.quantidade} frac={u.quantidade / ufMax} />
            ))
          ) : (
            <Vazio>Sem dados no período.</Vazio>
          )}
        </section>

        <section className="dash-cartao">
          <h3>Classificação da IA <small>licitações do período</small></h3>
          {ind.licitacoes_coletadas > 0 ? (
            classifs.map((c) => {
              const visual = CLASSIFICACOES[c.classificacao] || { rotulo: c.classificacao, tom: 'cinza' }
              return (
                <BarraH key={c.classificacao} rotulo={visual.rotulo} tom={visual.tom}
                        quantidade={c.quantidade} frac={c.quantidade / classifMax}
                        titulo={`${c.classificacao}: ${c.quantidade}`} />
              )
            })
          ) : (
            <Vazio>Sem dados no período.</Vazio>
          )}
        </section>

        <section className="dash-cartao">
          <h3>Por fonte <small>origem das coletas</small></h3>
          {dados.por_fonte.length > 0 ? (
            dados.por_fonte.map((f) => (
              <BarraH key={f.fonte} rotulo={FONTES[f.fonte] || f.fonte}
                      quantidade={f.quantidade} frac={f.quantidade / fonteMax} />
            ))
          ) : (
            <Vazio>Sem dados no período.</Vazio>
          )}
        </section>
      </div>

      {/* ---- Vencimentos próximos ---- */}
      <section className="dash-cartao">
        <h3>Vencendo nos próximos 14 dias <small>oportunidades ativas por data de encerramento</small></h3>
        {dados.vencimentos_proximos.length > 0 ? (
          <table className="tabela dash-tabela">
            <thead>
              <tr>
                <th>Órgão</th>
                <th>Estágio</th>
                <th>Valor</th>
                <th>Vence em</th>
              </tr>
            </thead>
            <tbody>
              {dados.vencimentos_proximos.map((v) => (
                <tr key={v.oportunidade_id}>
                  <td>
                    <div className="dash-orgao" title={v.objeto}>
                      {v.orgao || 'Órgão não informado'}
                      {v.municipio && <span className="dash-orgao-local"> — {v.municipio}/{v.uf}</span>}
                    </div>
                    <div className="dash-objeto">{v.objeto}</div>
                  </td>
                  <td>
                    <span className="veredito azul">{(ESTAGIOS[v.estagio] || {}).rotulo || v.estagio}</span>
                  </td>
                  <td>{brlCompacto(v.valor_estimado) || '—'}</td>
                  <td>
                    {dataBr(v.data_encerramento)}{' '}
                    <span className={`veredito ${v.dias_restantes <= 7 ? 'vermelho' : 'amarelo'}`}>
                      {v.dias_restantes === 0 ? 'hoje' : `${v.dias_restantes} dia${v.dias_restantes === 1 ? '' : 's'}`}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Vazio>Nenhuma oportunidade ativa vence nos próximos 14 dias.</Vazio>
        )}
      </section>

      {/* ---- Atividade por usuário (só admin: o backend só envia para admin) ---- */}
      {usuariosAtividade && (
        <section className="dash-cartao">
          <h3>Atividade por usuário <small>uso do sistema no período — detalhes na aba Atividade</small></h3>
          {usuariosAtividade.length > 0 ? (
            <table className="tabela dash-tabela">
              <thead>
                <tr>
                  <th>Usuário</th>
                  <th>Último acesso</th>
                  <th>Eventos</th>
                  <th>Licitações</th>
                  <th>Tempo de uso (est.)</th>
                </tr>
              </thead>
              <tbody>
                {usuariosAtividade.map((u) => (
                  <tr key={u.usuario_id}>
                    <td>
                      {u.nome || u.email}
                      {!u.ativo && <span className="veredito cinza atividade-pilula"> Desativado</span>}
                    </td>
                    <td>{dataHora(u.ultimo_acesso)}</td>
                    <td>{u.total_eventos}</td>
                    <td>{u.licitacoes_distintas}</td>
                    <td>{tempoUso(u.tempo_uso_minutos)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Vazio>Nenhum usuário cadastrado.</Vazio>
          )}
        </section>
      )}
    </div>
  )
}
