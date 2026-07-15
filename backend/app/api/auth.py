"""Rotas de autenticação e administração de usuários."""
import time
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Usuario
from ..security import (
    _HASH_FALSO,
    criar_sessao,
    definir_cookie_sessao,
    exigir_admin,
    hash_senha,
    limpar_cookie_sessao,
    remover_outras_sessoes,
    remover_sessao,
    usuario_atual,
    verificar_senha,
)
from ..services.atividade import registrar_evento

router = APIRouter(prefix="/api")

SENHA_MIN = 6


def _usuario_out(u: Usuario) -> dict:
    return {
        "id": u.id, "nome": u.nome, "email": u.email,
        "is_admin": u.is_admin, "ativo": u.ativo,
        "criado_em": u.criado_em.isoformat(),
    }


# ---------- Autenticação ----------

class LoginIn(BaseModel):
    email: str
    senha: str


@router.post("/auth/login")
def login(dados: LoginIn, response: Response, db: Session = Depends(get_db)):
    usuario = db.execute(
        select(Usuario).where(Usuario.email == dados.email.strip().lower())
    ).scalar_one_or_none()
    # Sempre roda bcrypt (hash falso se o email não existe): tempo de resposta
    # constante — não dá para descobrir quais emails têm conta.
    senha_ok = verificar_senha(dados.senha, usuario.senha_hash if usuario else _HASH_FALSO)
    if not usuario or not usuario.ativo or not senha_ok:
        time.sleep(0.5)  # freio simples contra força bruta
        raise HTTPException(401, "Credenciais inválidas")
    token = criar_sessao(db, usuario)
    definir_cookie_sessao(response, token)
    # ultimo_acesso é persistido junto com o commit de registrar_evento
    usuario.ultimo_acesso = datetime.utcnow()
    registrar_evento(db, usuario, "login")
    return {"nome": usuario.nome, "email": usuario.email, "is_admin": usuario.is_admin}


@router.post("/auth/logout")
def logout(
    response: Response,
    sessao: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if sessao:
        remover_sessao(db, sessao)
    limpar_cookie_sessao(response)
    return {"ok": True}


@router.get("/auth/me")
def me(usuario: Usuario = Depends(usuario_atual)):
    return {"nome": usuario.nome, "email": usuario.email, "is_admin": usuario.is_admin}


class TrocarSenhaIn(BaseModel):
    senha_atual: str
    senha_nova: str


@router.post("/auth/trocar-senha")
def trocar_senha(
    dados: TrocarSenhaIn,
    usuario: Usuario = Depends(usuario_atual),
    sessao: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not verificar_senha(dados.senha_atual, usuario.senha_hash):
        raise HTTPException(400, "Senha atual incorreta")
    if len(dados.senha_nova) < SENHA_MIN:
        raise HTTPException(400, f"A nova senha deve ter pelo menos {SENHA_MIN} caracteres")
    usuario.senha_hash = hash_senha(dados.senha_nova)
    db.commit()
    # revoga as demais sessões do usuário; a atual continua válida
    remover_outras_sessoes(db, usuario.id, token_manter=sessao)
    return {"ok": True}


# ---------- Administração de usuários (só admin) ----------

class UsuarioIn(BaseModel):
    nome: str
    email: str
    senha: str
    is_admin: bool = False


class UsuarioPatch(BaseModel):
    nome: str | None = None
    ativo: bool | None = None
    is_admin: bool | None = None
    senha: str | None = None  # resetar senha


@router.get("/usuarios")
def listar_usuarios(_: Usuario = Depends(exigir_admin), db: Session = Depends(get_db)):
    usuarios = db.execute(select(Usuario).order_by(Usuario.criado_em)).scalars().all()
    return [_usuario_out(u) for u in usuarios]


@router.post("/usuarios", status_code=201)
def criar_usuario(
    dados: UsuarioIn,
    _: Usuario = Depends(exigir_admin),
    db: Session = Depends(get_db),
):
    email = dados.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "Email inválido")
    if len(dados.senha) < SENHA_MIN:
        raise HTTPException(400, f"A senha deve ter pelo menos {SENHA_MIN} caracteres")
    if db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none():
        raise HTTPException(409, "Já existe um usuário com esse email")
    usuario = Usuario(
        nome=dados.nome.strip(),
        email=email,
        senha_hash=hash_senha(dados.senha),
        is_admin=dados.is_admin,
        ativo=True,
    )
    db.add(usuario)
    db.commit()
    return _usuario_out(usuario)


@router.patch("/usuarios/{usuario_id}")
def atualizar_usuario(
    usuario_id: int,
    patch: UsuarioPatch,
    admin: Usuario = Depends(exigir_admin),
    db: Session = Depends(get_db),
):
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(404, "Usuário não encontrado")
    if patch.ativo is False and usuario.id == admin.id:
        raise HTTPException(400, "Você não pode desativar a si mesmo")
    if patch.is_admin is False and usuario.id == admin.id:
        raise HTTPException(400, "Você não pode remover seu próprio acesso de administrador")
    if patch.nome is not None:
        usuario.nome = patch.nome.strip()
    if patch.ativo is not None:
        usuario.ativo = patch.ativo
    if patch.is_admin is not None:
        usuario.is_admin = patch.is_admin
    if patch.senha is not None:
        if len(patch.senha) < SENHA_MIN:
            raise HTTPException(400, f"A senha deve ter pelo menos {SENHA_MIN} caracteres")
        usuario.senha_hash = hash_senha(patch.senha)
    db.commit()
    if patch.ativo is False or patch.senha is not None:
        # derruba as sessões de quem foi desativado ou teve a senha resetada
        remover_outras_sessoes(db, usuario.id, token_manter=None)
    return _usuario_out(usuario)
