from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    # Google Gemini (nível gratuito do AI Studio) — alternativa sem custo para a análise
    gemini_api_key: str = ""
    # Alias que acompanha o flash mais recente — evita "model no longer available"
    # quando o Google aposenta versões antigas para contas novas
    gemini_model: str = "gemini-flash-latest"
    # Provedor da análise IA: "gemini" | "anthropic" | "" (auto: gemini se tiver chave, senão claude)
    ia_provider: str = ""
    conlicitacao_token: str = ""
    database_url: str = "sqlite:///./licitaprospera.db"

    @field_validator("database_url")
    @classmethod
    def _normalizar_database_url(cls, v: str) -> str:
        """Normaliza URLs de Postgres para o driver psycopg2.

        Supabase/Render/Heroku às vezes fornecem `postgres://` (esquema antigo,
        que o SQLAlchemy 2.x não aceita) ou `postgresql://` sem driver explícito.
        """
        if v.startswith("postgres://"):
            return "postgresql+psycopg2://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            return "postgresql+psycopg2://" + v[len("postgresql://"):]
        return v
    coleta_intervalo_horas: int = 6
    # score_minimo_oportunidade foi removido: toda licitação coletada entra no
    # pipeline; a análise IA só informa o card (extra="ignore" cobre .env antigos)

    # Modelo usado na análise dos editais
    claude_model: str = "claude-opus-4-8"

    # Autenticação: admin inicial (criado no 1º startup se não houver usuários)
    admin_email: str = ""
    admin_senha_inicial: str = ""
    # Secure=True exige HTTPS (ligar na nuvem); False para desenvolvimento local
    cookie_secure: bool = False
    # Validade da sessão de login, em dias
    sessao_dias: int = 7

    # Token do endpoint POST /api/pipeline/executar-cron (para cron externo, ex.: cron-job.org).
    # Vazio = rota desabilitada (retorna 404).
    cron_token: str = ""

    # Diretório do build do frontend (npm run build). Se existir, o FastAPI serve o
    # SPA em produção. Relativo ao diretório backend/. Em dev (sem dist) nada muda.
    frontend_dist: str = "../frontend/dist"


settings = Settings()
