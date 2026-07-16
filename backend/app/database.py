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
    bool_false = "0" if dialeto == "sqlite" else "FALSE"
    return {
        "analises": _migracoes_analises(dialeto),
        # Marcador de certame suspenso (silencia o alerta de prazo do card)
        "licitacoes": {
            "suspensa": f"BOOLEAN NOT NULL DEFAULT {bool_false}",
        },
        "execucoes_pipeline": {
            "avisos": "JSON",
        },
        # Último acesso do usuário (aba Atividade). TIMESTAMP vale nos dois dialetos.
        "usuarios": {
            "ultimo_acesso": "TIMESTAMP",
        },
        # Dados oficiais da empresa para as declarações geradas em Word.
        # DDL SÓ COM ASCII: literal com acento em ALTER TABLE chegou corrompido ao
        # Postgres de produção ('Benefícios' virou mojibake). Valores acentuados são
        # aplicados depois, via UPDATE com parâmetro bound (o driver codifica certo).
        "perfil_empresa": {
            "razao_social": "TEXT NOT NULL DEFAULT ''",
            "cnpj": "TEXT NOT NULL DEFAULT ''",
            "endereco": "TEXT NOT NULL DEFAULT ''",
            "cidade_sede": "TEXT NOT NULL DEFAULT ''",
            "representante_nome": "TEXT NOT NULL DEFAULT 'Dario'",
            "representante_cargo": "TEXT NOT NULL DEFAULT ''",
        },
    }


# Estágios do pipeline renomeados/unificados (kanban novo). UPDATEs idempotentes
# (o WHERE só casa com valores antigos) e em SQL simples, válido em SQLite e Postgres.
_RENOMEACOES_ESTAGIOS = [
    ("proposta", "proposta_enviada"),
    ("perdeu", "perdeu_nogo"),
    ("descartada", "perdeu_nogo"),
]


# Colunas que nasceram String(N) mas recebem texto livre: alargar para TEXT.
# O SQLite não impõe o limite (nada a fazer lá); o Postgres impõe e derrubava
# o cadastro manual com 500 quando o texto passava do tamanho.
_ALARGAMENTOS = {
    ("oportunidades", "responsavel"): "TEXT",
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
        if "oportunidades" in tabelas:
            for antigo, novo in _RENOMEACOES_ESTAGIOS:
                res = conn.execute(
                    text("UPDATE oportunidades SET estagio = :novo WHERE estagio = :antigo"),
                    {"novo": novo, "antigo": antigo},
                )
                if res.rowcount:
                    criadas.append(f"estagio:{antigo}->{novo}({res.rowcount})")

            # Fim da aba "No Go": toda licitação entra no pipeline. Backfill para
            # licitações represadas sem oportunidade (produção). Idempotente — o
            # NOT EXISTS só cria o que falta — e em SQL válido em SQLite e Postgres.
            if "licitacoes" in tabelas:
                res = conn.execute(text(
                    "INSERT INTO oportunidades "
                    "(licitacao_id, estagio, notas, responsavel, criado_em, atualizado_em) "
                    "SELECT l.id, 'identificada', 'Backfill: entrada automática no pipeline', '', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                    "FROM licitacoes l "
                    "WHERE NOT EXISTS (SELECT 1 FROM oportunidades o WHERE o.licitacao_id = l.id)"
                ))
                if res.rowcount:
                    criadas.append(f"backfill_oportunidades({res.rowcount})")
        # Preenche/conserta o cargo padrão do representante com parâmetro bound
        # (nunca em DDL — ver comentário em _migracoes). Só mexe quando o valor está
        # vazio ou contém U+FFFD (marca da corrupção); personalização do usuário fica.
        if "perfil_empresa" in tabelas:
            res = conn.execute(
                text(
                    "UPDATE perfil_empresa SET representante_cargo = :v "
                    "WHERE representante_cargo = '' "
                    "OR representante_cargo LIKE '%' || :fffd || '%'"
                ),
                {"v": "CEO — Prospera Benefícios", "fffd": "�"},
            )
            if res.rowcount:
                criadas.append(f"perfil.representante_cargo({res.rowcount})")

        if engine.dialect.name != "sqlite":
            for (tabela, coluna), tipo in _ALARGAMENTOS.items():
                if tabela not in tabelas:
                    continue
                atual = next((c for c in inspector.get_columns(tabela) if c["name"] == coluna), None)
                if atual is not None and "VARCHAR" in str(atual["type"]).upper():
                    conn.execute(text(f"ALTER TABLE {tabela} ALTER COLUMN {coluna} TYPE {tipo}"))
                    criadas.append(f"{tabela}.{coluna}->{tipo}")

            # Segurança (alerta rls_disabled_in_public do Supabase): o Supabase expõe
            # as tabelas do schema public numa API REST pública; sem RLS, quem tiver a
            # chave do projeto lê/edita tudo. O CRM não usa essa API — acessa o banco
            # por conexão direta como DONO das tabelas, e dono não é afetado por RLS.
            # Ligar RLS (sem policies) fecha a API pública sem mudar nada no app, e
            # roda a cada startup para cobrir tabelas criadas no futuro.
            sem_rls = conn.execute(text(
                "SELECT c.relname FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity"
            )).scalars().all()
            for tabela in sem_rls:
                conn.execute(text(f'ALTER TABLE public."{tabela}" ENABLE ROW LEVEL SECURITY'))
                criadas.append(f"RLS:{tabela}")
    return criadas


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
