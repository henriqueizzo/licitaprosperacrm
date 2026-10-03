"""Rotas da aba "E-mails do Dario" (/api/emails/*) — exigem sessão (main.py)."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import EmailRecebido, ItemEmail, Usuario
from ..security import usuario_atual
from ..services import emails as servico
from ..services import gmail
from ..services.atividade import registrar_evento
from .routes import _iniciar_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/emails")


class ColarIn(BaseModel):
    conteudo: str
    assunto: str = ""


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return servico.resumo_status(db)


@router.get("")
def listar(limite: int = 60, db: Session = Depends(get_db)):
    emails = db.execute(
        select(EmailRecebido)
        .order_by(EmailRecebido.recebido_em.desc().nullslast(), EmailRecebido.id.desc())
        .limit(limite)
    ).scalars().all()
    return [_email_out(e) for e in emails]


@router.post("/sincronizar", status_code=202)
def sincronizar(dias: int | None = None, usuario: Usuario = Depends(usuario_atual),
                db: Session = Depends(get_db)):
    """Lê os boletins novos do Gmail e tria (job em segundo plano; polling em
    GET /api/extracoes/{job_id}, como as extrações por PDF)."""
    if not gmail.configurado():
        raise HTTPException(
            409, "Gmail não conectado — configure GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET e "
                 "GMAIL_REFRESH_TOKEN no servidor (scripts/autorizar_gmail.py) ou use 'Colar e-mail'.",
        )
    registrar_evento(db, usuario, "sincronizar_emails", detalhe=f"dias={dias or gmail.settings.emails_janela_dias}")

    def trabalho():
        from ..database import SessionLocal
        sessao = SessionLocal()
        try:
            return servico.sincronizar_gmail(sessao, dias=dias)
        except gmail.GmailIndisponivel as exc:
            raise HTTPException(502, str(exc))
        finally:
            sessao.close()

    return {"job_id": _iniciar_job(trabalho)}


@router.post("/colar", status_code=202)
def colar(dados: ColarIn, usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    """Processa um boletim colado (HTML ou texto copiado do Gmail) — mesmo agente,
    sem depender da conexão com o Gmail."""
    conteudo = (dados.conteudo or "").strip()
    if len(conteudo) < 40:
        raise HTTPException(400, "Cole o conteúdo do e-mail (texto ou HTML) — veio vazio ou curto demais.")
    registrar_evento(db, usuario, "colar_email", detalhe=(dados.assunto or conteudo[:120]))
    gmail_id = servico.gmail_id_colado(conteudo)

    def trabalho():
        from ..database import SessionLocal
        sessao = SessionLocal()
        try:
            email = servico.processar_boletim(
                sessao, gmail_id=gmail_id, assunto=dados.assunto, remetente=f"colado por {usuario.nome or usuario.email}",
                recebido_em=datetime.utcnow(),
                html=conteudo if conteudo.lstrip().startswith("<") or "<table" in conteudo.lower() else None,
                texto=None if (conteudo.lstrip().startswith("<") or "<table" in conteudo.lower()) else conteudo,
                origem="colado",
            )
            if email is None:
                raise HTTPException(409, "Este e-mail já foi processado antes (mesmo conteúdo).")
            if email.erro and not email.total_itens:
                raise HTTPException(422, email.erro)
            triagem = servico.triar_pendentes(sessao)
            sessao.refresh(email)
            return {"email": _email_out(email), **triagem}
        finally:
            sessao.close()

    return {"job_id": _iniciar_job(trabalho)}


@router.post("/itens/{item_id}/importar")
def importar(item_id: int, usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    """Força a entrada no pipeline de um item que a triagem deixou de fora."""
    item = db.get(ItemEmail, item_id)
    if not item:
        raise HTTPException(404, "Item não encontrado")
    if item.situacao == "importada" and item.licitacao_id:
        raise HTTPException(409, f"Já está no pipeline (licitação #{item.licitacao_id}).")
    if item.situacao == "ja_na_base" and item.licitacao_id:
        raise HTTPException(409, f"Já está na base (licitação #{item.licitacao_id}) — use o card existente.")
    lic = servico.importar_item(db, item, forcado=True, por=usuario.nome or usuario.email,
                                motivo=f"Importada manualmente por {usuario.nome or usuario.email}")
    registrar_evento(db, usuario, "importar_item_email", licitacao_id=lic.id, detalhe=(item.objeto or "")[:200])
    return _item_out(item)


@router.post("/itens/{item_id}/ignorar")
def ignorar(item_id: int, usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    item = db.get(ItemEmail, item_id)
    if not item:
        raise HTTPException(404, "Item não encontrado")
    if item.situacao == "importada":
        raise HTTPException(409, "Este item já virou card — exclua o card no Pipeline se não quiser mais.")
    servico._decidir(item, "ignorado", aderente=False, motivo=f"Ignorado por {usuario.nome or usuario.email}")
    db.commit()
    registrar_evento(db, usuario, "ignorar_item_email", detalhe=(item.objeto or "")[:200])
    return _item_out(item)


# ---------- serializadores ----------

def _item_out(i: ItemEmail) -> dict:
    return {
        "id": i.id, "email_id": i.email_id, "ordem": i.ordem, "chave": i.chave, "portal": i.portal,
        "orgao": i.orgao, "municipio": i.municipio, "uf": i.uf, "modalidade": i.modalidade,
        "numero_certame": i.numero_certame, "objeto": i.objeto,
        "data_abertura": i.data_abertura, "data_encerramento": i.data_encerramento, "link": i.link,
        "situacao": i.situacao, "licitacao_id": i.licitacao_id, "aderente": i.aderente,
        "score_ia": i.score_ia, "motivo": i.motivo,
        "decidido_em": i.decidido_em.isoformat() + "Z" if i.decidido_em else None,
    }


def _email_out(e: EmailRecebido) -> dict:
    itens = [_item_out(i) for i in e.itens]
    resumo: dict[str, int] = {}
    for i in itens:
        resumo[i["situacao"]] = resumo.get(i["situacao"], 0) + 1
    return {
        "id": e.id, "gmail_id": e.gmail_id, "assunto": e.assunto, "remetente": e.remetente,
        "recebido_em": e.recebido_em.isoformat() + "Z" if e.recebido_em else None,
        "processado_em": e.processado_em.isoformat() + "Z" if e.processado_em else None,
        "tipo": e.tipo, "origem": e.origem, "total_itens": e.total_itens, "erro": e.erro,
        "resumo": resumo, "itens": itens,
    }
