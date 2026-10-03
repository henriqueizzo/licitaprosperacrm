"""Leitura da caixa do Gmail pela API oficial (OAuth 2.0, escopo somente leitura).

Sem bibliotecas do Google: o fluxo é dois GETs e um POST com httpx.
- refresh_token -> access_token (POST oauth2.googleapis.com/token). O refresh token
  é obtido UMA vez com backend/scripts/autorizar_gmail.py e vai para as env vars
  GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN.
- GET users/me/messages?q=... lista ids; GET users/me/messages/{id}?format=full traz
  cabeçalhos e corpo (partes MIME em base64url).

Escopo gmail.readonly: o CRM nunca envia, apaga nem marca nada na caixa.
"""
import base64
import logging
import time
from datetime import datetime, timezone

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
ESCOPO = "https://www.googleapis.com/auth/gmail.readonly"
TIMEOUT = 30

_token_cache: dict = {"valor": "", "expira_em": 0.0}


class GmailIndisponivel(Exception):
    """Falha de autenticação/rede com o Gmail — mensagem pronta para a tela."""


def configurado() -> bool:
    return bool(settings.gmail_client_id and settings.gmail_client_secret and settings.gmail_refresh_token)


def consulta_padrao(remetente: str | None = None, dias: int | None = None) -> str:
    """Busca do Gmail: só os dois boletins, só do remetente, só na janela."""
    remetente = remetente or settings.emails_remetente
    dias = dias or settings.emails_janela_dias
    # Entre aspas o Gmail casa palavras INTEIRAS ("Licita" não acha "Licitações")
    return (
        f"from:{remetente} newer_than:{dias}d "
        '(subject:"Divulgador de editais" OR subject:"Alerta de Licitações" OR subject:"Alerta de Licitacoes")'
    )


def _access_token() -> str:
    if _token_cache["valor"] and time.time() < _token_cache["expira_em"] - 60:
        return _token_cache["valor"]
    try:
        resp = httpx.post(TOKEN_URL, data={
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "refresh_token": settings.gmail_refresh_token,
            "grant_type": "refresh_token",
        }, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise GmailIndisponivel(f"Sem conexão com o Google ({type(exc).__name__}).") from exc
    if resp.status_code != 200:
        detalhe = ""
        try:
            detalhe = resp.json().get("error_description") or resp.json().get("error") or ""
        except Exception:
            pass
        raise GmailIndisponivel(
            "O Google recusou as credenciais do Gmail "
            f"({resp.status_code} {detalhe}). Gere um refresh token novo com "
            "scripts/autorizar_gmail.py e atualize GMAIL_REFRESH_TOKEN."
        )
    dados = resp.json()
    _token_cache["valor"] = dados["access_token"]
    _token_cache["expira_em"] = time.time() + int(dados.get("expires_in", 3600))
    return _token_cache["valor"]


def _get(caminho: str, params: dict | None = None) -> dict:
    token = _access_token()
    try:
        resp = httpx.get(
            f"{API_BASE}/{caminho}", params=params,
            headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise GmailIndisponivel(f"Falha de rede com o Gmail ({type(exc).__name__}).") from exc
    if resp.status_code in (401, 403):
        _token_cache["valor"] = ""
        raise GmailIndisponivel(
            f"Gmail negou o acesso ({resp.status_code}). O token pode ter sido revogado — "
            "autorize de novo com scripts/autorizar_gmail.py."
        )
    if resp.status_code >= 400:
        raise GmailIndisponivel(f"Gmail respondeu {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def listar_ids(consulta: str, maximo: int = 100) -> list[str]:
    """Ids das mensagens que casam com a consulta (mais recentes primeiro)."""
    ids: list[str] = []
    params: dict = {"q": consulta, "maxResults": min(maximo, 100)}
    while len(ids) < maximo:
        dados = _get("messages", params)
        ids += [m["id"] for m in dados.get("messages", [])]
        token = dados.get("nextPageToken")
        if not token:
            break
        params["pageToken"] = token
    return ids[:maximo]


def obter_mensagem(msg_id: str) -> dict:
    """{id, assunto, remetente, recebido_em (datetime UTC), html, texto}."""
    dados = _get(f"messages/{msg_id}", {"format": "full"})
    payload = dados.get("payload") or {}
    cabecalhos = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    corpos = {"text/html": "", "text/plain": ""}
    _coletar_corpos(payload, corpos)
    recebido = None
    if dados.get("internalDate"):
        recebido = datetime.fromtimestamp(int(dados["internalDate"]) / 1000, tz=timezone.utc).replace(tzinfo=None)
    return {
        "id": dados.get("id", msg_id),
        "assunto": cabecalhos.get("subject", ""),
        "remetente": cabecalhos.get("from", ""),
        "recebido_em": recebido,
        "html": corpos["text/html"] or None,
        "texto": corpos["text/plain"] or None,
    }


def _coletar_corpos(parte: dict, corpos: dict) -> None:
    mime = (parte.get("mimeType") or "").lower()
    dados = (parte.get("body") or {}).get("data")
    if mime in corpos and dados and not corpos[mime]:
        corpos[mime] = _b64url(dados)
    for sub in parte.get("parts") or []:
        _coletar_corpos(sub, corpos)


def _b64url(dados: str) -> str:
    faltam = (-len(dados)) % 4
    try:
        return base64.urlsafe_b64decode(dados + "=" * faltam).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Corpo do e-mail não decodificou: %s", exc)
        return ""
