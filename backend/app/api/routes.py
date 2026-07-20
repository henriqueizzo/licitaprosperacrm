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
from ..models import Analise, DocumentoAnexo, Licitacao, Oportunidade, PerfilEmpresa, Usuario
from ..security import exigir_admin, usuario_atual
from ..services import pipeline
from ..services.atividade import eventos_recentes, registrar_evento, resumo_atividade
from ..services.dashboard import montar_dashboard

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Rotas SEM cookie de sessão (autenticação própria por token) — incluídas no
# main.py sem a dependency `usuario_atual`.
cron_router = APIRouter(prefix="/api")


@cron_router.get("/saude")
def saude():
    """Diagnóstico público mínimo (sem dados sensíveis): o processo está de pé,
    qual provedor de IA está ativo e qual commit está rodando (RENDER_GIT_COMMIT,
    setado pelo Render) — permite confirmar de fora que um deploy backend-only
    chegou ao processo."""
    import os

    from ..analyzer import provedor_ativo
    return {
        "ok": True,
        "ia_provider": provedor_ativo() or "nenhum",
        "commit": os.environ.get("RENDER_GIT_COMMIT", "")[:7],
    }


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
def executar_pipeline(
    dias: int = 3,
    limite_analises: int = 10,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Roda coleta + análise IA agora."""
    # registra antes de rodar: a coleta pode levar minutos e até falhar no meio
    registrar_evento(db, usuario, "coleta_manual", detalhe=f"dias={dias}, limite_analises={limite_analises}")
    return pipeline.executar_pipeline(db, dias=dias, limite_analises=limite_analises)


@router.post("/pipeline/coletar")
def executar_coleta(dias: int = 3, usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    registrar_evento(db, usuario, "coleta_manual", detalhe=f"apenas coleta, dias={dias}")
    return pipeline.executar_coleta(db, dias=dias)


@router.post("/pipeline/analisar")
def executar_analises(limite: int = 10, db: Session = Depends(get_db)):
    return pipeline.executar_analises(db, limite=limite)


@router.post("/licitacoes/{licitacao_id}/reanalisar")
def reanalisar_licitacao(
    licitacao_id: int,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Refaz a análise IA de uma licitação (ex.: quando o edital não baixou na 1ª tentativa)."""
    if not db.get(Licitacao, licitacao_id):
        raise HTTPException(404, "Licitação não encontrada")
    registrar_evento(db, usuario, "reanalise", licitacao_id=licitacao_id)
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
    # Análise transcrita do relatório anexado no preenchimento automático
    # (formato ResultadoAnalise). Quando presente, é gravada como análise da
    # licitação — habilita o checklist de Documentação sem reanálise IA.
    analise: dict | None = None


@router.post("/licitacoes", status_code=201)
def criar_licitacao_manual(
    dados: LicitacaoManualIn,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Cadastra uma licitação manualmente (fonte 'manual').

    Regra de negócio: registro manual SEMPRE vira oportunidade no pipeline e NÃO
    passa pela análise IA automática (status 'manual'). A reanálise sob demanda
    (botão "reanalisar") continua disponível. Os campos `criar_oportunidade` e
    `analisar` do payload são ignorados (compatibilidade com clientes antigos).
    """
    if not dados.objeto.strip():
        raise HTTPException(400, "Informe o objeto da licitação")

    # Truncamentos casados com os limites das colunas (o Postgres impõe; o SQLite não)
    id_externo = (dados.numero_certame.strip() or f"manual-{uuid4().hex[:12]}")[:120]
    existe = db.execute(
        select(Licitacao).where(Licitacao.fonte == "manual", Licitacao.id_externo == id_externo)
    ).scalar_one_or_none()
    if existe and existe.oportunidade:
        raise HTTPException(409, f"Já existe uma licitação manual com o número de certame '{id_externo}'")

    # Reaproveita cadastro que ficou pela metade (ex.: erro após gravar a licitação):
    # atualiza os dados e segue para criar a oportunidade/análise.
    lic = existe or Licitacao(fonte="manual", id_externo=id_externo)
    lic.orgao = dados.orgao.strip()[:300]
    lic.municipio = dados.municipio.strip()[:120]
    lic.uf = dados.uf.strip().upper()[:2]
    lic.modalidade = dados.modalidade.strip()[:80]
    lic.objeto = dados.objeto.strip()
    lic.valor_estimado = dados.valor_estimado
    lic.data_abertura = dados.data_abertura.strip()[:30]
    lic.data_encerramento = dados.data_encerramento.strip()[:30]
    lic.link = dados.link.strip()
    lic.edital_url = dados.edital_url.strip() or dados.link.strip()
    if lic.status_analise != "analisada":
        # 'manual' fica fora do lote automático de análise IA (regra de negócio)
        lic.status_analise = "manual"
    db.add(lic)
    db.commit()

    oportunidade = Oportunidade(
        licitacao_id=lic.id, estagio="identificada",
        notas=dados.observacoes.strip(), responsavel=dados.responsavel.strip(),
    )
    db.add(oportunidade)
    db.commit()

    if dados.analise:
        _gravar_analise_importada(db, lic, dados.analise)

    registrar_evento(db, usuario, "cadastro_manual", licitacao_id=lic.id, detalhe=lic.objeto[:200])

    out = _licitacao_out(lic, db)
    out["oportunidade_id"] = oportunidade.id
    return out


def _gravar_analise_importada(db: Session, lic: Licitacao, analise_bruta: dict) -> bool:
    """Grava uma análise transcrita de relatório anexado (cadastro manual ou card).

    Mesmo formato da análise do pipeline (ResultadoAnalise). Se o payload vier
    inválido, NÃO levanta — retorna False (quem chama decide se falha).
    """
    from ..analyzer.schemas import ResultadoAnalise
    from ..services.pipeline import _derivar_veredito

    try:
        resultado = ResultadoAnalise.model_validate(analise_bruta).normalizar()
    except Exception as exc:
        logger.warning("Análise importada inválida para a licitação %s: %s", lic.id, exc)
        return False

    # Reaproveitamento de cadastro pela metade: descarta análise anterior
    for antiga in db.execute(select(Analise).where(Analise.licitacao_id == lic.id)).scalars():
        db.delete(antiga)

    maior_score = max(resultado.score_beneficios, resultado.score_pagamentos)
    db.add(Analise(
        licitacao_id=lic.id,
        score=maior_score * 10,
        veredito=_derivar_veredito(resultado),
        justificativa=resultado.justificativa,
        objeto_resumido=resultado.objeto_resumido,
        prazos=[p.model_dump() for p in resultado.prazos],
        exigencias_habilitacao=resultado.exigencias_habilitacao,
        exigencias_tecnicas=resultado.exigencias_tecnicas,
        atestados_exigidos=resultado.atestados_exigidos,
        documentos_habilitacao=[d.model_dump() for d in resultado.documentos_habilitacao],
        riscos=resultado.riscos,
        score_beneficios=resultado.score_beneficios,
        score_pagamentos=resultado.score_pagamentos,
        classificacao_final=resultado.classificacao_final,
        credenciamento_viavel=resultado.credenciamento_viavel,
        credenciamento_analise=resultado.credenciamento_analise,
        alertas_impugnacao=resultado.alertas_impugnacao,
        custo_emissao_cartoes=resultado.custo_emissao_cartoes,
        analise_completa=resultado.analise_completa,
        tokens_entrada=0,
        tokens_saida=0,
    ))
    lic.status_analise = "analisada"
    db.commit()
    return True


# ---------- Preenchimento automático do Cadastro Manual ----------

class ExtrairIn(BaseModel):
    texto: str = ""   # resumo/texto colado pelo usuário
    url: str = ""     # ou link da licitação (página do portal ou PDF do edital)


@router.post("/licitacoes/extrair")
def extrair_campos_licitacao(
    dados: ExtrairIn,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Extrai os campos do formulário de cadastro a partir de um resumo ou link.

    Baixa o conteúdo do link (HTML vira texto; PDF vai direto para a IA) e usa o
    provedor de IA ativo para devolver os campos estruturados — o usuário revisa
    antes de cadastrar.
    """
    from ..analyzer import ErroCotaIA, criar_analisador

    texto = dados.texto.strip()
    url = dados.url.strip()
    if not texto and not url:
        raise HTTPException(400, "Cole o resumo da licitação ou informe o link")

    pdf = None
    if url:
        conteudo_html, pdf = _baixar_conteudo(url)
        if conteudo_html:
            texto = (texto + "\n\n" + conteudo_html).strip()
        if not conteudo_html and not pdf:
            if not texto:
                raise HTTPException(
                    422,
                    "Não consegui ler o conteúdo desse link (página protegida ou dinâmica). "
                    "Cole o resumo/texto da licitação e tente de novo.",
                )

    try:
        extracao = criar_analisador().extrair(texto=texto or None, pdf_bytes=pdf)
    except ErroCotaIA as exc:
        raise HTTPException(503, f"IA indisponível no momento: {exc}")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))

    registrar_evento(db, usuario, "extracao_cadastro", detalhe=(url or "texto colado")[:300])

    out = extracao.campos.model_dump()
    out["link"] = url or extracao.campos.link
    out["analise"] = extracao.analise.model_dump() if extracao.analise else None
    return out


MAX_PDF_EXTRACAO = 19 * 1024 * 1024  # limite inline do Gemini


@router.post("/licitacoes/extrair-arquivo")
async def extrair_campos_de_pdf(
    arquivo: UploadFile,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Extrai os campos do cadastro a partir de um PDF do edital anexado pelo usuário.

    Mesmo fluxo do /licitacoes/extrair, mas com o arquivo enviado direto (multipart)
    em vez de link — útil quando o edital só existe como arquivo local.
    """
    from ..analyzer import ErroCotaIA, criar_analisador

    conteudo = await arquivo.read()
    if not conteudo.startswith(b"%PDF"):
        raise HTTPException(400, "Envie um arquivo PDF (o edital em .pdf).")
    if len(conteudo) > MAX_PDF_EXTRACAO:
        raise HTTPException(413, "PDF excede o tamanho máximo de 19 MB para leitura pela IA.")

    try:
        extracao = criar_analisador().extrair(pdf_bytes=conteudo)
    except ErroCotaIA as exc:
        raise HTTPException(503, f"IA indisponível no momento: {exc}")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))

    registrar_evento(db, usuario, "extracao_cadastro", detalhe=f"pdf: {arquivo.filename or ''}"[:300])
    out = extracao.campos.model_dump()
    out["analise"] = extracao.analise.model_dump() if extracao.analise else None
    return out


@router.post("/licitacoes/{licitacao_id}/analise-arquivo")
async def importar_analise_de_pdf(
    licitacao_id: int,
    arquivo: UploadFile,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Importa a análise de um relatório em PDF para uma licitação já cadastrada.

    Substitui a reanálise IA nos cards: o operador anexa o relatório de análise
    feito pelo time (mesmo formato do Cadastro Manual) e o card é atualizado —
    classificação, scores, alertas e o checklist de documentação. Campos vazios
    da licitação (valor, datas, município…) são preenchidos com o que o
    relatório trouxer; campos já preenchidos NUNCA são sobrescritos.
    """
    from ..analyzer import ErroCotaIA, criar_analisador

    lic = db.get(Licitacao, licitacao_id)
    if not lic:
        raise HTTPException(404, "Licitação não encontrada")

    conteudo = await arquivo.read()
    if not conteudo.startswith(b"%PDF"):
        raise HTTPException(400, "Envie um arquivo PDF (o relatório de análise em .pdf).")
    if len(conteudo) > MAX_PDF_EXTRACAO:
        raise HTTPException(413, "PDF excede o tamanho máximo de 19 MB para leitura pela IA.")

    try:
        extracao = criar_analisador().extrair(pdf_bytes=conteudo)
    except ErroCotaIA as exc:
        raise HTTPException(503, f"IA indisponível no momento: {exc}")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))

    if extracao.analise is None:
        raise HTTPException(
            422,
            "Este PDF não parece ser um relatório de análise (não encontrei checklist de "
            "documentos, scores e classificação). Anexe o PDF da nossa análise do edital.",
        )

    if not _gravar_analise_importada(db, lic, extracao.analise.model_dump()):
        raise HTTPException(422, "Não consegui estruturar a análise deste PDF — tente novamente.")

    # Complementa campos vazios da licitação com o que o relatório trouxer
    # (nunca sobrescreve o que já está preenchido)
    c = extracao.campos
    if not lic.objeto and c.objeto:
        lic.objeto = c.objeto.strip()
    if not lic.orgao and c.orgao:
        lic.orgao = c.orgao.strip()[:300]
    if not lic.municipio and c.municipio:
        lic.municipio = c.municipio.strip()[:120]
    if not lic.uf and c.uf:
        lic.uf = c.uf.strip().upper()[:2]
    if not lic.modalidade and c.modalidade:
        lic.modalidade = c.modalidade.strip()[:80]
    if lic.valor_estimado is None and c.valor_estimado is not None:
        lic.valor_estimado = c.valor_estimado
    if not lic.data_abertura and c.data_abertura:
        lic.data_abertura = c.data_abertura.strip()[:30]
    if not lic.data_encerramento and c.data_encerramento:
        lic.data_encerramento = c.data_encerramento.strip()[:30]
    if not lic.link and c.link:
        lic.link = c.link.strip()

    # Contato/forma de envio do relatório vão para as notas do card, se vazias
    if c.observacoes or c.responsavel:
        oportunidade = db.execute(
            select(Oportunidade).where(Oportunidade.licitacao_id == lic.id)
        ).scalars().first()
        if oportunidade and not (oportunidade.notas or "").strip():
            notas = []
            if c.responsavel:
                notas.append(f"Responsável pelo certame: {c.responsavel.strip()}")
            if c.observacoes:
                notas.append(c.observacoes.strip())
            oportunidade.notas = "\n".join(notas)
    db.commit()

    registrar_evento(
        db, usuario, "importar_analise", licitacao_id=lic.id,
        detalhe=f"pdf: {arquivo.filename or ''}"[:300],
    )
    return _licitacao_out(lic, db)


def _baixar_conteudo(url: str) -> tuple[str | None, bytes | None]:
    """Baixa o link do usuário. Retorna (texto_da_pagina, pdf_bytes) — um dos dois."""
    import httpx

    try:
        with httpx.Client(timeout=45, follow_redirects=True, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
        }) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("Falha ao baixar link para extração %s: %s", url, exc)
        return None, None

    if resp.content[:5].startswith(b"%PDF"):
        return None, resp.content if len(resp.content) <= 19 * 1024 * 1024 else None
    return _html_para_texto(resp.text), None


def _html_para_texto(html: str) -> str | None:
    """Reduz HTML a texto puro (sem scripts/estilos) para a extração por IA."""
    import html as html_lib
    import re as re_lib

    sem_blocos = re_lib.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    texto = re_lib.sub(r"(?s)<[^>]+>", " ", sem_blocos)
    texto = html_lib.unescape(texto)
    texto = re_lib.sub(r"\s+", " ", texto).strip()
    return texto[:80000] or None


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


@router.delete("/licitacoes/{licitacao_id}")
def excluir_licitacao(
    licitacao_id: int,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Exclui a licitação e tudo dela (card, análise, documentos) — IRREVERSÍVEL.

    Grava uma lápide em licitacoes_excluidas para a coleta não trazer a mesma
    licitação de volta no próximo ciclo. Eventos de auditoria são preservados
    (licitacao_id vira NULL).
    """
    from sqlalchemy import update as sql_update

    from ..models import EventoUso, LicitacaoExcluida

    lic = db.get(Licitacao, licitacao_id)
    if not lic:
        raise HTTPException(404, "Licitação não encontrada")

    descricao = f"{lic.orgao} — {(lic.objeto or '')[:150]}"
    db.execute(
        sql_update(EventoUso).where(EventoUso.licitacao_id == lic.id)
        .values(licitacao_id=None)
    )
    for analise in db.execute(select(Analise).where(Analise.licitacao_id == lic.id)).scalars():
        db.delete(analise)
    for doc in db.execute(select(DocumentoAnexo).where(DocumentoAnexo.licitacao_id == lic.id)).scalars():
        db.delete(doc)
    if lic.oportunidade:
        db.delete(lic.oportunidade)
    ja_tem_lapide = db.execute(
        select(LicitacaoExcluida).where(
            LicitacaoExcluida.fonte == lic.fonte,
            LicitacaoExcluida.id_externo == lic.id_externo,
        )
    ).scalar_one_or_none()
    if not ja_tem_lapide:
        db.add(LicitacaoExcluida(
            fonte=lic.fonte, id_externo=lic.id_externo,
            descricao=descricao, excluido_por=usuario.nome,
        ))
    db.delete(lic)
    db.commit()

    registrar_evento(db, usuario, "excluir_licitacao", detalhe=descricao[:300])
    return {"ok": True, "excluida": descricao}


class LicitacaoPatch(BaseModel):
    """Campos editáveis pelo time. Só o que vier no corpo é alterado.

    Caso de uso principal: certame suspenso volta com data de vencimento nova —
    edita o vencimento, reativa e reanalisa para comparar com o edital anterior.
    """
    orgao: str | None = None
    municipio: str | None = None
    uf: str | None = None
    modalidade: str | None = None
    objeto: str | None = None
    valor_estimado: float | None = None
    data_abertura: str | None = None
    data_encerramento: str | None = None
    link: str | None = None
    suspensa: bool | None = None


@router.patch("/licitacoes/{licitacao_id}")
def atualizar_licitacao(
    licitacao_id: int,
    dados: LicitacaoPatch,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    lic = db.get(Licitacao, licitacao_id)
    if not lic:
        raise HTTPException(404, "Licitação não encontrada")

    mudancas = dados.model_dump(exclude_unset=True)
    if not mudancas:
        raise HTTPException(400, "Nenhum campo para atualizar")
    if "uf" in mudancas and mudancas["uf"]:
        mudancas["uf"] = mudancas["uf"].strip().upper()[:2]
    for campo, valor in mudancas.items():
        setattr(lic, campo, valor)
    db.commit()

    detalhe = ", ".join(
        f"{campo}={valor!r}" for campo, valor in mudancas.items()
    )
    registrar_evento(db, usuario, "editar_licitacao", licitacao_id=lic.id, detalhe=detalhe[:300])
    return _licitacao_out(lic, db)


# ---------- Documentação (checklist + anexos) ----------

MAX_ANEXO_BYTES = 25 * 1024 * 1024  # 25 MB por arquivo


@router.get("/licitacoes/{licitacao_id}/documentos")
def listar_documentos(
    licitacao_id: int,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Checklist de documentos de habilitação (da análise IA) + anexos gravados.

    Cada item do checklist traz os anexos vinculados (casados pelo texto do documento);
    anexos sem item correspondente aparecem em `anexos_avulsos`. Nunca retorna o BLOB.
    """
    lic = db.get(Licitacao, licitacao_id)
    if not lic:
        raise HTTPException(404, "Licitação não encontrada")

    # abertura da tela de documentação de uma licitação (não é polling)
    registrar_evento(db, usuario, "ver_documentos", licitacao_id=licitacao_id)

    analise = _analise_da_licitacao(db, licitacao_id)
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
    usuario: Usuario = Depends(usuario_atual),
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
    registrar_evento(db, usuario, "upload_documento", licitacao_id=licitacao_id,
                     detalhe=anexo.nome_arquivo)
    return _anexo_out(anexo)


@router.get("/documentos/{doc_id}/download")
def baixar_documento(doc_id: int, usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    anexo = db.get(DocumentoAnexo, doc_id)
    if not anexo:
        raise HTTPException(404, "Documento não encontrado")
    registrar_evento(db, usuario, "download_documento", licitacao_id=anexo.licitacao_id,
                     detalhe=anexo.nome_arquivo)
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


# POST /oportunidades (promoção manual da antiga aba No Go) foi removido: toda
# licitação coletada já entra no pipeline automaticamente como 'identificada'.


@router.get("/oportunidades")
def listar_oportunidades(estagio: str | None = None, db: Session = Depends(get_db)):
    q = select(Oportunidade).order_by(Oportunidade.atualizado_em.desc())
    if estagio:
        q = q.where(Oportunidade.estagio == estagio)
    return [_oportunidade_out(o, db) for o in db.execute(q).scalars().all()]


@router.patch("/oportunidades/{oportunidade_id}")
def atualizar_oportunidade(
    oportunidade_id: int,
    patch: OportunidadePatch,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    op = db.get(Oportunidade, oportunidade_id)
    if not op:
        raise HTTPException(404, "Oportunidade não encontrada")
    estagio_anterior = op.estagio
    if patch.estagio is not None:
        if patch.estagio not in Oportunidade.ESTAGIOS:
            raise HTTPException(400, f"Estágio inválido. Use um de: {Oportunidade.ESTAGIOS}")
        op.estagio = patch.estagio
    if patch.notas is not None:
        op.notas = patch.notas
    if patch.responsavel is not None:
        op.responsavel = patch.responsavel
    db.commit()
    if patch.estagio is not None and patch.estagio != estagio_anterior:
        registrar_evento(db, usuario, "mover_estagio", licitacao_id=op.licitacao_id,
                         detalhe=f"de {estagio_anterior} para {patch.estagio}")
    return _oportunidade_out(op, db)


# ---------- Declarações em Word ----------

class DeclaracaoIn(BaseModel):
    documento: str            # texto do item do checklist (a declaração exigida)
    referencia: str = ""      # referência no edital (item/cláusula), se houver


@router.post("/licitacoes/{licitacao_id}/declaracoes")
def gerar_declaracao(
    licitacao_id: int,
    dados: DeclaracaoIn,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Gera a declaração exigida pelo edital em Word (.docx), pronta para assinar.

    O texto é redigido pela IA do provedor ativo (fallback: modelo genérico) e o
    documento sai com a identidade Prospera + bloco de assinatura do representante
    legal cadastrado na aba Perfil. O header X-Texto-Origem indica 'ia' ou 'modelo'.
    """
    from ..services import declaracoes

    lic = db.get(Licitacao, licitacao_id)
    if not lic:
        raise HTTPException(404, "Licitação não encontrada")
    documento = dados.documento.strip()
    if not documento:
        raise HTTPException(400, "Informe qual declaração deve ser gerada")

    perfil = pipeline.obter_perfil(db)
    texto, origem = declaracoes.redigir_texto(lic, perfil, documento, dados.referencia.strip())
    docx_bytes = declaracoes.gerar_docx(lic, perfil, documento, dados.referencia.strip(), texto)

    registrar_evento(db, usuario, "gerar_declaracao", licitacao_id=lic.id, detalhe=documento[:200])

    arquivo = declaracoes.nome_arquivo(lic, documento)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(arquivo)}",
            "X-Texto-Origem": origem,
        },
    )


# ---------- Perfil da empresa ----------

class PerfilIn(BaseModel):
    descricao: str
    cnaes: list[str] = []
    ufs: list[str] = []
    valor_minimo: float | None = None
    valor_maximo: float | None = None
    palavras_chave: list[str] = []
    restricoes: list[str] = []
    # Dados oficiais para as declarações geradas em Word
    razao_social: str = ""
    cnpj: str = ""
    endereco: str = ""
    cidade_sede: str = ""
    representante_nome: str = ""
    representante_cargo: str = ""


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


# ---------- Dashboard executivo (report ao CEO) ----------

@router.get("/dashboard")
def dashboard(
    dias: int = 30,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Dados agregados da aba Dashboard nos últimos `dias` (clampado 1–365).

    Formato da resposta:
    {
      "dias": 30, "gerado_em": "2026-07-15T12:00:00Z",
      "indicadores": {
        "licitacoes_coletadas": 42,      // licitações que entraram no período
        "oportunidades_novas": 40,       // oportunidades criadas no período
        "valor_em_disputa": 1234567.0,   // soma dos estágios ativos (foto atual)
        "valor_ganho": 100000.0,         // finalizadas em 'ganhou' no período
        "valor_perdido": 50000.0,        // finalizadas em 'perdeu_nogo' no período
        "ganhas": 2, "perdidas": 1,
        "taxa_vitoria": 66.7             // % ganhas/(ganhas+perdidas); null sem finalizadas
      },
      "funil": [{"estagio", "quantidade", "valor"}, ...],  // ordem do kanban, foto atual
      "por_uf": [{"uf", "quantidade"}, ...],               // licitações do período, desc
      "por_fonte": [{"fonte", "quantidade"}, ...],         // pncp/fiesc/fiergs/fiems/manual
      "classificacoes": [{"classificacao", "quantidade"}, ...],  // IA + "SEM ANÁLISE"
      "vencimentos_proximos": [{oportunidade_id, licitacao_id, orgao, municipio, uf,
                                objeto, valor_estimado, data_encerramento,
                                dias_restantes, estagio}, ...],  // ativas, <= 14 dias
      "coletas_por_dia": [{"dia": "2026-07-01", "quantidade": 3}, ...],  // série contínua
      "atividade": {"usuarios": [...]}   // só quando o usuário é admin (resumo_atividade)
    }
    Qualquer usuário autenticado acessa; o bloco "atividade" só vai para admin.
    """
    dias = max(1, min(dias, 365))
    dados = montar_dashboard(db, dias)
    if usuario.is_admin:
        dados["atividade"] = {"usuarios": resumo_atividade(db, dias)}
    return dados


# ---------- Atividade dos usuários (só admin) ----------

@router.get("/admin/atividade")
def atividade_resumo(
    dias: int = 30,
    _: Usuario = Depends(exigir_admin),
    db: Session = Depends(get_db),
):
    """Resumo de atividade por usuário nos últimos `dias` (aba Atividade e dashboard).

    Formato da resposta (estável — o dashboard também consome):
    {
      "dias": 30,
      "usuarios": [
        {
          "usuario_id": 1, "nome": "...", "email": "...", "ativo": true,
          "ultimo_acesso": "2026-07-15T12:00:00Z" | null,
          "total_eventos": 42,           // eventos no período
          "licitacoes_distintas": 7,     // licitações diferentes acessadas
          "tempo_uso_minutos": 95,       // estimativa: gaps < 30 min somam; maiores contam 1 min
          "eventos_por_tipo": {"login": 3, "ver_documentos": 12, ...}
        }, ...
      ]
    }
    Ordenado por total_eventos desc; inclui usuários sem eventos no período.
    """
    dias = max(1, min(dias, 365))
    return {"dias": dias, "usuarios": resumo_atividade(db, dias)}


@router.get("/admin/atividade/eventos")
def atividade_eventos(
    usuario_id: int | None = None,
    dias: int = 30,
    limit: int = 100,
    _: Usuario = Depends(exigir_admin),
    db: Session = Depends(get_db),
):
    """Eventos recentes (desc), opcionalmente filtrados por usuário.

    Cada evento: id, usuario_id, usuario_nome, tipo, licitacao_id,
    licitacao_objeto/licitacao_orgao (null quando não há licitação vinculada),
    detalhe e criado_em (ISO UTC com Z).
    """
    dias = max(1, min(dias, 365))
    limit = max(1, min(limit, 500))
    return {
        "dias": dias,
        "eventos": eventos_recentes(db, usuario_id=usuario_id, dias=dias, limit=limit),
    }


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


def _docs_progresso(l: Licitacao, db: Session, analise: Analise | None):
    """Progresso da documentação para o cartão do kanban: quantos itens do
    checklist da IA já têm anexo (casados pelo texto, como em listar_documentos)
    + anexos avulsos fora do checklist."""
    checklist = (analise.documentos_habilitacao if analise else None) or []
    chaves = [
        (chave or "").strip()
        for chave in db.execute(
            select(DocumentoAnexo.item_checklist).where(DocumentoAnexo.licitacao_id == l.id)
        ).scalars().all()
    ]
    itens = [(item.get("documento") or "").strip() for item in checklist]
    conjunto_chaves, conjunto_itens = set(chaves), set(itens)
    anexados = sum(1 for texto in itens if texto and texto in conjunto_chaves)
    avulsos = sum(1 for chave in chaves if not chave or chave not in conjunto_itens)
    return {"itens": len(itens), "anexados": anexados, "avulsos": avulsos}


def _analise_da_licitacao(db: Session, licitacao_id: int) -> Analise | None:
    """Análise mais recente da licitação.

    Usa first() em vez de scalar_one_or_none(): se uma duplicata escapar (ex.:
    duas importações concorrentes), a listagem NÃO pode cair com 500 — mostra a
    mais nova e o startup limpa o resto.
    """
    return db.execute(
        select(Analise).where(Analise.licitacao_id == licitacao_id).order_by(Analise.id.desc())
    ).scalars().first()


def _licitacao_out(l: Licitacao, db: Session, incluir_raw: bool = False):
    analise = _analise_da_licitacao(db, l.id)
    out = {
        "id": l.id, "fonte": l.fonte, "id_externo": l.id_externo, "orgao": l.orgao,
        "municipio": l.municipio, "uf": l.uf, "modalidade": l.modalidade, "objeto": l.objeto,
        "valor_estimado": l.valor_estimado, "data_abertura": l.data_abertura,
        "data_encerramento": l.data_encerramento, "link": l.link,
        "status_analise": l.status_analise, "suspensa": l.suspensa,
        "analise": _analise_out(analise),
        "documentos": _docs_progresso(l, db, analise),
        # Data de identificação da licitação (quando entrou no sistema)
        "criado_em": l.criado_em.isoformat() if l.criado_em else None,
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
