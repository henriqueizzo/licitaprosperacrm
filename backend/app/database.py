from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Colunas adicionadas à tabela `analises` (análise Prospera Benefícios + Pagamentos).
# ALTER TABLE ... ADD COLUMN funciona no SQLite e preserva os dados existentes.
_MIGRACOES_ANALISES = {
    "score_beneficios": "INTEGER NOT NULL DEFAULT 0",
    "score_pagamentos": "INTEGER NOT NULL DEFAULT 0",
    "classificacao_final": "VARCHAR(40) NOT NULL DEFAULT ''",
    "credenciamento_viavel": "BOOLEAN NOT NULL DEFAULT 1",
    "credenciamento_analise": "TEXT NOT NULL DEFAULT ''",
    "alertas_impugnacao": "JSON",
    "custo_emissao_cartoes": "VARCHAR(200) NOT NULL DEFAULT ''",
    "analise_completa": "TEXT NOT NULL DEFAULT ''",
    "documentos_habilitacao": "JSON",
}


def migrar_esquema() -> list[str]:
    """Adiciona colunas novas em bancos já existentes, sem apagar dados.

    Idempotente: só adiciona o que ainda não existe. Retorna a lista de colunas criadas.
    """
    inspector = inspect(engine)
    if "analises" not in inspector.get_table_names():
        return []  # banco novo — create_all já cria a tabela completa
    existentes = {c["name"] for c in inspector.get_columns("analises")}
    criadas: list[str] = []
    with engine.begin() as conn:
        for coluna, ddl in _MIGRACOES_ANALISES.items():
            if coluna not in existentes:
                conn.execute(text(f"ALTER TABLE analises ADD COLUMN {coluna} {ddl}"))
                criadas.append(coluna)
    return criadas


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
