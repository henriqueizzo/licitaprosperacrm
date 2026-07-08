"""Análise de editais com a API do Claude (claude-opus-4-8).

- PDF do edital vai como bloco `document` base64 (limites: 32 MB por request).
- Saída estruturada validada via `client.messages.parse` + Pydantic.
- Thinking adaptativo ligado (recomendado para análise complexa).
- Analisa a aderência para as DUAS empresas (Prospera Benefícios e Prospera
  Pagamentos), com score 0-10 para cada uma e classificação final.
"""
import base64
import logging
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from ..config import settings
from .prompts import SYSTEM_ANALISTA, prompt_analise

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 30 * 1024 * 1024  # margem sob o limite de 32 MB da API

CLASSIFICACOES = [
    "EXCELENTE OPORTUNIDADE",
    "BOA OPORTUNIDADE",
    "OPORTUNIDADE MODERADA",
    "ALTO RISCO",
    "NÃO RECOMENDADO",
]


class Prazo(BaseModel):
    descricao: str = Field(description="Ex.: Abertura das propostas, Prazo de impugnação")
    data_ou_prazo: str = Field(description="Data (ISO) ou prazo em dias, como consta no edital")


class DocumentoHabilitacao(BaseModel):
    categoria: Literal[
        "HABILITAÇÃO JURÍDICA",
        "REGULARIDADE FISCAL E TRABALHISTA",
        "QUALIFICAÇÃO TÉCNICA",
        "QUALIFICAÇÃO ECONÔMICO-FINANCEIRA",
        "OUTROS DOCUMENTOS / DECLARAÇÕES",
    ] = Field(description="Categoria do documento na TABELA DE DOCUMENTOS PARA HABILITAÇÃO")
    documento: str = Field(description="Nome/descrição objetiva do documento exigido")
    referencia_edital: str = Field(
        description="Item/cláusula/página do edital que exige o documento, ou 'Não informado no edital'"
    )


class ResultadoAnalise(BaseModel):
    objeto_resumido: str = Field(description="Objeto da licitação em 1-2 frases claras")
    prazos: list[Prazo]
    exigencias_habilitacao: list[str]
    exigencias_tecnicas: list[str]
    atestados_exigidos: list[str] = Field(description="Atestados de capacidade técnica exigidos")
    documentos_habilitacao: list[DocumentoHabilitacao] = Field(
        description=(
            "TABELA DE DOCUMENTOS PARA HABILITAÇÃO estruturada: um item por documento "
            "exigido no edital, com categoria, documento e referência no edital"
        )
    )
    riscos: list[str] = Field(description="Riscos e pontos de atenção para a decisão")
    score_beneficios: int = Field(
        description="Score final de 0 a 10 para a PROSPERA BENEFÍCIOS (VA/VR, multibenefícios)"
    )
    score_pagamentos: int = Field(
        description="Score final de 0 a 10 para a PROSPERA PAGAMENTOS (adquirência, POS, gateway)"
    )
    classificacao_final: Literal[
        "EXCELENTE OPORTUNIDADE",
        "BOA OPORTUNIDADE",
        "OPORTUNIDADE MODERADA",
        "ALTO RISCO",
        "NÃO RECOMENDADO",
    ] = Field(description="Classificação final da licitação")
    credenciamento_viavel: bool = Field(
        description=(
            "false somente se o certame exigir regime societário que impeça S.A. "
            "(exclusivo ME/EPP/MEI) ou personalização do cartão com nome do portador"
        )
    )
    credenciamento_analise: str = Field(
        description="Texto da 'Análise Preliminar de Credenciamento' da Tabela 1"
    )
    alertas_impugnacao: list[str] = Field(
        description=(
            "Alertas de impugnação (taxa negativa, pós-pago, arranjo fechado etc.) "
            "com fundamentação legal resumida; lista vazia se não houver"
        )
    )
    custo_emissao_cartoes: str = Field(
        description="Cálculo explícito 'X beneficiários × R$ 5,00 = R$ Y,00' ou 'Não informado no edital'"
    )
    justificativa: str = Field(description="Justificativa objetiva dos scores e da classificação final")
    analise_completa: str = Field(
        description=(
            "Texto integral da análise no FORMATO DA RESPOSTA definido (todas as tabelas "
            "em Markdown e as 10 seções, sem emojis)"
        )
    )


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

        response = self.client.messages.parse(
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

        resultado: ResultadoAnalise = response.parsed_output
        # Garante coerência dos scores mesmo se o modelo escorregar (escala 0-10)
        resultado.score_beneficios = max(0, min(10, resultado.score_beneficios))
        resultado.score_pagamentos = max(0, min(10, resultado.score_pagamentos))
        return resultado, response.usage
