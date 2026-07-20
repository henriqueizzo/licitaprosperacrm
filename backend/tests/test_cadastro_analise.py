"""Teste funcional do cadastro manual com análise importada (POST /api/licitacoes).

Fluxo novo: o preenchimento automático pode devolver, além dos campos, a análise
transcrita de um relatório anexado (campo `analise`). O cadastro grava essa
análise como se fosse do pipeline — checklist de Documentação funciona direto.

Rodar de dentro de backend/:  .venv\\Scripts\\python.exe tests\\test_cadastro_analise.py
(também funciona com pytest, se instalado)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import security
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import Analise, Licitacao

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


ADMIN_EMAIL = "admin-cadastro@teste.com"
ADMIN_SENHA = "senha-inicial"

ANALISE_IMPORTADA = {
    "objeto_resumido": "Credenciamento para fornecimento de Vale-Alimentação a 150 servidores.",
    "prazos": [{"descricao": "Data Máx. Credenciamento", "data_ou_prazo": "2026-07-17"}],
    "exigencias_habilitacao": ["Registro no PAT"],
    "exigencias_tecnicas": ["Central de atendimento por telefone"],
    "atestados_exigidos": ["Atestado com no mínimo 50% do efetivo (75 cartões)"],
    "documentos_habilitacao": [
        {"categoria": "HABILITAÇÃO JURÍDICA", "documento": "Contrato social em vigor",
         "referencia_edital": "Item 8.4, a.1, p. 6"},
        {"categoria": "REGULARIDADE FISCAL E TRABALHISTA", "documento": "CND Federal",
         "referencia_edital": "Item 8.4, b.5, p. 7"},
        {"categoria": "OUTROS DOCUMENTOS / DECLARAÇÕES", "documento": "Registro no PAT",
         "referencia_edital": "Item 8.4, b, p. 6"},
    ],
    "riscos": ["Rede credenciada local mínima de 3 estabelecimentos"],
    "score_beneficios": 7,
    "score_pagamentos": 0,
    "classificacao_final": "OPORTUNIDADE MODERADA",
    "credenciamento_viavel": True,
    "credenciamento_analise": "Viável. Depende da avaliação financeira e documental.",
    "alertas_impugnacao": ["Restrição territorial de uso do cartão (Item 16.4.1 do TR)"],
    "custo_emissao_cartoes": "150 cartões × R$ 5,00 = R$ 750,00",
    "justificativa": "Aderência total ao objeto, mas volume reduzido e taxa zero.",
    "analise_completa": "# 1. TABELAS DE DADOS DO CERTAME\n(transcrição integral)",
}


def test_cadastro_com_analise_importada():
    override_anterior = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db_teste
    try:
        settings.admin_email = ADMIN_EMAIL
        settings.admin_senha_inicial = ADMIN_SENHA
        db = TestingSession()
        security.bootstrap_admin(db)
        db.close()

        cliente = TestClient(app)
        r = cliente.post("/api/auth/login", json={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA})
        assert r.status_code == 200

        # --- cadastro COM análise importada ---
        r = cliente.post("/api/licitacoes", json={
            "objeto": "Vale-Alimentação União Paulista",
            "orgao": "Prefeitura Municipal de União Paulista",
            "municipio": "União Paulista", "uf": "SP",
            "modalidade": "Credenciamento Eletrônico",
            "numero_certame": "019/2026",
            "valor_estimado": 818694.0,
            "data_encerramento": "2026-07-17",
            "analise": ANALISE_IMPORTADA,
        })
        assert r.status_code == 201, r.text
        lic_id = r.json()["id"]

        db = TestingSession()
        lic = db.get(Licitacao, lic_id)
        assert lic.status_analise == "analisada"
        analise = db.execute(select(Analise).where(Analise.licitacao_id == lic_id)).scalar_one()
        assert analise.score_beneficios == 7 and analise.score_pagamentos == 0
        assert analise.score == 70  # maior score × 10
        assert analise.veredito == "revisar_manual"  # OPORTUNIDADE MODERADA
        assert analise.classificacao_final == "OPORTUNIDADE MODERADA"
        assert len(analise.documentos_habilitacao) == 3
        db.close()

        # Checklist de Documentação funciona direto (sem reanálise IA)
        r = cliente.get(f"/api/licitacoes/{lic_id}/documentos")
        assert r.status_code == 200
        docs = r.json()
        assert docs["tem_checklist"] is True
        assert docs["reanalise_gera_checklist"] is False
        assert [i["documento"] for i in docs["checklist"]] == [
            "Contrato social em vigor", "CND Federal", "Registro no PAT",
        ]

        # --- cadastro SEM análise: comportamento antigo preservado ---
        r = cliente.post("/api/licitacoes", json={
            "objeto": "Outra licitação manual", "numero_certame": "020/2026",
        })
        assert r.status_code == 201
        lic2_id = r.json()["id"]
        db = TestingSession()
        assert db.get(Licitacao, lic2_id).status_analise == "manual"
        assert db.execute(
            select(Analise).where(Analise.licitacao_id == lic2_id)
        ).scalar_one_or_none() is None
        db.close()

        # --- análise inválida NÃO derruba o cadastro (fica sem análise) ---
        r = cliente.post("/api/licitacoes", json={
            "objeto": "Licitação com análise quebrada", "numero_certame": "021/2026",
            "analise": {"score_beneficios": "não é número"},
        })
        assert r.status_code == 201
        lic3_id = r.json()["id"]
        db = TestingSession()
        assert db.get(Licitacao, lic3_id).status_analise == "manual"
        assert db.execute(
            select(Analise).where(Analise.licitacao_id == lic3_id)
        ).scalar_one_or_none() is None
        db.close()

        # --- importar análise por PDF em card existente (IA mockada) ---
        from unittest.mock import patch

        from app.analyzer.schemas import CamposLicitacao, ExtracaoCadastro, ResultadoAnalise

        extracao_fake = ExtracaoCadastro(
            campos=CamposLicitacao(
                municipio="União Paulista", uf="SP", valor_estimado=818694.0,
                data_encerramento="2026-07-17",
            ),
            analise=ResultadoAnalise.model_validate(ANALISE_IMPORTADA),
        )

        class AnalisadorFake:
            def extrair(self, texto=None, pdf_bytes=None):
                return extracao_fake

        # Card automático sem análise e com campos faltando (como os do mural Sistema S)
        r = cliente.post("/api/licitacoes", json={
            "objeto": "Card automático sem análise", "numero_certame": "030/2026",
        })
        lic4_id = r.json()["id"]
        db = TestingSession()
        lic4 = db.get(Licitacao, lic4_id)
        lic4.fonte = "fiesc"  # simula card de coleta automática
        db.commit()
        db.close()

        with patch("app.analyzer.criar_analisador", return_value=AnalisadorFake()):
            r = cliente.post(
                f"/api/licitacoes/{lic4_id}/analise-arquivo",
                files={"arquivo": ("analise.pdf", b"%PDF-1.4 conteudo", "application/pdf")},
            )
        assert r.status_code == 200, r.text
        atualizada = r.json()
        assert atualizada["analise"]["classificacao_final"] == "OPORTUNIDADE MODERADA"
        assert len(atualizada["analise"]["documentos_habilitacao"]) == 3
        # Campos vazios preenchidos pelo relatório; objeto original preservado
        assert atualizada["municipio"] == "União Paulista" and atualizada["uf"] == "SP"
        assert atualizada["valor_estimado"] == 818694.0
        assert atualizada["objeto"] == "Card automático sem análise"

        # PDF que não é relatório de análise -> 422 e nada é gravado
        extracao_fake.analise = None
        with patch("app.analyzer.criar_analisador", return_value=AnalisadorFake()):
            r = cliente.post(
                f"/api/licitacoes/{lic2_id}/analise-arquivo",
                files={"arquivo": ("edital.pdf", b"%PDF-1.4 edital", "application/pdf")},
            )
        assert r.status_code == 422
        db = TestingSession()
        assert db.execute(
            select(Analise).where(Analise.licitacao_id == lic2_id)
        ).scalar_one_or_none() is None
        db.close()

        print("OK - cadastro com análise, sem análise, análise inválida e importação por PDF no card")
    finally:
        if override_anterior:
            app.dependency_overrides[get_db] = override_anterior
        else:
            app.dependency_overrides.pop(get_db, None)


if __name__ == "__main__":
    test_cadastro_com_analise_importada()
