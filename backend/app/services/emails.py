"""Agente dos "E-mails do Dario": lê os boletins encaminhados, confere a base e
decide o que entra no pipeline.

Fluxo por e-mail (processar_boletim):
  1. parse determinístico do boletim (emails_parser) -> N itens (ItemEmail)
  2. etapas sem IA (classificar_sem_ia), nesta ordem:
     - repetido: a mesma licitação já veio em e-mail anterior -> herda a decisão
     - ignorado: o time já excluiu essa licitação do pipeline (lápide)
     - ja_na_base: a coleta pública (PNCP/Sistema S/manual) já tem a licitação
     - fora_do_perfil: UF fora das UFs de atuação cadastradas no Perfil
  3. triagem por IA (triar_pendentes) do que sobrou, UMA chamada por lote:
     aderente ao perfil -> importada (Licitacao fonte "email_dario" + card
     "identificada", status "pendente" para o pipeline analisar o edital);
     senão -> fora_do_perfil (com o motivo). IA indisponível -> aguardando_ia
     (tenta de novo na próxima sincronização).

A coleta do PNCP consulta `licitacao_email_correspondente` antes de inserir: se a
licitação do e-mail aparecer depois no PNCP, o card do e-mail é ENRIQUECIDO (edital,
valor, datas) em vez de duplicado — e volta a "pendente" para ser analisado com o
edital de verdade.
"""
import hashlib
import logging
import re
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analyzer import ErroCotaIA, criar_analisador, provedor_ativo
from ..models import Analise, EmailRecebido, ItemEmail, Licitacao, LicitacaoExcluida, Oportunidade
from . import gmail
from .dedupe import _normalizar as _norm
from .dedupe import objetos_equivalentes
from .emails_parser import (
    html_para_linhas,
    identificar_boletim,
    normalizar_numero,
    parse_boletim,
    texto_para_linhas,
)
from .pipeline import obter_perfil, perfil_como_dict

logger = logging.getLogger(__name__)

FONTE_EMAIL = "email_dario"

ROTULO_SITUACAO = {
    "novo": "novo",
    "ja_na_base": "já na base",
    "importada": "importada para o pipeline",
    "fora_do_perfil": "fora do perfil",
    "aguardando_ia": "aguardando IA",
    "repetido": "repetido",
    "ignorado": "ignorado",
}

ROTULO_FONTE = {
    "pncp": "PNCP", "fiesc": "FIESC", "fiergs": "FIERGS", "fiems": "FIEMS",
    "manual": "cadastro manual", "conlicitacao": "ConLicitação", "bll": "BLL",
    FONTE_EMAIL: "e-mail do Dario",
}

# Última sincronização com o Gmail (memória do processo — 1 instância no Render free)
_ultima_sync: dict = {"em": None, "resultado": None, "erro": ""}


# ---------------------------------------------------------------------------
# Entrada: um e-mail -> itens
# ---------------------------------------------------------------------------

def processar_boletim(
    db: Session, *, gmail_id: str, assunto: str, remetente: str,
    recebido_em: datetime | None, html: str | None = None, texto: str | None = None,
    origem: str = "gmail",
) -> EmailRecebido | None:
    """Grava o e-mail e seus itens e roda as etapas sem IA. None se já processado."""
    ja = db.execute(select(EmailRecebido).where(EmailRecebido.gmail_id == gmail_id)).scalar_one_or_none()
    if ja is not None:
        return None

    linhas = html_para_linhas(html) if html else texto_para_linhas(texto or "")
    tipo = identificar_boletim(assunto, linhas)
    itens = parse_boletim(tipo, linhas)
    erro = ""
    if tipo == "desconhecido":
        erro = ("Formato de boletim não reconhecido — esperado 'Divulgador de editais' (BLL) "
                "ou 'Alerta de Licitações' (Portal de Compras Públicas).")
    elif not itens:
        erro = "Nenhuma licitação encontrada no corpo do e-mail."

    email = EmailRecebido(
        gmail_id=gmail_id[:120], assunto=(assunto or "").strip(), remetente=(remetente or "").strip(),
        recebido_em=recebido_em, tipo=tipo, origem=origem, total_itens=len(itens), erro=erro,
    )
    db.add(email)
    db.flush()
    for ordem, it in enumerate(itens):
        db.add(ItemEmail(
            email_id=email.id, ordem=ordem, chave=it.chave[:200], portal=it.portal[:60],
            orgao=it.orgao, municipio=it.municipio, uf=(it.uf or "")[:2], modalidade=it.modalidade,
            numero_certame=it.numero_certame, objeto=it.objeto,
            data_abertura=it.data_abertura[:30], data_encerramento=it.data_encerramento[:30],
            link=it.link, situacao="novo",
        ))
    db.commit()
    db.refresh(email)
    classificar_sem_ia(db, list(email.itens))
    return email


def gmail_id_colado(conteudo: str) -> str:
    return "colado-" + hashlib.sha1((conteudo or "").strip().encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Etapas sem IA
# ---------------------------------------------------------------------------

def classificar_sem_ia(db: Session, itens: list[ItemEmail]) -> None:
    perfil = obter_perfil(db)
    ufs = {u.strip().upper() for u in (perfil.ufs or []) if u}
    for item in itens:
        if item.situacao != "novo":
            continue
        anterior = db.execute(
            select(ItemEmail).where(
                ItemEmail.chave == item.chave, ItemEmail.id != item.id,
                ItemEmail.situacao != "repetido",
            ).order_by(ItemEmail.id)
        ).scalars().first()
        if anterior is not None:
            quando = anterior.email.recebido_em.strftime("%d/%m") if anterior.email and anterior.email.recebido_em else "anterior"
            _decidir(
                item, "repetido", licitacao_id=anterior.licitacao_id, aderente=anterior.aderente,
                score=anterior.score_ia,
                motivo=f"Mesma licitação do e-mail de {quando} — {ROTULO_SITUACAO.get(anterior.situacao, anterior.situacao)}"
                       + (f": {anterior.motivo}" if anterior.motivo else ""),
            )
            continue
        lapide = db.execute(
            select(LicitacaoExcluida).where(
                LicitacaoExcluida.fonte == FONTE_EMAIL, LicitacaoExcluida.id_externo == item.chave[:120],
            )
        ).scalar_one_or_none()
        if lapide is not None:
            _decidir(item, "ignorado", aderente=False,
                     motivo=f"Excluída do pipeline por {lapide.excluido_por or 'alguém do time'} — não reimportar sozinho")
            continue
        lic = localizar_na_base(db, item)
        if lic is not None:
            _decidir(item, "ja_na_base", licitacao_id=lic.id,
                     motivo=f"Já coletada via {ROTULO_FONTE.get(lic.fonte, lic.fonte)} (licitação #{lic.id})")
            continue
        if ufs and item.uf and item.uf.upper() not in ufs:
            _decidir(item, "fora_do_perfil", aderente=False, score=0,
                     motivo=f"UF {item.uf} fora das UFs de atuação do perfil ({', '.join(sorted(ufs))})")
    db.commit()


def _decidir(item: ItemEmail, situacao: str, *, licitacao_id: int | None = None,
             aderente: bool | None = None, score: int | None = None, motivo: str = "") -> None:
    item.situacao = situacao
    item.licitacao_id = licitacao_id
    item.aderente = aderente
    item.score_ia = score
    item.motivo = (motivo or "")[:2000]
    item.decidido_em = datetime.utcnow()


def _propagar_repetidos(db: Session, item: ItemEmail) -> None:
    """Repetidos da mesma chave herdam a decisão nova (ex.: IA decidiu depois)."""
    for rep in db.execute(
        select(ItemEmail).where(ItemEmail.chave == item.chave, ItemEmail.situacao == "repetido")
    ).scalars():
        rep.licitacao_id = item.licitacao_id
        rep.aderente = item.aderente
        rep.score_ia = item.score_ia
        rep.motivo = f"Repetido — {ROTULO_SITUACAO.get(item.situacao, item.situacao)}: {item.motivo}"[:2000]


# ---------------------------------------------------------------------------
# Casamento com a base pública
# ---------------------------------------------------------------------------

_RE_NUM_ANO = re.compile(r"(\d{1,6})\s*/\s*(20\d{2})")
_PALAVRAS_ORGAO = {"prefeitura", "municipal", "municipio", "de", "do", "da", "dos", "das", "mun", "pm", "o", "a"}


def _numero_ano_de(obj) -> tuple[int, str] | None:
    numero = getattr(obj, "numero_certame", "") or ""
    m = _RE_NUM_ANO.search(normalizar_numero(numero)) if numero else None
    if m:
        return int(m.group(1)), m.group(2)
    raw = getattr(obj, "raw_json", None) or getattr(obj, "raw", None) or {}
    if isinstance(raw, dict) and raw.get("numeroCompra") and raw.get("anoCompra"):
        try:
            return int(str(raw["numeroCompra"]).strip()), str(raw["anoCompra"]).strip()
        except ValueError:
            pass
    if getattr(obj, "fonte", "") == "manual":
        m = _RE_NUM_ANO.search(getattr(obj, "id_externo", "") or "")
        if m:
            return int(m.group(1)), m.group(2)
    m = re.search(r"n[ºo°.]?\s*(\d{1,6})\s*/\s*(20\d{2})", getattr(obj, "objeto", "") or "", re.I)
    if m:
        return int(m.group(1)), m.group(2)
    return None


def _limpar_orgao(texto: str) -> str:
    tokens = [t for t in re.split(r"[^a-z0-9]+", _norm(texto)) if t and t not in _PALAVRAS_ORGAO]
    return " ".join(tokens)


def _mesmo_municipio(a, b) -> bool:
    na, nb = _norm(getattr(a, "municipio", "")), _norm(getattr(b, "municipio", ""))
    if na and nb:
        return na == nb
    # um dos lados sem município: procura o nome do outro no órgão
    nome = na or nb
    orgao = _norm(getattr(b if na else a, "orgao", ""))
    return bool(nome) and len(nome) >= 4 and nome in orgao


def _mesmo_orgao(a, b) -> bool:
    oa, ob = _limpar_orgao(getattr(a, "orgao", "")), _limpar_orgao(getattr(b, "orgao", ""))
    if not oa or not ob:
        return False
    if oa == ob or oa in ob or ob in oa:
        return True
    return SequenceMatcher(None, oa, ob).ratio() >= 0.85


def _urls(obj) -> set[str]:
    saida = set()
    for campo in ("link", "endereco_licitacao"):
        u = (getattr(obj, campo, "") or "").strip().rstrip("/").lower()
        if u and "pncp.gov.br" not in u:  # página do PNCP é da coleta, não identifica o portal
            saida.add(u)
    return saida


def _sem_reticencias(texto: str) -> str:
    return re.sub(r"(\.\.\.|…)\s*$", "", (texto or "").strip())


def corresponde(lic, item) -> bool:
    """A licitação `lic` (da base) e o `item` (do e-mail OU da coleta) são o mesmo certame?

    Regras, da mais forte para a mais fraca:
    1. mesmo endereço no portal de disputa;
    2. mesmo município/órgão + mesmo número/ano do certame;
    3. mesmo município/órgão + objetos equivalentes (o objeto do boletim pode vir
       truncado com "..." — a comparação aceita prefixo).
    """
    if _urls(lic) & _urls(item):
        return True
    uf_a, uf_b = (getattr(lic, "uf", "") or "").upper(), (getattr(item, "uf", "") or "").upper()
    if uf_a and uf_b and uf_a != uf_b:
        return False
    if not (_mesmo_municipio(lic, item) or _mesmo_orgao(lic, item)):
        return False
    na, nb = _numero_ano_de(lic), _numero_ano_de(item)
    if na and nb and na == nb:
        return True
    return objetos_equivalentes(getattr(lic, "objeto", ""), _sem_reticencias(getattr(item, "objeto", "")))


def localizar_na_base(db: Session, item, fonte: str | None = None) -> Licitacao | None:
    """Licitação já gravada que corresponde ao item do boletim (ou None)."""
    q = select(Licitacao)
    uf = (getattr(item, "uf", "") or "").upper()
    if uf:
        q = q.where((Licitacao.uf == uf) | (Licitacao.uf == ""))
    if fonte:
        q = q.where(Licitacao.fonte == fonte)
    for lic in db.execute(q.order_by(Licitacao.id)).scalars():
        if corresponde(lic, item):
            return lic
    return None


def licitacao_email_correspondente(db: Session, coletada) -> Licitacao | None:
    """Usada pela COLETA: a licitação coletada (PNCP etc.) já existe como card de e-mail?"""
    return localizar_na_base(db, coletada, fonte=FONTE_EMAIL)


def enriquecer_com_coleta(db: Session, lic: Licitacao, c) -> None:
    """A licitação do e-mail apareceu na fonte pública: completa o card com o que a
    fonte traz (edital, valor, datas, razão social) em vez de inserir duplicata.
    Com edital disponível pela primeira vez, volta a 'pendente' para ser analisada
    com o documento de verdade (a análise anterior era só pelo link do portal)."""
    primeira_vez_com_edital = bool(c.edital_url) and not lic.edital_url
    if c.edital_url:
        lic.edital_url = c.edital_url
    if c.link:
        lic.link = c.link
    if c.endereco_licitacao and not lic.endereco_licitacao:
        lic.endereco_licitacao = c.endereco_licitacao
    if c.sistema and not lic.sistema:
        lic.sistema = c.sistema
    if lic.valor_estimado is None and c.valor_estimado is not None:
        lic.valor_estimado = c.valor_estimado
    if c.data_abertura:
        lic.data_abertura = c.data_abertura[:30]
    if c.data_encerramento:
        lic.data_encerramento = c.data_encerramento[:30]
    if c.orgao:
        lic.orgao = c.orgao[:300]
    if c.municipio and not lic.municipio:
        lic.municipio = c.municipio[:120]
    if c.modalidade and not lic.modalidade:
        lic.modalidade = c.modalidade[:80]
    raw = dict(lic.raw_json or {})
    raw["fonte_publica"] = c.fonte
    raw["fonte_publica_id_externo"] = c.id_externo
    raw["registro_fonte_publica"] = c.raw
    lic.raw_json = raw
    if primeira_vez_com_edital:
        for antiga in db.execute(select(Analise).where(Analise.licitacao_id == lic.id)).scalars():
            db.delete(antiga)
        lic.status_analise = "pendente"
    for item in db.execute(
        select(ItemEmail).where(ItemEmail.licitacao_id == lic.id, ItemEmail.situacao == "importada")
    ).scalars():
        marca = f"Localizada depois na coleta ({ROTULO_FONTE.get(c.fonte, c.fonte)} {c.id_externo})."
        if marca not in (item.motivo or ""):
            item.motivo = f"{item.motivo} | {marca}".strip(" |")[:2000]
    logger.info("Licitação do e-mail #%s enriquecida com %s %s", lic.id, c.fonte, c.id_externo)


# ---------------------------------------------------------------------------
# Triagem por IA + importação
# ---------------------------------------------------------------------------

def _item_para_ia(item: ItemEmail) -> dict:
    return {
        "portal": item.portal, "orgao": item.orgao, "municipio": item.municipio, "uf": item.uf,
        "modalidade": item.modalidade, "numero_certame": item.numero_certame,
        "data_encerramento": item.data_encerramento, "objeto": item.objeto,
    }


def triar_pendentes(db: Session, limite: int = 40) -> dict:
    """Decide por IA os itens 'novo'/'aguardando_ia' (um lote, uma chamada)."""
    pendentes = db.execute(
        select(ItemEmail).where(ItemEmail.situacao.in_(["novo", "aguardando_ia"]))
        .order_by(ItemEmail.id).limit(limite)
    ).scalars().all()
    resultado = {"triados": 0, "importadas": 0, "fora_do_perfil": 0, "aguardando_ia": 0}
    if not pendentes:
        return resultado

    def _adiar(motivo: str) -> dict:
        for item in pendentes:
            item.situacao = "aguardando_ia"
            item.motivo = motivo[:2000]
        db.commit()
        resultado["aguardando_ia"] = len(pendentes)
        resultado["aviso"] = motivo
        return resultado

    if not provedor_ativo():
        return _adiar("IA não configurada (GEMINI_API_KEY/ANTHROPIC_API_KEY) — triagem adiada")
    perfil_dict = perfil_como_dict(obter_perfil(db))
    try:
        vereditos = criar_analisador().triar_emails([_item_para_ia(i) for i in pendentes], perfil_dict)
    except ErroCotaIA as exc:
        logger.warning("Triagem de e-mails adiada por cota de IA: %s", exc)
        return _adiar(f"IA sem cota no momento ({exc}) — triagem adiada para a próxima sincronização")
    except Exception as exc:
        logger.exception("Triagem de e-mails falhou")
        return _adiar(f"IA indisponível ({type(exc).__name__}: {exc}) — triagem adiada")

    por_indice = {v.indice: v for v in vereditos}
    for i, item in enumerate(pendentes):
        v = por_indice.get(i)
        if v is None:
            item.situacao = "aguardando_ia"
            item.motivo = "A IA não devolveu veredito para este item — tenta de novo na próxima sincronização"
            resultado["aguardando_ia"] += 1
            continue
        score = max(0, min(10, int(v.score)))
        if v.aderente:
            importar_item(db, item, motivo=v.motivo, score=score)
            resultado["importadas"] += 1
        else:
            _decidir(item, "fora_do_perfil", aderente=False, score=score, motivo=v.motivo)
            _propagar_repetidos(db, item)
            resultado["fora_do_perfil"] += 1
        resultado["triados"] += 1
    db.commit()
    return resultado


def importar_item(db: Session, item: ItemEmail, *, motivo: str = "", score: int | None = None,
                  forcado: bool = False, por: str = "") -> Licitacao:
    """Cria a Licitacao (fonte email_dario) + card 'identificada' a partir do item.

    status_analise 'pendente': o pipeline analisa o edital no próximo ciclo pelo
    link do portal (regra de fonte da análise) — ou pelo PDF, se a coleta do PNCP
    encontrar a mesma licitação depois (enriquecer_com_coleta).
    """
    id_externo = item.chave[:120]
    lic = db.execute(
        select(Licitacao).where(Licitacao.fonte == FONTE_EMAIL, Licitacao.id_externo == id_externo)
    ).scalar_one_or_none()
    if forcado:
        for lapide in db.execute(
            select(LicitacaoExcluida).where(
                LicitacaoExcluida.fonte == FONTE_EMAIL, LicitacaoExcluida.id_externo == id_externo,
            )
        ).scalars():
            db.delete(lapide)
    if lic is None:
        recebido = item.email.recebido_em.strftime("%d/%m/%Y") if item.email and item.email.recebido_em else ""
        notas = f"Origem: e-mail do Dario ({recebido}) — boletim {item.portal}."
        if motivo:
            notas += f" Triagem: {motivo}"
        lic = Licitacao(
            fonte=FONTE_EMAIL, id_externo=id_externo,
            orgao=(item.orgao or "")[:300], municipio=(item.municipio or "")[:120],
            uf=(item.uf or "")[:2], modalidade=(item.modalidade or "")[:80], objeto=item.objeto or "",
            data_abertura=(item.data_abertura or "")[:30], data_encerramento=(item.data_encerramento or "")[:30],
            link=item.link or "", edital_url="", sistema=item.portal or "",
            endereco_licitacao=item.link or "", status_analise="pendente",
            raw_json={
                "origem": FONTE_EMAIL, "email_id": item.email_id, "item_email_id": item.id,
                "portal": item.portal, "numero_certame": item.numero_certame,
                "triagem_motivo": motivo, "triagem_score": score, "importacao_forcada": forcado,
                "importado_por": por,
            },
        )
        db.add(lic)
        db.flush()
        db.add(Oportunidade(licitacao_id=lic.id, estagio="identificada", notas=notas))
    elif lic.oportunidade is None:
        db.add(Oportunidade(licitacao_id=lic.id, estagio="identificada",
                            notas="Origem: e-mail do Dario (reimportada)."))
    _decidir(item, "importada", licitacao_id=lic.id, aderente=True, score=score,
             motivo=motivo or (f"Importada manualmente por {por}" if forcado else ""))
    _propagar_repetidos(db, item)
    db.commit()
    return lic


# ---------------------------------------------------------------------------
# Sincronização com o Gmail
# ---------------------------------------------------------------------------

def sincronizar_gmail(db: Session, dias: int | None = None, maximo: int = 60) -> dict:
    """Lê os boletins novos da caixa, processa e tria. Levanta GmailIndisponivel."""
    if not gmail.configurado():
        raise gmail.GmailIndisponivel(
            "Gmail não conectado — configure GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET e "
            "GMAIL_REFRESH_TOKEN (scripts/autorizar_gmail.py) ou use 'Colar e-mail'."
        )
    try:
        ids = gmail.listar_ids(gmail.consulta_padrao(dias=dias), maximo=maximo)
        conhecidos = set(
            db.execute(select(EmailRecebido.gmail_id).where(EmailRecebido.gmail_id.in_(ids))).scalars()
        ) if ids else set()
        novos, itens_novos = 0, 0
        for mid in reversed(ids):  # do mais antigo para o mais novo: "repetido" aponta para a 1ª vez
            if mid in conhecidos:
                continue
            msg = gmail.obter_mensagem(mid)
            email = processar_boletim(
                db, gmail_id=mid, assunto=msg["assunto"], remetente=msg["remetente"],
                recebido_em=msg["recebido_em"], html=msg["html"], texto=msg["texto"], origem="gmail",
            )
            if email is not None:
                novos += 1
                itens_novos += email.total_itens
    except gmail.GmailIndisponivel as exc:
        _ultima_sync.update(em=datetime.utcnow(), erro=str(exc))
        raise
    triagem = triar_pendentes(db)
    resultado = {"emails_na_caixa": len(ids), "emails_novos": novos, "itens_novos": itens_novos, **triagem}
    _ultima_sync.update(em=datetime.utcnow(), resultado=resultado, erro="")
    return resultado


def resumo_status(db: Session) -> dict:
    from sqlalchemy import func

    por_situacao = dict(
        db.execute(select(ItemEmail.situacao, func.count(ItemEmail.id)).group_by(ItemEmail.situacao)).all()
    )
    total_emails = db.execute(select(func.count(EmailRecebido.id))).scalar() or 0
    ultimo = db.execute(select(func.max(EmailRecebido.recebido_em))).scalar()
    return {
        "gmail_configurado": gmail.configurado(),
        "remetente": gmail.settings.emails_remetente,
        "janela_dias": gmail.settings.emails_janela_dias,
        "ia_configurada": bool(provedor_ativo()),
        "total_emails": total_emails,
        "ultimo_email_em": ultimo.isoformat() + "Z" if ultimo else None,
        "por_situacao": por_situacao,
        "ultima_sincronizacao": _ultima_sync["em"].isoformat() + "Z" if _ultima_sync["em"] else None,
        "ultima_sincronizacao_resultado": _ultima_sync["resultado"],
        "ultima_sincronizacao_erro": _ultima_sync["erro"],
    }
