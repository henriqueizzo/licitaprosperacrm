"""Fábrica do analisador de editais — escolhe o provedor de IA pela configuração.

IA_PROVIDER no .env: "gemini" | "anthropic" | "" (auto).
No modo auto, usa o Gemini se GEMINI_API_KEY estiver configurada (nível gratuito),
senão o Claude se ANTHROPIC_API_KEY estiver configurada.
"""
from ..config import settings
from .schemas import CLASSIFICACOES, ErroCotaIA, ErroEntradaIA, ResultadoAnalise, UsoIA  # noqa: F401


def provedor_ativo() -> str | None:
    """Nome do provedor que será usado ("gemini"/"anthropic") ou None se nenhum configurado."""
    escolhido = (settings.ia_provider or "").strip().lower()
    if escolhido == "gemini":
        return "gemini" if settings.gemini_api_key else None
    if escolhido == "anthropic":
        return "anthropic" if settings.anthropic_api_key else None
    # auto
    if settings.gemini_api_key:
        return "gemini"
    if settings.anthropic_api_key:
        return "anthropic"
    return None


def criar_analisador():
    """Instancia o analisador do provedor ativo. Levanta RuntimeError se nenhum configurado."""
    provedor = provedor_ativo()
    if provedor == "gemini":
        from .gemini_analyzer import AnalisadorEditalGemini
        return AnalisadorEditalGemini()
    if provedor == "anthropic":
        from .claude_analyzer import AnalisadorEdital
        return AnalisadorEdital()
    raise RuntimeError(
        "Nenhum provedor de IA configurado — defina GEMINI_API_KEY (gratuito) ou "
        "ANTHROPIC_API_KEY no .env"
    )


# Compatibilidade com imports antigos
from .claude_analyzer import AnalisadorEdital  # noqa: E402,F401
