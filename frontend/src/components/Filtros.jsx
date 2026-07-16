// Filtros compartilhados entre o Pipeline (kanban) e a aba Licitações:
// UF, classificação da IA e proximidade do vencimento.

export const CLASSIFICACOES = [
  { valor: 'EXCELENTE OPORTUNIDADE', rotulo: 'Excelente oportunidade' },
  { valor: 'BOA OPORTUNIDADE', rotulo: 'Boa oportunidade' },
  { valor: 'OPORTUNIDADE MODERADA', rotulo: 'Moderada — revisar' },
  { valor: 'ALTO RISCO', rotulo: 'Alto risco — revisar' },
  { valor: 'NÃO RECOMENDADO', rotulo: 'Não recomendado' },
]

// Dias até o vencimento (data_encerramento), comparando só as datas (hoje = 0).
// Retorna null quando não há data válida.
export const diasParaVencer = (iso) => {
  if (!iso) return null
  const alvo = new Date(`${String(iso).slice(0, 10)}T00:00:00`)
  if (isNaN(alvo)) return null
  const hoje = new Date()
  hoje.setHours(0, 0, 0, 0)
  return Math.round((alvo - hoje) / 86400000)
}

export const passaClassificacao = (analise, filtro) => {
  if (filtro === 'todas') return true
  const cls = analise?.classificacao_final || ''
  return filtro === 'sem_analise' ? cls === '' : cls === filtro
}

export const passaVencimento = (iso, filtro) => {
  if (filtro === 'qualquer') return true
  const dias = diasParaVencer(iso)
  if (dias == null) return false
  if (filtro === 'vencidas') return dias < 0
  return dias >= 0 && dias <= Number(filtro)
}

export default function FiltrosSelects({ uf, setUf, cls, setCls, venc, setVenc }) {
  return (
    <>
      <select className="filtro-uf" value={uf} onChange={(e) => setUf(e.target.value)}
        aria-label="Filtrar por UF">
        <option value="todas">Todas as UFs</option>
        <option value="RS">RS</option>
        <option value="SC">SC</option>
        <option value="PR">PR</option>
      </select>
      <select className="filtro-uf" value={cls} onChange={(e) => setCls(e.target.value)}
        aria-label="Filtrar por classificação da IA">
        <option value="todas">Todas as classificações</option>
        {CLASSIFICACOES.map((c) => (
          <option key={c.valor} value={c.valor}>{c.rotulo}</option>
        ))}
        <option value="sem_analise">Sem análise</option>
      </select>
      <select className="filtro-uf" value={venc} onChange={(e) => setVenc(e.target.value)}
        aria-label="Filtrar por vencimento">
        <option value="qualquer">Qualquer vencimento</option>
        <option value="7">Vence em até 7 dias</option>
        <option value="14">Vence em até 14 dias</option>
        <option value="30">Vence em até 30 dias</option>
        <option value="vencidas">Vencidas</option>
      </select>
    </>
  )
}
