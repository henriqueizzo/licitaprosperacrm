from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    conlicitacao_token: str = ""
    database_url: str = "sqlite:///./licitaprospera.db"
    coleta_intervalo_horas: int = 6
    score_minimo_oportunidade: int = 60

    # Modelo usado na análise dos editais
    claude_model: str = "claude-opus-4-8"

    # Autenticação: admin inicial (criado no 1º startup se não houver usuários)
    admin_email: str = ""
    admin_senha_inicial: str = ""
    # Secure=True exige HTTPS (ligar na nuvem); False para desenvolvimento local
    cookie_secure: bool = False
    # Validade da sessão de login, em dias
    sessao_dias: int = 7


settings = Settings()
