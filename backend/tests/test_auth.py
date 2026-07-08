"""Teste funcional da autenticação (banco SQLite em memória, TestClient).

Rodar de dentro de backend/:  .venv\\Scripts\\python.exe tests\\test_auth.py
(também funciona com pytest, se instalado)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import security
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import Usuario

# ---------- banco em memória ----------
engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base.metadata.create_all(engine)


def _get_db_teste():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _get_db_teste

ADMIN_EMAIL = "admin@teste.com"
ADMIN_SENHA = "senha-inicial"


def _login(client: TestClient, email: str, senha: str):
    return client.post("/api/auth/login", json={"email": email, "senha": senha})


def test_fluxo_completo():
    # --- bootstrap do admin (idempotente) ---
    settings.admin_email = ADMIN_EMAIL
    settings.admin_senha_inicial = ADMIN_SENHA
    db = TestingSession()
    criado = security.bootstrap_admin(db)
    assert criado is not None and criado.is_admin and criado.email == ADMIN_EMAIL
    assert security.bootstrap_admin(db) is None, "bootstrap deve ser idempotente"
    assert db.query(Usuario).count() == 1
    db.close()

    admin = TestClient(app)  # sem `with`: lifespan não roda (não toca o banco real)

    # --- rota protegida sem sessão -> 401 ---
    assert admin.get("/api/licitacoes").status_code == 401
    assert admin.get("/api/auth/me").status_code == 401

    # --- login errado -> 401 genérico (senha errada e email inexistente iguais) ---
    r = _login(admin, ADMIN_EMAIL, "senha-errada")
    assert r.status_code == 401 and r.json()["detail"] == "Credenciais inválidas"
    r = _login(admin, "naoexiste@teste.com", "qualquer")
    assert r.status_code == 401 and r.json()["detail"] == "Credenciais inválidas"

    # --- login ok -> cookie HttpOnly + dados do usuário ---
    r = _login(admin, ADMIN_EMAIL, ADMIN_SENHA)
    assert r.status_code == 200
    assert r.json() == {"nome": "Administrador", "email": ADMIN_EMAIL, "is_admin": True}
    set_cookie = r.headers["set-cookie"].lower()
    assert "sessao=" in set_cookie and "httponly" in set_cookie and "samesite=lax" in set_cookie

    # --- com sessão: me e rota protegida -> 200 ---
    r = admin.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["email"] == ADMIN_EMAIL
    assert admin.get("/api/licitacoes").status_code == 200

    # --- trocar senha (atual errada -> 400; ok -> senha antiga deixa de valer) ---
    r = admin.post("/api/auth/trocar-senha",
                   json={"senha_atual": "errada", "senha_nova": "nova-senha-123"})
    assert r.status_code == 400
    r = admin.post("/api/auth/trocar-senha",
                   json={"senha_atual": ADMIN_SENHA, "senha_nova": "nova-senha-123"})
    assert r.status_code == 200
    assert admin.get("/api/auth/me").status_code == 200, "sessão atual continua válida"
    outro = TestClient(app)
    assert _login(outro, ADMIN_EMAIL, ADMIN_SENHA).status_code == 401, "senha antiga não vale"
    assert _login(outro, ADMIN_EMAIL, "nova-senha-123").status_code == 200

    # --- criar usuário não-admin ---
    r = admin.post("/api/usuarios", json={
        "nome": "Funcionário", "email": "func@teste.com", "senha": "func-123", "is_admin": False,
    })
    assert r.status_code == 201 and r.json()["is_admin"] is False
    func_id = r.json()["id"]
    # email duplicado -> 409; senha curta -> 400
    assert admin.post("/api/usuarios", json={
        "nome": "X", "email": "func@teste.com", "senha": "func-123"}).status_code == 409
    assert admin.post("/api/usuarios", json={
        "nome": "X", "email": "y@teste.com", "senha": "123"}).status_code == 400

    # --- não-admin loga, usa o app, mas não administra usuários ---
    func = TestClient(app)
    r = _login(func, "func@teste.com", "func-123")
    assert r.status_code == 200 and r.json()["is_admin"] is False
    assert func.get("/api/licitacoes").status_code == 200
    assert func.get("/api/usuarios").status_code == 403
    assert func.post("/api/usuarios", json={
        "nome": "Z", "email": "z@t.com", "senha": "zzzzzz"}).status_code == 403

    # --- admin não pode desativar a si mesmo ---
    admin_id = next(u["id"] for u in admin.get("/api/usuarios").json()
                    if u["email"] == ADMIN_EMAIL)
    r = admin.patch(f"/api/usuarios/{admin_id}", json={"ativo": False})
    assert r.status_code == 400

    # --- desativar usuário: sessão existente cai e login passa a falhar ---
    r = admin.patch(f"/api/usuarios/{func_id}", json={"ativo": False})
    assert r.status_code == 200 and r.json()["ativo"] is False
    assert func.get("/api/licitacoes").status_code == 401, "sessão do desativado é revogada"
    assert _login(TestClient(app), "func@teste.com", "func-123").status_code == 401

    # --- reativar + resetar senha pelo admin ---
    r = admin.patch(f"/api/usuarios/{func_id}", json={"ativo": True, "senha": "senha-nova-func"})
    assert r.status_code == 200
    assert _login(TestClient(app), "func@teste.com", "func-123").status_code == 401
    assert _login(TestClient(app), "func@teste.com", "senha-nova-func").status_code == 200

    # --- logout invalida a sessão ---
    assert admin.post("/api/auth/logout").status_code == 200
    assert admin.get("/api/auth/me").status_code == 401
    assert admin.get("/api/licitacoes").status_code == 401

    print("OK — todos os cenários de autenticação passaram.")


if __name__ == "__main__":
    test_fluxo_completo()
