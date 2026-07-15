"""Agregações do dashboard executivo (aba Dashboard, report ao CEO).

Monta num único payload os indicadores do período, o funil do pipeline, as
distribuições (UF, fonte, classificação da IA), os vencimentos próximos e a
série de coletas por dia. Tudo somente leitura — nenhuma migração envolvida.
O bloco de atividade por usuário (só admin) é anexado pela rota, reutilizando
`resumo_atividade` de services/atividade.py.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Analise, Licitacao, Oportunidade

# Estágios que encerram a oportunidade (fim do funil)
ESTAGIOS_FINAIS = {"ganhou", "perdeu_nogo"}

# Ordem canônica das classificações da IA nos gráficos (+ "sem análise" no fim)
CLASSIFICACOES_IA = [
    "EXCELENTE OPORTUNIDADE",
    "BOA OPORTUNIDADE",
    "OPORTUNIDADE MODERADA",
    "ALTO RISCO",
    "NÃO RECOMENDADO",
]
SEM_ANALISE = "SEM ANÁLISE"

# Janela de alerta de vencimento (mesma régua dos cartões do kanban)
VENCIMENTO_DIAS = 14
VENCIMENTO_LIMITE_ITENS = 12


def _data_iso(valor: str | None) -> date | None:
    """Converte 'YYYY-MM-DD[...]' (string livre das fontes) em date; None se inválida."""
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def montar_dashboard(db: Session, dias: int) -> dict:
    """Payload do GET /api/dashboard (formato documentado no docstring da rota)."""
    agora = datetime.utcnow()
    corte = agora - timedelta(days=dias)
    hoje = date.today()

    # ---- Licitações do período (distribuições e série temporal) ----
    lics_periodo = db.execute(
        select(Licitacao.id, Licitacao.uf, Licitacao.fonte, Licitacao.criado_em)
        .where(Licitacao.criado_em >= corte)
    ).all()

    # Última classificação da IA por licitação (reanálise substitui a anterior)
    classificacao_por_lic: dict[int, str] = {}
    for lic_id, classificacao in db.execute(
        select(Analise.licitacao_id, Analise.classificacao_final).order_by(Analise.criado_em)
    ).all():
        classificacao_por_lic[lic_id] = (classificacao or "").strip()

    por_uf: dict[str, int] = {}
    por_fonte: dict[str, int] = {}
    por_dia: dict[str, int] = {}
    por_classificacao: dict[str, int] = {c: 0 for c in CLASSIFICACOES_IA}
    por_classificacao[SEM_ANALISE] = 0
    for lic_id, uf, fonte, criado_em in lics_periodo:
        chave_uf = (uf or "").strip().upper() or "Sem UF"
        por_uf[chave_uf] = por_uf.get(chave_uf, 0) + 1
        chave_fonte = (fonte or "").strip() or "desconhecida"
        por_fonte[chave_fonte] = por_fonte.get(chave_fonte, 0) + 1
        if criado_em:
            chave_dia = criado_em.date().isoformat()
            por_dia[chave_dia] = por_dia.get(chave_dia, 0) + 1
        classificacao = classificacao_por_lic.get(lic_id, "") or SEM_ANALISE
        por_classificacao[classificacao] = por_classificacao.get(classificacao, 0) + 1

    # Série contínua: todos os dias do período, inclusive os sem coleta (barra zero)
    coletas_por_dia = []
    for i in range(dias):
        d = (hoje - timedelta(days=dias - 1 - i)).isoformat()
        coletas_por_dia.append({"dia": d, "quantidade": por_dia.get(d, 0)})

    # ---- Oportunidades (funil, valores e vencimentos) ----
    ops = db.execute(
        select(Oportunidade, Licitacao).join(Licitacao, Oportunidade.licitacao_id == Licitacao.id)
    ).all()

    funil = {e: {"quantidade": 0, "valor": 0.0} for e in Oportunidade.ESTAGIOS}
    valor_em_disputa = 0.0
    oportunidades_novas = 0
    ganhas = perdidas = 0
    valor_ganho = valor_perdido = 0.0
    vencimentos = []

    for op, lic in ops:
        valor = lic.valor_estimado or 0.0
        if op.estagio in funil:
            funil[op.estagio]["quantidade"] += 1
            funil[op.estagio]["valor"] += valor
        if op.criado_em and op.criado_em >= corte:
            oportunidades_novas += 1

        if op.estagio in ESTAGIOS_FINAIS:
            # Finalizadas NO PERÍODO (a última movimentação levou ao estágio final)
            if op.atualizado_em and op.atualizado_em >= corte:
                if op.estagio == "ganhou":
                    ganhas += 1
                    valor_ganho += valor
                else:
                    perdidas += 1
                    valor_perdido += valor
            continue

        # Estágio ativo: soma no valor em disputa e checa o vencimento próximo
        valor_em_disputa += valor
        encerramento = _data_iso(lic.data_encerramento)
        if encerramento and hoje <= encerramento <= hoje + timedelta(days=VENCIMENTO_DIAS):
            vencimentos.append({
                "oportunidade_id": op.id,
                "licitacao_id": lic.id,
                "orgao": lic.orgao,
                "municipio": lic.municipio,
                "uf": lic.uf,
                "objeto": (lic.objeto or "")[:180],
                "valor_estimado": lic.valor_estimado,
                "data_encerramento": encerramento.isoformat(),
                "dias_restantes": (encerramento - hoje).days,
                "estagio": op.estagio,
            })

    vencimentos.sort(key=lambda v: v["data_encerramento"])
    finalizadas = ganhas + perdidas
    taxa_vitoria = round(100 * ganhas / finalizadas, 1) if finalizadas else None

    return {
        "dias": dias,
        "gerado_em": agora.isoformat() + "Z",
        "indicadores": {
            "licitacoes_coletadas": len(lics_periodo),
            "oportunidades_novas": oportunidades_novas,
            "valor_em_disputa": valor_em_disputa,
            "valor_ganho": valor_ganho,
            "valor_perdido": valor_perdido,
            "ganhas": ganhas,
            "perdidas": perdidas,
            "taxa_vitoria": taxa_vitoria,  # % (0–100) ou null sem finalizadas no período
        },
        "funil": [
            {"estagio": e, "quantidade": funil[e]["quantidade"], "valor": funil[e]["valor"]}
            for e in Oportunidade.ESTAGIOS
        ],
        "por_uf": [
            {"uf": uf, "quantidade": qtd}
            for uf, qtd in sorted(por_uf.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "por_fonte": [
            {"fonte": fonte, "quantidade": qtd}
            for fonte, qtd in sorted(por_fonte.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "classificacoes": [
            {"classificacao": c, "quantidade": por_classificacao[c]}
            for c in [*CLASSIFICACOES_IA, SEM_ANALISE]
        ] + [
            # Valores inesperados vindos da IA aparecem no fim, sem sumir do total
            {"classificacao": c, "quantidade": q}
            for c, q in sorted(por_classificacao.items(), key=lambda kv: kv[1], reverse=True)
            if c not in CLASSIFICACOES_IA and c != SEM_ANALISE
        ],
        "vencimentos_proximos": vencimentos[:VENCIMENTO_LIMITE_ITENS],
        "coletas_por_dia": coletas_por_dia,
    }
