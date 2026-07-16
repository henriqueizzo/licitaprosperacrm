"""Deduplicação de licitações espelhadas.

O mesmo pregão pode chegar ao PNCP mais de uma vez quando o órgão publica pelo
sistema próprio E por uma plataforma intermediária (ex.: Portal de Compras
Públicas) — cada publicação ganha um numeroControlePNCP diferente, então o
dedupe por (fonte, id_externo) não pega. A regra aqui é deliberadamente
conservadora: só considera espelho quando o MESMO órgão (CNPJ) tem duas
licitações com o MESMO valor estimado (ao centavo), a MESMA data de
encerramento e objeto equivalente (ignorando o prefixo "[Plataforma] - ").
Pregões parecidos-mas-distintos (ex.: dois kits com valores diferentes do
mesmo órgão) NÃO casam.
"""
import logging
import re
import unicodedata
from difflib import SequenceMatcher

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import Analise, DocumentoAnexo, EventoUso, Licitacao, Oportunidade

logger = logging.getLogger(__name__)

# "[Portal de Compras Públicas] - Contratação..." -> "Contratação..."
_PREFIXO_PLATAFORMA = re.compile(r"^\s*\[[^\]]{2,80}\]\s*[-–—:]?\s*")

_ORDEM_ESTAGIO = {e: i for i, e in enumerate(Oportunidade.ESTAGIOS)}


def _normalizar(texto: str | None) -> str:
    texto = _PREFIXO_PLATAFORMA.sub("", texto or "")
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def _chave_orgao(lic) -> str:
    """CNPJ do órgão (id_externo PNCP = 'CNPJ-1-SEQ/ANO'); senão órgão+município."""
    id_externo = getattr(lic, "id_externo", "") or ""
    if getattr(lic, "fonte", "") == "pncp" and "-" in id_externo:
        cnpj = id_externo.split("-", 1)[0]
        if cnpj.isdigit() and len(cnpj) == 14:
            return cnpj
    return f"{_normalizar(lic.orgao)}|{_normalizar(lic.municipio)}|{(lic.uf or '').upper()}"


def chave_espelho(lic) -> tuple | None:
    """Chave de agrupamento de espelhos; None quando faltam dados para decidir.

    Sem valor estimado ou sem data de encerramento não há como afirmar espelho
    com segurança — nesses casos a licitação nunca é deduplicada.
    """
    valor = getattr(lic, "valor_estimado", None)
    data = (getattr(lic, "data_encerramento", "") or "")[:10]
    if valor is None or not data:
        return None
    return (_chave_orgao(lic), round(valor, 2), data)


def objetos_equivalentes(a: str | None, b: str | None) -> bool:
    na, nb = _normalizar(a), _normalizar(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na[:400], nb[:400]).ratio() >= 0.85


def eh_espelho_de_existente(db: Session, candidata) -> Licitacao | None:
    """Retorna a licitação já gravada da qual `candidata` é espelho, se houver.

    Usada na coleta para nem inserir o espelho. `candidata` é o item do coletor
    (mesmos nomes de atributos de Licitacao — duck typing).
    """
    chave = chave_espelho(candidata)
    if chave is None:
        return None
    existentes = db.execute(
        select(Licitacao).where(Licitacao.valor_estimado == round(candidata.valor_estimado, 2))
    ).scalars().all()
    for lic in existentes:
        if chave_espelho(lic) == chave and objetos_equivalentes(lic.objeto, candidata.objeto):
            return lic
    return None


def _pontuacao_manter(db: Session, lic: Licitacao) -> tuple:
    """Quanto maior, mais 'trabalhada' a licitação — é a que fica no lugar do espelho."""
    op = lic.oportunidade
    estagio = _ORDEM_ESTAGIO.get(op.estagio, 0) if op else -1
    docs = db.execute(
        select(DocumentoAnexo.id).where(DocumentoAnexo.licitacao_id == lic.id)
    ).first() is not None
    mexida = bool(op and (op.responsavel or (op.notas and not op.notas.startswith("Backfill"))))
    tem_analise = lic.analise is not None
    # -lic.id no fim: empate fica com a mais antiga (primeira coletada)
    return (estagio, int(docs), int(mexida), int(tem_analise), -lic.id)


def _foi_trabalhada(db: Session, lic: Licitacao) -> bool:
    """True se um humano já interagiu com a licitação (não é seguro apagar sozinho)."""
    op = lic.oportunidade
    if op and op.estagio != "identificada":
        return True
    if op and (op.responsavel or (op.notas and not op.notas.startswith("Backfill"))):
        return True
    return db.execute(
        select(DocumentoAnexo.id).where(DocumentoAnexo.licitacao_id == lic.id)
    ).first() is not None


def encontrar_grupos(db: Session) -> list[list[Licitacao]]:
    """Agrupa licitações espelhadas: mesma chave + objetos equivalentes."""
    por_chave: dict[tuple, list[Licitacao]] = {}
    for lic in db.execute(select(Licitacao)).scalars():
        chave = chave_espelho(lic)
        if chave is not None:
            por_chave.setdefault(chave, []).append(lic)

    grupos: list[list[Licitacao]] = []
    for candidatas in por_chave.values():
        if len(candidatas) < 2:
            continue
        # Dentro da chave, ainda exige objeto equivalente (subgrupos)
        restantes = list(candidatas)
        while restantes:
            base = restantes.pop(0)
            grupo = [base]
            for outra in list(restantes):
                if objetos_equivalentes(base.objeto, outra.objeto):
                    grupo.append(outra)
                    restantes.remove(outra)
            if len(grupo) > 1:
                grupos.append(grupo)
    return grupos


def apagar_espelhos(db: Session) -> dict:
    """Apaga definitivamente as licitações espelhadas, mantendo a mais trabalhada.

    Segurança: se mais de uma licitação do grupo já foi trabalhada por humano
    (estágio avançado, notas/responsável ou documentos anexados), o grupo é
    pulado e vira aviso — decisão de mesclar fica com o time.
    Idempotente: depois da primeira passada não sobra nada para apagar.
    """
    grupos = encontrar_grupos(db)
    apagadas = 0
    avisos: list[str] = []
    detalhes: list[dict] = []

    for grupo in grupos:
        trabalhadas = [l for l in grupo if _foi_trabalhada(db, l)]
        if len(trabalhadas) > 1:
            ids = ", ".join(f"#{l.id}" for l in grupo)
            avisos.append(
                f"Espelhos NÃO apagados ({ids} — {grupo[0].orgao}): mais de uma já foi "
                "trabalhada (estágio/notas/documentos). Unifiquem manualmente."
            )
            continue

        grupo.sort(key=lambda l: _pontuacao_manter(db, l), reverse=True)
        mantida, espelhos = grupo[0], grupo[1:]
        for esp in espelhos:
            # Auditoria aponta para a licitação que fica (não perde histórico)
            db.execute(
                update(EventoUso).where(EventoUso.licitacao_id == esp.id)
                .values(licitacao_id=mantida.id)
            )
            for analise in db.execute(select(Analise).where(Analise.licitacao_id == esp.id)).scalars():
                db.delete(analise)
            for doc in db.execute(select(DocumentoAnexo).where(DocumentoAnexo.licitacao_id == esp.id)).scalars():
                db.delete(doc)
            if esp.oportunidade:
                db.delete(esp.oportunidade)
            db.delete(esp)
            apagadas += 1
        detalhes.append({
            "mantida": mantida.id,
            "apagadas": [e.id for e in espelhos],
            "orgao": mantida.orgao,
            "municipio": f"{mantida.municipio}/{mantida.uf}",
            "valor": mantida.valor_estimado,
        })

    db.commit()
    if apagadas:
        logger.info("Dedupe: %d licitação(ões) espelhada(s) apagada(s): %s", apagadas, detalhes)
    for aviso in avisos:
        logger.warning("Dedupe: %s", aviso)
    return {"grupos": len(grupos), "apagadas": apagadas, "avisos": avisos, "detalhes": detalhes}
