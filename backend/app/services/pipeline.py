"""Pipeline: coleta -> deduplicação -> download do edital -> análise IA -> CRM."""
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analyzer import AnalisadorEdital
from ..collectors import coletores_ativos
from ..collectors.pncp import PNCPCollector
from ..config import settings
from ..models import PERFIL_PADRAO, Analise, ExecucaoPipeline, Licitacao, Oportunidade, PerfilEmpresa

logger = logging.getLogger(__name__)


def obter_perfil(db: Session) -> PerfilEmpresa:
    perfil = db.get(PerfilEmpresa, 1)
    if not perfil:
        perfil = PerfilEmpresa(id=1, **PERFIL_PADRAO)
        db.add(perfil)
        db.commit()
    return perfil


def perfil_como_dict(perfil: PerfilEmpresa) -> dict:
    return {
        "descricao": perfil.descricao,
        "cnaes": perfil.cnaes or [],
        "ufs": perfil.ufs or [],
        "valor_minimo": perfil.valor_minimo,
        "valor_maximo": perfil.valor_maximo,
        "palavras_chave": perfil.palavras_chave or [],
        "restricoes": perfil.restricoes or [],
    }


def executar_coleta(db: Session, dias: int = 3) -> dict:
    """Coleta licitações novas de todas as fontes ativas e grava no banco."""
    perfil = obter_perfil(db)
    ufs = perfil.ufs or ["RS", "SC", "PR"]
    palavras = perfil.palavras_chave or []
    novas = 0
    avisos: list[str] = []

    for coletor in coletores_ativos(settings):
        try:
            coletadas = coletor.coletar(ufs, palavras, dias=dias)
        except Exception as exc:
            logger.error("Coletor %s falhou: %s", coletor.fonte, exc)
            avisos.append(f"Coletor {coletor.fonte} falhou: {exc}")
            continue

        if getattr(coletor, "falhas", 0) > 0:
            avisos.append(
                f"{coletor.fonte}: {coletor.falhas} consulta(s) falharam mesmo após novas tentativas "
                "(portal instável ou limite de requisições) — a cobertura desta coleta pode estar "
                "incompleta; rode novamente mais tarde."
            )

        for c in coletadas:
            existe = db.execute(
                select(Licitacao).where(Licitacao.fonte == c.fonte, Licitacao.id_externo == c.id_externo)
            ).scalar_one_or_none()
            if existe:
                continue
            db.add(Licitacao(
                fonte=c.fonte, id_externo=c.id_externo, orgao=c.orgao, municipio=c.municipio,
                uf=c.uf, modalidade=c.modalidade, objeto=c.objeto, valor_estimado=c.valor_estimado,
                data_abertura=c.data_abertura, data_encerramento=c.data_encerramento,
                link=c.link, edital_url=c.edital_url, raw_json=c.raw,
            ))
            novas += 1
    db.commit()
    resultado = {"novas_licitacoes": novas}
    if avisos:
        resultado["avisos"] = avisos
    return resultado


def executar_analises(db: Session, limite: int = 10, licitacao_ids: list[int] | None = None) -> dict:
    """Analisa licitações pendentes com a IA; cria oportunidade se o score passar do corte.

    Se `licitacao_ids` for passado, reanalisa essas licitações (removendo a análise anterior).
    """
    if not settings.anthropic_api_key:
        return {"erro": "ANTHROPIC_API_KEY não configurada no .env — análise IA desativada"}

    perfil = obter_perfil(db)
    perfil_dict = perfil_como_dict(perfil)
    analisador = AnalisadorEdital()

    if licitacao_ids:
        pendentes = db.execute(
            select(Licitacao).where(Licitacao.id.in_(licitacao_ids))
        ).scalars().all()
        for lic in pendentes:  # descarta análises anteriores
            for antiga in db.execute(select(Analise).where(Analise.licitacao_id == lic.id)).scalars():
                db.delete(antiga)
        db.commit()
    else:
        pendentes = db.execute(
            select(Licitacao).where(Licitacao.status_analise == "pendente").limit(limite)
        ).scalars().all()

    analisadas, oportunidades, erros = 0, 0, 0
    for lic in pendentes:
        pdf = None
        if lic.fonte == "pncp" and lic.edital_url:
            pdf = PNCPCollector.baixar_edital(lic.edital_url)
        elif lic.fonte == "manual" and lic.edital_url:
            pdf = _baixar_pdf_direto(lic.edital_url)
        try:
            resultado, usage = analisador.analisar(_dados(lic), perfil_dict, pdf)
        except Exception as exc:
            logger.error("Análise da licitação %s falhou: %s", lic.id, exc)
            lic.status_analise = "erro"
            erros += 1
            db.commit()
            continue

        # Score de compatibilidade (0-100) = maior score das duas empresas (0-10) x 10
        maior_score = max(resultado.score_beneficios, resultado.score_pagamentos)
        score_100 = maior_score * 10
        veredito = _derivar_veredito(resultado)

        db.add(Analise(
            licitacao_id=lic.id,
            score=score_100,
            veredito=veredito,
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
            tokens_entrada=usage.input_tokens,
            tokens_saida=usage.output_tokens,
        ))
        lic.status_analise = "analisada"
        analisadas += 1

        # Cria oportunidade quando: credenciamento viável, classificação não é
        # NÃO RECOMENDADO e o MAIOR dos dois scores (na escala 0-100) passa do corte.
        cria_oportunidade = (
            resultado.credenciamento_viavel
            and resultado.classificacao_final != "NÃO RECOMENDADO"
            and score_100 >= settings.score_minimo_oportunidade
        )
        if cria_oportunidade:
            ja_existe = db.execute(
                select(Oportunidade).where(Oportunidade.licitacao_id == lic.id)
            ).scalar_one_or_none()
            if not ja_existe:
                db.add(Oportunidade(licitacao_id=lic.id, estagio="identificada"))
                oportunidades += 1
        db.commit()

    return {"analisadas": analisadas, "oportunidades_criadas": oportunidades, "erros": erros}


def executar_pipeline(db: Session, dias: int = 3, limite_analises: int = 10,
                      gatilho: str = "manual") -> dict:
    coleta = executar_coleta(db, dias=dias)
    analises = executar_analises(db, limite=limite_analises)
    resultado = {**coleta, **analises}
    # Registra a execução (alimenta o status "última/próxima coleta" do cabeçalho).
    # `analises` pode vir como {"erro": ...} sem contadores — get() cobre esse caso.
    db.add(ExecucaoPipeline(
        gatilho=gatilho,
        novas_licitacoes=resultado.get("novas_licitacoes", 0),
        analisadas=resultado.get("analisadas", 0),
        oportunidades_criadas=resultado.get("oportunidades_criadas", 0),
        erros=resultado.get("erros", 0),
    ))
    db.commit()
    return resultado


def _baixar_pdf_direto(url: str) -> bytes | None:
    """Baixa um PDF de URL direta (licitações cadastradas manualmente).

    Retorna None se a URL não apontar para um PDF — a análise segue só com os metadados.
    """
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            if b"%PDF" in resp.content[:1024]:
                return resp.content
            logger.info("URL do edital manual não é um PDF direto, analisando só metadados: %s", url)
    except Exception as exc:
        logger.warning("Falha ao baixar edital manual %s: %s", url, exc)
    return None


def _derivar_veredito(resultado) -> str:
    """Traduz a classificação oficial para o veredito legado (compatibilidade).

    - Credenciamento inviável ou NÃO RECOMENDADO -> nao_participar
    - EXCELENTE/BOA OPORTUNIDADE -> participar
    - OPORTUNIDADE MODERADA / ALTO RISCO -> revisar_manual
    """
    if not resultado.credenciamento_viavel or resultado.classificacao_final == "NÃO RECOMENDADO":
        return "nao_participar"
    if resultado.classificacao_final in ("EXCELENTE OPORTUNIDADE", "BOA OPORTUNIDADE"):
        return "participar"
    return "revisar_manual"


def _dados(lic: Licitacao) -> dict:
    return {
        "orgao": lic.orgao, "municipio": lic.municipio, "uf": lic.uf,
        "modalidade": lic.modalidade, "objeto": lic.objeto,
        "valor_estimado": lic.valor_estimado,
        "data_abertura": lic.data_abertura, "data_encerramento": lic.data_encerramento,
    }
