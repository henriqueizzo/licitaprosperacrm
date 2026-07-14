"""Análise de editais com a API do Claude (claude-opus-4-8).

- PDF do edital vai como bloco `document` base64 (limites: 32 MB por request).
- Saída estruturada validada via `client.messages.parse` + Pydantic.
- Thinking adaptativo ligado (recomendado para análise complexa).
- Analisa a aderência para as DUAS empresas (Prospera Benefícios e Prospera
  Pagamentos), com score 0-10 para cada uma e classificação final.
"""
import base64
import logging

import anthropic

from ..config import settings
from .prompts import SYSTEM_ANALISTA, SYSTEM_EXTRACAO, prompt_analise, prompt_extracao
from .schemas import (  # noqa: F401 (reexport legado)
    CLASSIFICACOES,
    CamposLicitacao,
    ErroCotaIA,
    ResultadoAnalise,
)

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 30 * 1024 * 1024  # margem sob o limite de 32 MB da API


class AnalisadorEdital:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def analisar(self, dados_licitacao: dict, perfil: dict, pdf_bytes: bytes | None = None):
        """Analisa uma licitação. Retorna (ResultadoAnalise, usage)."""
        content: list[dict] = []

        if pdf_bytes and len(pdf_bytes) > MAX_PDF_BYTES:
            logger.warning(
                "Edital com %.1f MB excede o limite da API; analisando sem o PDF",
                len(pdf_bytes) / 1024 / 1024,
            )
            pdf_bytes = None

        if pdf_bytes:
            content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf_bytes).decode(),
                },
            })

        content.append({
            "type": "text",
            "text": prompt_analise(perfil, dados_licitacao, tem_pdf=pdf_bytes is not None),
        })

        try:
            response = self._chamar(content)
        except anthropic.BadRequestError as exc:
            if "credit balance" in str(exc.message).lower():
                raise ErroCotaIA(
                    "Créditos da API Anthropic esgotados — recarregue em console.anthropic.com "
                    "(Plans & Billing). As análises continuam no próximo ciclo após a recarga."
                ) from exc
            raise
        except anthropic.RateLimitError as exc:
            # 429 persistente (após os retries do SDK): trata como cota para reanalisar depois
            raise ErroCotaIA("Rate limit da API Anthropic persistente — tentaremos no próximo ciclo.") from exc

        resultado: ResultadoAnalise = response.parsed_output
        return resultado.normalizar(), response.usage

    def extrair(self, texto: str | None = None, pdf_bytes: bytes | None = None) -> CamposLicitacao:
        """Extrai campos cadastrais de um resumo/texto ou PDF (preenchimento automático)."""
        if pdf_bytes and len(pdf_bytes) > MAX_PDF_BYTES:
            pdf_bytes = None
        content: list[dict] = []
        if pdf_bytes:
            content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.standard_b64encode(pdf_bytes).decode(),
                },
            })
        content.append({"type": "text", "text": prompt_extracao(texto, tem_pdf=pdf_bytes is not None)})
        try:
            response = self.client.messages.parse(
                model=settings.claude_model,
                max_tokens=4000,
                system=SYSTEM_EXTRACAO,
                messages=[{"role": "user", "content": content}],
                output_format=CamposLicitacao,
            )
        except anthropic.BadRequestError as exc:
            if "credit balance" in str(exc.message).lower():
                raise ErroCotaIA("Créditos da API Anthropic esgotados.") from exc
            raise
        except anthropic.RateLimitError as exc:
            raise ErroCotaIA("Rate limit da API Anthropic persistente.") from exc
        return response.parsed_output

    def _chamar(self, content: list[dict]):
        return self.client.messages.parse(
            model=settings.claude_model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            # Prefixo estável (system) cacheado — reduz custo entre análises consecutivas
            system=[{
                "type": "text",
                "text": SYSTEM_ANALISTA,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": content}],
            output_format=ResultadoAnalise,
        )
