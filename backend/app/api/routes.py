import logging
import secrets
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Header, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Analise, DocumentoAnexo, Licitacao, Oportunidade, PerfilEmpresa
from ..services import pipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Rotas SEM cookie de sessão (autenticação própria por token) — incluídas no
# main.py sem a dependency `usuario_atual`.
cron_router = APIRouter(prefix="/api")


def _pipeline_em_background(dias: int, limite_analises: int) -> None:
    """Roda o pipeline com sessão própria (a da requisição já terá sido fechada)."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        resultado = pipeline.executar_pipeline(db, dias=dias, limite_analises=limite_analises, gatilho="cron")
        logger.info("Pipeline via cron concluído: %s", resultado)
    except Exception:
        logger.exception("Pipeline via cron falhou")
    finally:
        db.close()


@cron_router.post("/pipeline/executar-cron", status_code=202)
def executar_pipeline_cron(
    tarefas: BackgroundTasks,
    dias: int = 3,
    limite_analises: int = 10,
    token: str | None = None,
    x_cron_token: str | None = Header(default=None),
):
    """Dispara o pipeline (coleta + análise IA) via cron externo, sem cookie de sessão.

    Autenticação: header `X-Cron-Token` (ou query `?token=`) igual à env CRON_TOKEN.
    Se CRON_TOKEN não estiver configurado, a rota fica desabilitada (404).
    Responde na hora (202) e roda o pipeline em segundo plano — a coleta completa
    pode levar vários minutos, mais que o timeout dos serviços de cron gratuitos.
    Útil no Render free tier: a chamada externa também acorda o serviço.
    """
    if not settings.cron_token:
        raise HTTPException(404, "Not Found")
    fornecido = x_cron_token or token or ""
    if not secrets.compare_digest(fornecido, settings.cron_token):
        raise HTTPException(401, "Token de cron inválido")
    tarefas.add_task(_pipeline_em_background, dias, limite_analises)
    return {"status": "coleta iniciada em segundo plano", "dias": dias, "limite_analises": limite_analises}


# ---------- Pipeline ----------

@router.get("/pipeline/status")
def status_pipeline(db: Session = Depends(get_db)):
    """Última execução do pipeline e estimativa da próxima (última + intervalo).

    Datas em UTC com sufixo Z — o frontend converte para o fuso local.
    """
    from datetime import timedelta

    from ..models import ExecucaoPipeline

    execucoes = db.execute(
        select(ExecucaoPipeline).order_by(ExecucaoPipeline.executado_em.desc()).limit(20)
    ).scalars().all()
    ultima = execucoes[0] if execucoes else None

    def _resumo(e):
        return {
            "executado_em": e.executado_em.isoformat() + "Z",
            "gatilho": e.gatilho,
            "novas_licitacoes": e.novas_licitacoes,
            "analisadas": e.analisadas,
            "oportunidades_criadas": e.oportunidades_criadas,
            "erros": e.erros,
            "avisos": e.avisos or [],
        }

    intervalo = settings.coleta_intervalo_horas
    proxima = ultima.executado_em + timedelta(hours=intervalo) if (ultima and intervalo > 0) else None
    return {
        "intervalo_horas": intervalo,
        "ultima_execucao": ultima.executado_em.isoformat() + "Z" if ultima else None,
        "proxima_estimada": proxima.isoformat() + "Z" if proxima else None,
        "ultimo_resultado": _resumo(ultima) if ultima else None,
        "historico": [_resumo(e) for e in execucoes],
    }


@router.post("/pipeline/executar")
def executar_pipeline(dias: int = 3, limite_analises: int = 10, db: Session = Depends(get_db)):
    """Roda coleta + análise IA agora."""
    return pipeline.executar_pipeline(db, dias=dias, limite_analises=limite_analises)


@router.post("/pipeline/coletar")
def executar_coleta(dias: int = 3, db: Session = Depends(get_db)):
    return pipeline.executar_coleta(db, dias=dias)


@router.post("/pipeline/analisar")
def executar_analises(limite: int = 10, db: Session = Depends(get_db)):
    return pipeline.executar_analises(db, limite=limite)


@router.post("/licitacoes/{licitacao_id}/reanalisar")
def reanalisar_licitacao(licitacao_id: int, db: Session = Depends(get_db)):
    """Refaz a análise IA de uma licitação (ex.: quando o edital não baixou na 1ª tentativa)."""
    if not db.get(Licitacao, licitacao_id):
        raise HTTPException(404, "Licitação não encontrada")
    return pipeline.executar_analises(db, licitacao_ids=[licitacao_id])


# ---------- Licitações ----------

class LicitacaoManualIn(BaseModel):
    objeto: str
    orgao: str = ""
    municipio: str = ""
    uf: str = ""
    modalidade: str = ""
    numero_certame: str = ""
    valor_estimado: float | None = None
    data_abertura: str = ""       # ISO (YYYY-MM-DD)
    data_encerramento: str = ""   # ISO (YYYY-MM-DD)
    link: str = ""
    edital_url: str = ""
    observacoes: str = ""
    responsavel: str = ""
    criar_oportunidade: bool = True
    analisar: bool = False


@router.post("/licitacoes", status_code=201)
def criar_licitacao_manual(dados: LicitacaoManualIn, db: Session = Depends(get_db)):
    """Cadastra uma licitação manualmente (fonte 'manual').

    Por padrão também cria a oportunidade correspondente no pipeline; se `analisar`
    for True, dispara a análise IA em seguida (falha na análise não bloqueia o cadastro).
    """
    if not dados.objeto.strip():
        raise HTTPException(400, "Informe o objeto da licitação")

    id_externo = dados.numero_certame.strip() or f"manual-{uuid4().hex[:12]}"
    existe = db.execute(
        select(Licitacao).where(Licitacao.fonte == "manual", Licitacao.id_externo == id_externo)
    ).scalar_one_or_none()
    if existe:
        raise HTTPException(409, f"Já existe uma licitação manual com o número de certame '{id_externo}'")

    lic = Licitacao(
        fonte="manual",
        id_externo=id_externo,
        orgao=dados.orgao.strip(),
        municipio=dados.municipio.strip(),
        uf=dados.uf.strip().upper()[:2],
        modalidade=dados.modalidade.strip(),
        objeto=dados.objeto.strip(),
        valor_estimado=dados.valor_estimado,
        data_abertura=dados.data_abertura.strip(),
        data_encerramento=dados.data_encerramento.strip(),
        link=dados.link.strip(),
        edital_url=dados.edital_url.strip() or dados.link.strip(),
    )
    db.add(lic)
    db.commit()

    oportunidade = None
    if dados.criar_oportunidade:
        oportunidade = Oportunidade(
            licitacao_id=lic.id, estagio="identificada",
            notas=dados.observacoes.strip(), responsavel=dados.responsavel.strip(),
        )
        db.add(oportunidade)
        db.commit()

    resultado_analise = None
    if dados.analisar:
        try:
            resultado_analise = pipeline.executar_analises(db, licitacao_ids=[lic.id])
        except Exception as exc:  # análise nunca bloqueia o cadastro
            resultado_analise = {"erro": f"Análise IA falhou: {exc}"}

    out = _licitacao_out(lic, db)
    out["oportunidade_id"] = oportunidade.id if oportunidade else None
    if resultado_analise is not None:
        out["analise_pipeline"] = resultado_analise
    return out


@router.get("/licitacoes")
def listar_licitacoes(status: str | None = None, uf: str | None = None,
                      limite: int = 100, db: Session = Depends(get_db)):
    q = select(Licitacao).order_by(Licitacao.criado_em.desc()).limit(limite)
    if status:
        q = q.where(Licitacao.status_analise == status)
    if uf:
        q = q.where(Licitacao.uf == uf.upper())
    itens = db.execute(q).scalars().all()
    return [_licitacao_out(l, db) for l in itens]


@router.get("/licitacoes/{licitacao_id}")
def obter_licitacao(licitacao_id: int, db: Session = Depends(get_db)):
    lic = db.get(Licitacao, licitacao_id)
    if not lic:
        raise HTTPException(404, "Licitação não encontrada")
    return _licitacao_out(lic, db, incluir_raw=True)


# ---------- Documentação (checklist + anexos) ----------

MAX_ANEXO_BYTES = 25 * 1024 * 1024  # 25 MB por arquivo


@router.get("/licitacoes/{licitacao_id}/documentos")
def listar_documentos(licitacao_id: int, db: Session = Depends(get_db)):
    """Checklist de documentos de habilitação (da análise IA) + anexos gravados.

    Cada item do checklist traz os anexos vinculados (casados pelo texto do documento);
    anexos sem item correspondente aparecem em `anexos_avulsos`. Nunca retorna o BLOB.
    """
    lic = db.get(Licitacao, licitacao_id)
    if not lic:
        raise HTTPException(404, "Licitação não encontrada")

    analise = db.execute(select(Analise).where(Analise.licitacao_id == licitacao_id)).scalar_one_or_none()
    checklist_ia = (analise.documentos_habilitacao if analise else None) or []

    anexos = db.execute(
        select(DocumentoAnexo)
        .where(DocumentoAnexo.licitacao_id == licitacao_id)
        .order_by(DocumentoAnexo.criado_em)
    ).scalars().all()

    itens_checklist = {(item.get("documento") or "").strip() for item in checklist_ia}
    por_item: dict[str, list] = {}
    avulsos = []
    for anexo in anexos:
        chave = (anexo.item_checklist or "").strip()
        if chave and chave in itens_checklist:
            por_item.setdefault(chave, []).append(_anexo_out(anexo))
        else:
            avulsos.append(_anexo_out(anexo))

    checklist = [
        {
            "categoria": item.get("categoria") or "OUTROS DOCUMENTOS / DECLARAÇÕES",
            "documento": item.get("documento") or "",
            "referencia_edital": item.get("referencia_edital") or "",
            "anexos": por_item.get((item.get("documento") or "").strip(), []),
        }
        for item in checklist_ia
    ]

    return {
        "licitacao_id": licitacao_id,
        "tem_checklist": bool(checklist),
        # Análise antiga (sem o campo) ou licitação ainda não analisada: uma
        # (re)análise gera o checklist estruturado a partir do edital.
        "reanalise_gera_checklist": not checklist,
        "checklist": checklist,
        "anexos_avulsos": avulsos,
    }


@router.post("/licitacoes/{licitacao_id}/documentos", status_code=201)
async def anexar_documento(
    licitacao_id: int,
    arquivo: UploadFile,
    item_checklist: str = Form(""),
    db: Session = Depends(get_db),
):
    """Anexa um arquivo à licitação (multipart). O conteúdo é gravado no SQLite.

    `item_checklist` (form, opcional) vincula o anexo a um item do checklist;
    vazio = anexo avulso. Tamanho máximo: 25 MB.
    """
    if not db.get(Licitacao, licitacao_id):
        raise HTTPException(404, "Licitação não encontrada")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(400, "Arquivo vazio")
    if len(conteudo) > MAX_ANEXO_BYTES:
        raise HTTPException(413, "Arquivo excede o tamanho máximo de 25 MB")

    anexo = DocumentoAnexo(
        licitacao_id=licitacao_id,
        item_checklist=item_checklist.strip() or None,
        nome_arquivo=arquivo.filename or "documento",
        content_type=arquivo.content_type or "application/octet-stream",
        tamanho=len(conteudo),
        conteudo=conteudo,
    )
    db.add(anexo)
    db.commit()
    return _anexo_out(anexo)


@router.get("/documentos/{doc_id}/download")
def baixar_documento(doc_id: int, db: Session = Depends(get_db)):
    anexo = db.get(DocumentoAnexo, doc_id)
    if not anexo:
        raise HTTPException(404, "Documento não encontrado")
    nome = quote(anexo.nome_arquivo or "documento")
    return Response(
        content=anexo.conteudo,
        media_type=anexo.content_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{nome}"},
    )


@router.delete("/documentos/{doc_id}")
def excluir_documento(doc_id: int, db: Session = Depends(get_db)):
    anexo = db.get(DocumentoAnexo, doc_id)
    if not anexo:
        raise HTTPException(404, "Documento não encontrado")
    db.delete(anexo)
    db.commit()
    return {"ok": True, "id": doc_id}


def _anexo_out(a: DocumentoAnexo) -> dict:
    """Metadados do anexo (sem o BLOB)."""
    return {
        "id": a.id,
        "licitacao_id": a.licitacao_id,
        "item_checklist": a.item_checklist,
        "nome_arquivo": a.nome_arquivo,
        "content_type": a.content_type,
        "tamanho": a.tamanho,
        "criado_em": a.criado_em.isoformat(),
    }


# ---------- Oportunidades (CRM) ----------

class OportunidadePatch(BaseModel):
    estagio: str | None = None
    notas: str | None = None
    responsavel: str | None = None


class OportunidadeIn(BaseModel):
    licitacao_id: int


@router.post("/oportunidades", status_code=201)
def criar_oportunidade(dados: OportunidadeIn, db: Session = Depends(get_db)):
    """Cria manualmente uma oportunidade para uma licitação (aba No Go -> Pipeline).

    Permite ao usuário discordar da IA e levar ao kanban uma licitação reprovada.
    """
    if not db.get(Licitacao, dados.licitacao_id):
        raise HTTPException(404, "Licitação não encontrada")
    existe = db.execute(
        select(Oportunidade).where(Oportunidade.licitacao_id == dados.licitacao_id)
    ).scalar_one_or_none()
    if existe:
        raise HTTPException(409, "Esta licitação já está no pipeline")
    op = Oportunidade(
        licitacao_id=dados.licitacao_id, estagio="identificada",
        notas="Movida manualmente da aba No Go",
    )
    db.add(op)
    db.commit()
    return _oportunidade_out(op, db)


@router.get("/oportunidades")
def listar_oportunidades(estagio: str | None = None, db: Session = Depends(get_db)):
    q = select(Oportunidade).order_by(Oportunidade.atualizado_em.desc())
    if estagio:
        q = q.where(Oportunidade.estagio == estagio)
    return [_oportunidade_out(o, db) for o in db.execute(q).scalars().all()]


@router.patch("/oportunidades/{oportunidade_id}")
def atualizar_oportunidade(oportunidade_id: int, patch: OportunidadePatch, db: Session = Depends(get_db)):
    op = db.get(Oportunidade, oportunidade_id)
    if not op:
        raise HTTPException(404, "Oportunidade não encontrada")
    if patch.estagio is not None:
        if patch.estagio not in Oportunidade.ESTAGIOS:
            raise HTTPException(400, f"Estágio inválido. Use um de: {Oportunidade.ESTAGIOS}")
        op.estagio = patch.estagio
    if patch.notas is not None:
        op.notas = patch.notas
    if patch.responsavel is not None:
        op.responsavel = patch.responsavel
    db.commit()
    return _oportunidade_out(op, db)


# ---------- Perfil da empresa ----------

class PerfilIn(BaseModel):
    descricao: str
    cnaes: list[str] = []
    ufs: list[str] = []
    valor_minimo: float | None = None
    valor_maximo: float | None = None
    palavras_chave: list[str] = []
    restricoes: list[str] = []


@router.get("/perfil")
def obter_perfil(db: Session = Depends(get_db)):
    return pipeline.perfil_como_dict(pipeline.obter_perfil(db))


@router.put("/perfil")
def atualizar_perfil(perfil_in: PerfilIn, db: Session = Depends(get_db)):
    perfil = pipeline.obter_perfil(db)
    for campo, valor in perfil_in.model_dump().items():
        setattr(perfil, campo, valor)
    db.commit()
    return pipeline.perfil_como_dict(perfil)


# ---------- Serializadores ----------

def _analise_out(a: Analise | None):
    if not a:
        return None
    return {
        "score": a.score, "veredito": a.veredito, "justificativa": a.justificativa,
        "objeto_resumido": a.objeto_resumido, "prazos": a.prazos,
        "exigencias_habilitacao": a.exigencias_habilitacao,
        "exigencias_tecnicas": a.exigencias_tecnicas,
        "atestados_exigidos": a.atestados_exigidos, "riscos": a.riscos,
        "documentos_habilitacao": a.documentos_habilitacao,
        "score_beneficios": a.score_beneficios,
        "score_pagamentos": a.score_pagamentos,
        "classificacao_final": a.classificacao_final,
        "credenciamento_viavel": a.credenciamento_viavel,
        "credenciamento_analise": a.credenciamento_analise,
        "alertas_impugnacao": a.alertas_impugnacao,
        "custo_emissao_cartoes": a.custo_emissao_cartoes,
        "analise_completa": a.analise_completa,
        "criado_em": a.criado_em.isoformat(),
    }


def _licitacao_out(l: Licitacao, db: Session, incluir_raw: bool = False):
    analise = db.execute(select(Analise).where(Analise.licitacao_id == l.id)).scalar_one_or_none()
    out = {
        "id": l.id, "fonte": l.fonte, "id_externo": l.id_externo, "orgao": l.orgao,
        "municipio": l.municipio, "uf": l.uf, "modalidade": l.modalidade, "objeto": l.objeto,
        "valor_estimado": l.valor_estimado, "data_abertura": l.data_abertura,
        "data_encerramento": l.data_encerramento, "link": l.link,
        "status_analise": l.status_analise, "analise": _analise_out(analise),
    }
    if incluir_raw:
        out["raw"] = l.raw_json
    return out


def _oportunidade_out(o: Oportunidade, db: Session):
    lic = db.get(Licitacao, o.licitacao_id)
    return {
        "id": o.id, "estagio": o.estagio, "notas": o.notas, "responsavel": o.responsavel,
        "criado_em": o.criado_em.isoformat(), "atualizado_em": o.atualizado_em.isoformat(),
        "licitacao": _licitacao_out(lic, db) if lic else None,
    }
