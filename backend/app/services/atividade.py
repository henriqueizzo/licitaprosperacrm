"""Log de atividade dos usuários (aba Atividade e dashboard, só admin).

Grava eventos de uso (EventoUso) nos pontos instrumentados das rotas e agrega
os dados para os endpoints /api/admin/atividade*. A telemetria é "melhor
esforço": registrar_evento NUNCA propaga erro para a rota principal.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import EventoUso, Licitacao, Usuario

logger = logging.getLogger(__name__)

# Heurística do tempo de uso estimado: intervalos entre eventos consecutivos do
# mesmo usuário contam como uso contínuo se menores que o gap máximo; um gap
# maior (usuário saiu e voltou) conta apenas 1 minuto pelo evento isolado.
GAP_MAX_MINUTOS = 30
MINUTOS_EVENTO_ISOLADO = 1.0

# Eventos são gravados em UTC; o dia de trabalho é contado no fuso do Brasil.
# Offset fixo -3h: o país não adota horário de verão desde 2019 (evita depender
# de tzdata instalado no host).
FUSO_BRASIL = timedelta(hours=-3)


def registrar_evento(
    db: Session,
    usuario: Usuario,
    tipo: str,
    licitacao_id: int | None = None,
    detalhe: str = "",
) -> None:
    """Grava um evento de uso. NUNCA quebra a rota principal (melhor esforço)."""
    try:
        db.add(EventoUso(
            usuario_id=usuario.id,
            tipo=tipo,
            licitacao_id=licitacao_id,
            detalhe=detalhe or "",
        ))
        db.commit()
    except Exception:
        logger.exception(
            "Falha ao registrar evento de uso '%s' (usuário %s)",
            tipo, getattr(usuario, "id", "?"),
        )
        try:
            db.rollback()
        except Exception:
            pass


def _tempo_uso_minutos(momentos: list[datetime]) -> int:
    """Tempo de uso estimado: soma dos gaps < 30 min; gap maior conta 1 min."""
    if not momentos:
        return 0
    total = 0.0
    for antes, depois in zip(momentos, momentos[1:]):
        gap = (depois - antes).total_seconds() / 60
        total += gap if gap < GAP_MAX_MINUTOS else MINUTOS_EVENTO_ISOLADO
    # pelo menos 1 min para quem teve algum evento no período
    return max(int(round(total)), 1)


def _uso_por_dia(momentos: list[datetime]) -> list[dict]:
    """Tempo de uso estimado por dia (fuso do Brasil), mais recente primeiro.

    Mesma heurística do total (_tempo_uso_minutos), aplicada aos eventos de cada
    dia. Só retorna dias com atividade:
    [{dia: 'YYYY-MM-DD', minutos: int, eventos: int}].
    """
    por_dia: dict[str, list[datetime]] = {}
    for momento in momentos:
        dia = (momento + FUSO_BRASIL).date().isoformat()
        por_dia.setdefault(dia, []).append(momento)
    return [
        {"dia": dia, "minutos": _tempo_uso_minutos(do_dia), "eventos": len(do_dia)}
        for dia, do_dia in sorted(por_dia.items(), reverse=True)
    ]


def resumo_atividade(db: Session, dias: int) -> list[dict]:
    """Resumo por usuário nos últimos `dias` (formato consumido pelo dashboard).

    Cada item: usuario_id, nome, email, ativo, ultimo_acesso (ISO UTC com Z ou
    null), total_eventos, licitacoes_distintas, tempo_uso_minutos,
    uso_por_dia ([{dia, minutos}], dia no fuso do Brasil, desc),
    eventos_por_tipo ({tipo: quantidade}). Ordenado por total_eventos desc.
    """
    corte = datetime.utcnow() - timedelta(days=dias)
    usuarios = db.execute(select(Usuario).order_by(Usuario.criado_em)).scalars().all()
    eventos = db.execute(
        select(EventoUso.usuario_id, EventoUso.tipo, EventoUso.licitacao_id, EventoUso.criado_em)
        .where(EventoUso.criado_em >= corte)
        .order_by(EventoUso.usuario_id, EventoUso.criado_em)
    ).all()

    por_usuario: dict[int, list] = {}
    for ev in eventos:
        por_usuario.setdefault(ev.usuario_id, []).append(ev)

    saida = []
    for u in usuarios:
        evs = por_usuario.get(u.id, [])
        por_tipo: dict[str, int] = {}
        licitacoes: set[int] = set()
        for ev in evs:
            por_tipo[ev.tipo] = por_tipo.get(ev.tipo, 0) + 1
            if ev.licitacao_id:
                licitacoes.add(ev.licitacao_id)
        saida.append({
            "usuario_id": u.id,
            "nome": u.nome,
            "email": u.email,
            "ativo": u.ativo,
            "ultimo_acesso": u.ultimo_acesso.isoformat() + "Z" if u.ultimo_acesso else None,
            "total_eventos": len(evs),
            "licitacoes_distintas": len(licitacoes),
            "tempo_uso_minutos": _tempo_uso_minutos([ev.criado_em for ev in evs]),
            "uso_por_dia": _uso_por_dia([ev.criado_em for ev in evs]),
            "eventos_por_tipo": por_tipo,
        })
    saida.sort(key=lambda r: r["total_eventos"], reverse=True)
    return saida


def eventos_recentes(
    db: Session,
    usuario_id: int | None = None,
    dias: int = 30,
    limit: int = 100,
) -> list[dict]:
    """Eventos recentes (desc), com nome do usuário e objeto/órgão da licitação."""
    corte = datetime.utcnow() - timedelta(days=dias)
    q = (
        select(EventoUso, Usuario.nome, Usuario.email, Licitacao.objeto, Licitacao.orgao)
        .join(Usuario, EventoUso.usuario_id == Usuario.id)
        .outerjoin(Licitacao, EventoUso.licitacao_id == Licitacao.id)
        .where(EventoUso.criado_em >= corte)
        .order_by(EventoUso.criado_em.desc())
        .limit(limit)
    )
    if usuario_id:
        q = q.where(EventoUso.usuario_id == usuario_id)
    return [
        {
            "id": ev.id,
            "usuario_id": ev.usuario_id,
            "usuario_nome": nome or email,
            "tipo": ev.tipo,
            "licitacao_id": ev.licitacao_id,
            "licitacao_objeto": objeto,
            "licitacao_orgao": orgao,
            "detalhe": ev.detalhe,
            "criado_em": ev.criado_em.isoformat() + "Z",
        }
        for ev, nome, email, objeto, orgao in db.execute(q).all()
    ]
