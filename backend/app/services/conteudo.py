"""Download de conteúdo de links de licitação (página do portal ou PDF direto).

Usado pelo preenchimento automático do Cadastro Manual (routes) e pelo fallback
de fonte da análise no pipeline — regra do produto: TEM documento? analisa o PDF;
NÃO tem? considera o conteúdo do link do certame.
"""
import html as html_lib
import logging
import re

import httpx

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 19 * 1024 * 1024  # limite inline do provedor de IA (Gemini)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def baixar_conteudo(url: str) -> tuple[str | None, bytes | None]:
    """Baixa o link. Retorna (texto_da_pagina, pdf_bytes) — no máximo um dos dois."""
    try:
        with httpx.Client(timeout=45, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("Falha ao baixar link %s: %s", url, exc)
        return None, None

    if resp.content[:5].startswith(b"%PDF"):
        return None, resp.content if len(resp.content) <= MAX_PDF_BYTES else None
    return html_para_texto(resp.text), None


def html_para_texto(html: str) -> str | None:
    """Reduz HTML a texto puro (sem scripts/estilos) para consumo pela IA."""
    sem_blocos = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    texto = re.sub(r"(?s)<[^>]+>", " ", sem_blocos)
    texto = html_lib.unescape(texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:80000] or None
