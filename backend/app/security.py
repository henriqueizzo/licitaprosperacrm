"""Autenticação: senhas bcrypt + sessões opacas em cookie HttpOnly.

O cookie `sessao` carrega um token aleatório (secrets.token_urlsafe); no banco
fica só o SHA-256 do token, na tabela `sessoes` — revogável e sem segredo em claro.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Sessao, Usuario

logger = logging.getLogger(__name__)

COOKIE_SESSAO = "sessao"

# Hash bcrypt de uma senha impossível: usado quando o email não existe, para que
# o tempo de resposta seja o mesmo e não dê para descobrir quais emails têm conta.
_HASH_FALSO = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt()).decode("ascii")


# ---------- Senhas ----------

def hash_senha(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verificar_senha(senha: str, senha_hash: str) -> bool:
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), senha_hash.encode("ascii"))
    except ValueError:
        return False


# ---------- Sessões ----------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def criar_sessao(db: Session, usuario: Usuario) -> str:
    """Cria uma sessão e retorna o token em claro (vai para o cookie)."""
    # higiene: remove sessões já expiradas (de qualquer usuário)
    db.execute(delete(Sessao).where(Sessao.expira_em < datetime.utcnow()))
    token = secrets.token_urlsafe(32)
    db.add(Sessao(
        token_hash=_hash_token(token),
        usuario_id=usuario.id,
        expira_em=datetime.utcnow() + timedelta(days=settings.sessao_dias),
    ))
    db.commit()
    return token


def remover_sessao(db: Session, token: str) -> None:
    db.execute(delete(Sessao).where(Sessao.token_hash == _hash_token(token)))
    db.commit()


def remover_outras_sessoes(db: Session, usuario_id: int, token_manter: str | None) -> None:
    """Revoga as demais sessões do usuário (ex.: após troca/reset de senha)."""
    q = delete(Sessao).where(Sessao.usuario_id == usuario_id)
    if token_manter:
        q = q.where(Sessao.token_hash != _hash_token(token_manter))
    db.execute(q)
    db.commit()


def usuario_da_sessao(db: Session, token: str) -> Usuario | None:
    sessao = db.execute(
        select(Sessao).where(Sessao.token_hash == _hash_token(token))
    ).scalar_one_or_none()
    if not sessao or sessao.expira_em < datetime.utcnow():
        if sessao:  # expirada: remove do banco
            db.delete(sessao)
            db.commit()
        return None
    usuario = db.get(Usuario, sessao.usuario_id)
    if not usuario or not usuario.ativo:
        return None
    return usuario


def definir_cookie_sessao(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_SESSAO,
        value=token,
        max_age=settings.sessao_dias * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def limpar_cookie_sessao(response: Response) -> None:
    response.delete_cookie(key=COOKIE_SESSAO, path="/")


# ---------- Dependencies ----------

def _tocar_ultimo_acesso(db: Session, usuario: Usuario) -> None:
    """Atualiza Usuario.ultimo_acesso no máximo 1x por minuto (evita um UPDATE
    a cada request) e nunca quebra a autenticação em caso de falha de escrita."""
    agora = datetime.utcnow()
    if usuario.ultimo_acesso and (agora - usuario.ultimo_acesso) < timedelta(minutes=1):
        return
    try:
        usuario.ultimo_acesso = agora
        db.commit()
    except Exception:
        logger.warning("Falha ao atualizar ultimo_acesso do usuário %s", usuario.id, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass


def usuario_atual(
    sessao: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Usuario:
    """Exige sessão válida (cookie `sessao`). 401 se ausente/expirada/usuário inativo."""
    if not sessao:
        raise HTTPException(401, "Não autenticado")
    usuario = usuario_da_sessao(db, sessao)
    if not usuario:
        raise HTTPException(401, "Sessão inválida ou expirada")
    _tocar_ultimo_acesso(db, usuario)
    return usuario


def exigir_admin(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
    if not usuario.is_admin:
        raise HTTPException(403, "Acesso restrito a administradores")
    return usuario


# ---------- Bootstrap ----------

def bootstrap_admin(db: Session) -> Usuario | None:
    """Cria o primeiro admin (do .env) se ainda não existir nenhum usuário."""
    if db.execute(select(Usuario.id).limit(1)).first():
        return None
    if not settings.admin_email or not settings.admin_senha_inicial:
        logger.warning(
            "Nenhum usuário cadastrado e ADMIN_EMAIL/ADMIN_SENHA_INICIAL não definidos "
            "no .env — ninguém conseguirá entrar no sistema."
        )
        return None
    admin = Usuario(
        nome="Administrador",
        email=settings.admin_email.strip().lower(),
        senha_hash=hash_senha(settings.admin_senha_inicial),
        is_admin=True,
        ativo=True,
    )
    db.add(admin)
    db.commit()
    logger.warning(
        "Usuário admin inicial criado (%s) com a senha de ADMIN_SENHA_INICIAL do .env. "
        "TROQUE A SENHA no primeiro acesso (menu Trocar senha).",
        admin.email,
    )
    return admin
