from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

if settings.database_url.startswith("sqlite"):
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:
    # Postgres (Supabase etc.): pool_pre_ping descarta conexões derrubadas pelo
    # pooler/idle timeout antes de usá-las (evita erros após o serviço "acordar").
    engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Colunas adicionadas à tabela `analises` (análise Prospera Benefícios + Pagamentos).
# ALTER TABLE ... ADD COLUMN funciona no SQLite e no Postgres, preservando os dados.
# O default do BOOLEAN é dialect-específico (SQLite usa 1, Postgres usa TRUE).
def _migracoes_analises(dialeto: str) -> dict[str, str]:
    bool_true = "1" if dialeto == "sqlite" else "TRUE"
    return {
        "score_beneficios": "INTEGER NOT NULL DEFAULT 0",
        "score_pagamentos": "INTEGER NOT NULL DEFAULT 0",
        "classificacao_final": "VARCHAR(40) NOT NULL DEFAULT ''",
        "credenciamento_viavel": f"BOOLEAN NOT NULL DEFAULT {bool_true}",
        "credenciamento_analise": "TEXT NOT NULL DEFAULT ''",
        "alertas_impugnacao": "JSON",
        "custo_emissao_cartoes": "VARCHAR(200) NOT NULL DEFAULT ''",
        "analise_completa": "TEXT NOT NULL DEFAULT ''",
        "documentos_habilitacao": "JSON",
    }


def _migracoes(dialeto: str) -> dict[str, dict[str, str]]:
    """Colunas novas por tabela, para bancos criados antes delas existirem."""
    return {
        "analises": _migracoes_analises(dialeto),
        "execucoes_pipeline": {
            "avisos": "JSON",
        },
    }


def migrar_esquema() -> list[str]:
    """Adiciona colunas novas em bancos já existentes, sem apagar dados.

    Idempotente e dialect-aware (SQLite e Postgres): usa `sqlalchemy.inspect` para
    a introspecção e só adiciona o que ainda não existe. Retorna as colunas criadas.
    """
    inspector = inspect(engine)
    tabelas = set(inspector.get_table_names())
    criadas: list[str] = []
    with engine.begin() as conn:
        for tabela, colunas in _migracoes(engine.dialect.name).items():
            if tabela not in tabelas:
                continue  # banco novo — create_all já cria a tabela completa
            existentes = {c["name"] for c in inspector.get_columns(tabela)}
            for coluna, ddl in colunas.items():
                if coluna not in existentes:
                    conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {ddl}"))
                    criadas.append(f"{tabela}.{coluna}")
    return criadas


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
