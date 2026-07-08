"""Migra TODOS os dados do SQLite local para um Postgres (ex.: Supabase).

Uso (na pasta backend, com o venv ativado):

    python scripts/migrar_para_postgres.py --destino "postgresql+psycopg2://usuario:senha@host:5432/postgres"

Argumentos:
    origem (posicional, opcional)  Caminho do arquivo SQLite. Default: licitaprospera.db
    --destino URL                  URL do banco de destino. Se omitido, usa a env
                                   DATABASE_URL (que NÃO pode ser SQLite).

O script:
  * copia todas as tabelas na ordem correta das FKs
    (usuarios -> sessoes -> perfil_empresa -> licitacoes -> analises -> oportunidades -> documentos_anexos);
  * preserva os IDs originais;
  * ajusta as sequences do Postgres ao final (setval), para os próximos INSERTs;
  * é seguro: ABORTA se o destino já tiver dados (não duplica nem sobrescreve nada).
"""
import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import JSON, create_engine, func, inspect, null, select, text

# permite rodar de qualquer diretório: adiciona backend/ ao sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base  # noqa: E402
from app import models  # noqa: E402,F401  (registra as tabelas no metadata)

# Ordem respeitando as FKs (pais antes dos filhos)
ORDEM_TABELAS = [
    "usuarios",
    "sessoes",
    "perfil_empresa",
    "licitacoes",
    "analises",
    "oportunidades",
    "documentos_anexos",
]


def _normalizar_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def migrar(origem_sqlite: str, destino_url: str, lote: int = 500) -> dict[str, int]:
    caminho = Path(origem_sqlite)
    if not caminho.is_file():
        raise SystemExit(f"ERRO: arquivo SQLite de origem não encontrado: {caminho.resolve()}")

    engine_origem = create_engine(f"sqlite:///{caminho.as_posix()}",
                                  connect_args={"check_same_thread": False})
    engine_destino = create_engine(_normalizar_url(destino_url))

    tabelas = [Base.metadata.tables[t] for t in ORDEM_TABELAS if t in Base.metadata.tables]

    # cria as tabelas que faltarem no destino
    Base.metadata.create_all(engine_destino)

    # trava de segurança: destino precisa estar vazio
    with engine_destino.connect() as conn:
        for tabela in tabelas:
            total = conn.execute(select(func.count()).select_from(tabela)).scalar()
            if total:
                raise SystemExit(
                    f"ERRO: o banco de destino já tem dados (tabela '{tabela.name}' com {total} linha(s)).\n"
                    "Este script só migra para um banco VAZIO, para não duplicar nem sobrescrever nada.\n"
                    "Se quiser recomeçar, apague as tabelas no destino e rode de novo."
                )

    inspector_origem = inspect(engine_origem)
    tabelas_origem = set(inspector_origem.get_table_names())

    copiadas: dict[str, int] = {}
    with engine_origem.connect() as conn_origem, engine_destino.begin() as conn_destino:
        for tabela in tabelas:
            if tabela.name not in tabelas_origem:
                print(f"  - {tabela.name}: não existe na origem, pulando")
                copiadas[tabela.name] = 0
                continue
            # só as colunas que existem nos dois lados (origem antiga pode não ter colunas novas)
            cols_origem = {c["name"] for c in inspector_origem.get_columns(tabela.name)}
            colunas = [c for c in tabela.columns if c.name in cols_origem]
            # em colunas JSON, None deve virar SQL NULL (e não o texto JSON 'null')
            cols_json = {c.name for c in colunas if isinstance(c.type, JSON)}

            def _valor(col: str, v):
                return null() if v is None and col in cols_json else v

            resultado = conn_origem.execute(select(*colunas))
            n = 0
            while True:
                linhas = resultado.fetchmany(lote)
                if not linhas:
                    break
                conn_destino.execute(
                    tabela.insert(),
                    [{c.name: _valor(c.name, v) for c, v in zip(colunas, linha)} for linha in linhas],
                )
                n += len(linhas)
            copiadas[tabela.name] = n
            print(f"  - {tabela.name}: {n} linha(s) copiada(s)")

        # ajusta as sequences do Postgres (IDs preservados => sequence ficou para trás)
        if engine_destino.dialect.name == "postgresql":
            for tabela in tabelas:
                pk = list(tabela.primary_key.columns)
                if len(pk) == 1 and pk[0].autoincrement is not False:
                    col = pk[0].name
                    conn_destino.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{tabela.name}', '{col}'), "
                        f"COALESCE((SELECT MAX({col}) FROM {tabela.name}), 0) + 1, false)"
                    ))
            print("  - sequences do Postgres ajustadas (setval)")

    return copiadas


def main() -> None:
    parser = argparse.ArgumentParser(description="Migra os dados do SQLite local para o Postgres.")
    parser.add_argument("origem", nargs="?", default="licitaprospera.db",
                        help="arquivo SQLite de origem (default: licitaprospera.db)")
    parser.add_argument("--destino", default=os.environ.get("DATABASE_URL", ""),
                        help="URL do banco de destino (default: env DATABASE_URL)")
    args = parser.parse_args()

    if not args.destino:
        raise SystemExit("ERRO: informe --destino <url do Postgres> (ou defina a env DATABASE_URL).")
    if args.destino.startswith("sqlite") and Path(args.origem).resolve() == \
            Path(args.destino.replace("sqlite:///", "")).resolve():
        raise SystemExit("ERRO: origem e destino são o mesmo arquivo SQLite.")

    print(f"Origem : sqlite:///{args.origem}")
    destino_mascarado = _normalizar_url(args.destino)
    if "@" in destino_mascarado:  # não imprime a senha
        destino_mascarado = destino_mascarado.split("@")[-1]
    print(f"Destino: ...@{destino_mascarado}" if "@" in args.destino else f"Destino: {destino_mascarado}")
    print("Copiando tabelas...")
    copiadas = migrar(args.origem, args.destino)
    total = sum(copiadas.values())
    print(f"\nMigração concluída: {total} linha(s) copiada(s) no total.")


if __name__ == "__main__":
    main()
