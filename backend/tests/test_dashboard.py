"""Teste funcional do dashboard executivo (GET /api/dashboard).

Rodar de dentro de backend/:  .venv\\Scripts\\python.exe tests\\test_dashboard.py
(também funciona com pytest, se instalado)
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import security
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import Analise, Licitacao, Oportunidade

# ---------- banco em memória próprio deste teste ----------
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


ADMIN_EMAIL = "admin-dash@teste.com"
ADMIN_SENHA = "senha-inicial"


def _seed(db):
    """3 licitações: 1 em disputa (vence em 5 dias), 1 ganha e 1 perdida."""
    l1 = Licitacao(
        fonte="pncp", id_externo="dash-1", orgao="Prefeitura A", municipio="Chapecó",
        uf="SC", objeto="Vale alimentação", valor_estimado=100000.0,
        data_encerramento=(date.today() + timedelta(days=5)).isoformat(),
    )
    l2 = Licitacao(fonte="manual", id_externo="dash-2", orgao="Prefeitura B",
                   uf="PR", objeto="Vale refeição", valor_estimado=50000.0)
    l3 = Licitacao(fonte="pncp", id_externo="dash-3", orgao="Prefeitura C",
                   uf="SC", objeto="Cartão benefício", valor_estimado=20000.0)
    db.add_all([l1, l2, l3])
    db.commit()
    db.add(Analise(licitacao_id=l1.id, veredito="participar",
                   classificacao_final="BOA OPORTUNIDADE"))
    db.add_all([
        Oportunidade(licitacao_id=l1.id, estagio="disputa"),
        Oportunidade(licitacao_id=l2.id, estagio="ganhou"),
        Oportunidade(licitacao_id=l3.id, estagio="perdeu_nogo"),
    ])
    db.commit()


def test_dashboard():
    # Override do banco só durante este teste (não pisar no override do test_auth)
    override_anterior = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db_teste
    try:
        settings.admin_email = ADMIN_EMAIL
        settings.admin_senha_inicial = ADMIN_SENHA
        db = TestingSession()
        security.bootstrap_admin(db)
        _seed(db)
        db.close()

        cliente = TestClient(app)

        # --- sem sessão -> 401 ---
        assert cliente.get("/api/dashboard").status_code == 401

        # --- admin logado: payload completo ---
        r = cliente.post("/api/auth/login", json={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})
        assert r.status_code == 200
        r = cliente.get("/api/dashboard?dias=30")
        assert r.status_code == 200
        d = r.json()

        ind = d["indicadores"]
        assert ind["licitacoes_coletadas"] == 3
        assert ind["oportunidades_novas"] == 3
        assert ind["valor_em_disputa"] == 100000.0
        assert ind["valor_ganho"] == 50000.0 and ind["ganhas"] == 1
        assert ind["valor_perdido"] == 20000.0 and ind["perdidas"] == 1
        assert ind["taxa_vitoria"] == 50.0

        # Funil na ordem do kanban, com contagem e valor
        assert [f["estagio"] for f in d["funil"]] == Oportunidade.ESTAGIOS
        funil = {f["estagio"]: f for f in d["funil"]}
        assert funil["disputa"] == {"estagio": "disputa", "quantidade": 1, "valor": 100000.0}
        assert funil["ganhou"]["quantidade"] == 1 and funil["perdeu_nogo"]["quantidade"] == 1

        # Distribuições
        assert d["por_uf"][0] == {"uf": "SC", "quantidade": 2}
        assert {f["fonte"]: f["quantidade"] for f in d["por_fonte"]} == {"pncp": 2, "manual": 1}
        classifs = {c["classificacao"]: c["quantidade"] for c in d["classificacoes"]}
        assert classifs["BOA OPORTUNIDADE"] == 1
        assert classifs["SEM ANÁLISE"] == 2

        # Vencimentos próximos: só a oportunidade ativa que vence em 5 dias
        assert len(d["vencimentos_proximos"]) == 1
        venc = d["vencimentos_proximos"][0]
        assert venc["orgao"] == "Prefeitura A"
        assert venc["dias_restantes"] == 5 and venc["estagio"] == "disputa"

        # Série contínua (30 pontos, dias sem coleta com zero)
        assert len(d["coletas_por_dia"]) == 30
        assert sum(p["quantidade"] for p in d["coletas_por_dia"]) == 3

        # Admin recebe o bloco de atividade; `dias` é clampado para >= 1
        assert "atividade" in d
        assert any(u["email"] == ADMIN_EMAIL for u in d["atividade"]["usuarios"])
        assert cliente.get("/api/dashboard?dias=0").json()["dias"] == 1

        # --- não-admin: mesmo payload, SEM o bloco de atividade ---
        r = cliente.post("/api/usuarios", json={
            "nome": "Funcionário", "email": "func-dash@teste.com", "senha": "func-123",
        })
        assert r.status_code == 201
        func = TestClient(app)
        assert func.post("/api/auth/login", json={
            "email": "func-dash@teste.com", "senha": "func-123"}).status_code == 200
        d2 = func.get("/api/dashboard?dias=30").json()
        assert "atividade" not in d2
        assert d2["indicadores"]["licitacoes_coletadas"] == 3

        print("OK — dashboard executivo respondeu com todos os blocos esperados.")
    finally:
        if override_anterior is not None:
            app.dependency_overrides[get_db] = override_anterior
        else:
            app.dependency_overrides.pop(get_db, None)


if __name__ == "__main__":
    test_dashboard()
