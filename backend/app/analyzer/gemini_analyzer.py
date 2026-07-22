"""Análise de editais com a API do Google Gemini (nível gratuito).

Mesma interface do analisador Claude: `analisar(dados, perfil, pdf)` retorna
(ResultadoAnalise, UsoIA). Usa o mesmo prompt oficial (prompts.py) e o mesmo
schema Pydantic — o Gemini valida a saída via `response_schema`.

Nível gratuito (AI Studio): limite por minuto e por dia. Quando o limite diário
estoura (429 RESOURCE_EXHAUSTED persistente), levantamos ErroCotaIA para o
pipeline manter as licitações pendentes e tentar no ciclo seguinte.
"""
import logging
import time

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from ..config import settings
from .prompts import SYSTEM_ANALISTA, SYSTEM_EXTRACAO, prompt_analise, prompt_extracao
from .schemas import ErroCotaIA, ErroEntradaIA, ExtracaoCadastro, ResultadoAnalise, UsoIA

logger = logging.getLogger(__name__)

# Inline data no Gemini: limite de ~20 MB por request — acima disso analisamos sem o PDF
MAX_PDF_BYTES = 19 * 1024 * 1024

# 429 de rate limit por minuto se resolve esperando; o diário não — daí ErroCotaIA
ESPERAS_RATE_LIMIT = [30, 60]

# 5xx transitório ("high demand") também merece retry antes de desistir
ESPERAS_5XX = [15, 45]

# Se o modelo principal seguir indisponível (503 persistente), tenta o flash-lite,
# que tem mais capacidade ociosa no nível gratuito
MODELOS_FALLBACK = ["gemini-flash-lite-latest"]


def _normalizar_pdfs(pdf_bytes: bytes | list[bytes] | None, teto: int) -> list[bytes]:
    """Aceita PDF único ou lista; descarta o que estourar o teto conjunto do provedor."""
    if not pdf_bytes:
        return []
    candidatos = pdf_bytes if isinstance(pdf_bytes, list) else [pdf_bytes]
    pdfs: list[bytes] = []
    total = 0
    for pdf in candidatos:
        if total + len(pdf) > teto:
            logger.warning(
                "PDF com %.1f MB excede o teto do provedor; analisando sem ele",
                len(pdf) / 1024 / 1024,
            )
            continue
        pdfs.append(pdf)
        total += len(pdf)
    return pdfs


class AnalisadorEditalGemini:
    def __init__(self):
        # attempts=1 DESLIGA o retry interno do SDK (tenacity): com cota esgotada
        # ele dormia minutos obedecendo o "retry in 59s" do Google ANTES de nos
        # devolver o 429 — nossos retries curtos nunca valiam e as chamadas
        # interativas estouravam o corte de ~100s do proxy do Render (502).
        # Toda a política de retry/fallback é nossa, em _gerar_com_retry.
        self.client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=genai_types.HttpOptions(
                retry_options=genai_types.HttpRetryOptions(attempts=1),
            ),
        )

    def analisar(self, dados_licitacao: dict, perfil: dict,
                 pdf_bytes: bytes | list[bytes] | None = None,
                 conteudo_link: str | None = None):
        """Analisa uma licitação. Retorna (ResultadoAnalise, UsoIA).

        `pdf_bytes` aceita um PDF ou uma LISTA de PDFs (edital + termo de
        referência + anexos). Regra de fonte: TEM documento? analisa o PDF;
        NÃO tem? `conteudo_link` (conteúdo do link do certame) é a fonte.
        """
        pdfs = _normalizar_pdfs(pdf_bytes, MAX_PDF_BYTES)

        contents: list = [
            genai_types.Part.from_bytes(data=pdf, mime_type="application/pdf") for pdf in pdfs
        ]
        contents.append(prompt_analise(
            perfil, dados_licitacao, tem_pdf=bool(pdfs),
            conteudo_link=None if pdfs else conteudo_link,
        ))

        # max_tokens folgado: análise completa + checklist integral de documentos
        response = self._gerar_com_retry(contents, max_tokens=32000)

        resultado: ResultadoAnalise | None = response.parsed
        if resultado is None:
            # response_schema garante JSON; se o parse falhou, tenta validar o texto cru
            resultado = ResultadoAnalise.model_validate_json(response.text)

        uso = response.usage_metadata
        entrada = (uso.prompt_token_count or 0) if uso else 0
        saida = ((uso.candidates_token_count or 0) + (uso.thoughts_token_count or 0)) if uso else 0
        return resultado.normalizar(), UsoIA(input_tokens=entrada, output_tokens=saida)

    def extrair(self, texto: str | None = None, pdf_bytes: bytes | None = None) -> ExtracaoCadastro:
        """Extrai campos cadastrais de um resumo/texto ou PDF (preenchimento automático).

        Se o documento for um relatório de análise do time (não o edital), a IA
        também transcreve a análise estruturada em `analise` — o cadastro manual
        grava essa análise e o checklist de documentação passa a funcionar.
        """
        if pdf_bytes and len(pdf_bytes) > MAX_PDF_BYTES:
            pdf_bytes = None
        contents: list = []
        if pdf_bytes:
            contents.append(genai_types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"))
        contents.append(prompt_extracao(texto, tem_pdf=pdf_bytes is not None))
        # A extração NÃO transcreve o documento (analise_completa fica vazia e o
        # backend a preenche com o texto do PDF) — resposta curta o bastante para
        # caber no corte de ~100s do proxy do Render. Retries CURTOS pelo mesmo
        # motivo: retry longo estoura o proxy, o usuário clica de novo e a
        # execução dobrada grava dados duplicados.
        # max_tokens 16k: o modelo reserva às vezes ignora a instrução de NÃO
        # transcrever e produz resposta longa — com 8k o JSON vinha truncado e a
        # validação estourava ("erro 500" no cadastro via PDF).
        response = self._gerar_com_retry(
            contents, system=SYSTEM_EXTRACAO, schema=ExtracaoCadastro, max_tokens=16000,
            esperas_429=[5], esperas_5xx=[5],
            # Extração é cópia estruturada, não raciocínio: thinking desligado
            # corta mais da metade do tempo de resposta (crítico p/ o proxy)
            thinking_budget=0,
        )
        extracao = response.parsed
        if extracao is None:
            texto = response.text
            if not texto:
                fr = None
                if getattr(response, "candidates", None):
                    fr = getattr(response.candidates[0], "finish_reason", None)
                logger.warning("Extração sem texto na resposta do Gemini (finish_reason=%s)", fr)
                raise RuntimeError(
                    "A IA não retornou a extração (resposta vazia/bloqueada) — tente novamente."
                )
            try:
                extracao = ExtracaoCadastro.model_validate_json(texto)
            except Exception as exc:
                logger.warning("JSON da extração inválido/truncado (%d chars): %s", len(texto), exc)
                raise RuntimeError(
                    "A IA retornou uma resposta incompleta — tente novamente em instantes."
                ) from exc
        if extracao.analise is not None:
            extracao.analise.normalizar()
        return extracao

    def redigir(self, instrucao: str, system: str) -> str:
        """Gera texto corrido (sem schema) — usado p/ redigir declarações e afins.

        Chamada interativa (botão na tela) atrás do proxy do Render, que corta
        requests em ~100s: retries curtos — se o Gemini estiver congestionado,
        quem chama usa o fallback determinístico em vez de estourar o proxy.
        """
        response = self._gerar_com_retry(
            [instrucao], system=system, schema=None, max_tokens=4000,
            esperas_429=[8], esperas_5xx=[8],
        )
        return (response.text or "").strip()

    def _gerar_com_retry(self, contents: list, system: str = SYSTEM_ANALISTA,
                         schema=ResultadoAnalise, max_tokens: int = 16000,
                         esperas_429: list[int] | None = None,
                         esperas_5xx: list[int] | None = None,
                         thinking_budget: int | None = None):
        esperas_429 = ESPERAS_RATE_LIMIT if esperas_429 is None else esperas_429
        esperas_5xx = ESPERAS_5XX if esperas_5xx is None else esperas_5xx
        modelos = [settings.gemini_model] + [m for m in MODELOS_FALLBACK if m != settings.gemini_model]
        ultima_5xx: Exception | None = None
        cota_esgotada: Exception | None = None
        for modelo in modelos:
            rate_limits = 0
            tentativas_5xx = 0
            while True:
                try:
                    return self._gerar(modelo, contents, system, schema, max_tokens, thinking_budget)
                except genai_errors.APIError as exc:
                    if exc.code == 429:
                        if rate_limits < len(esperas_429):
                            espera = esperas_429[rate_limits]
                            rate_limits += 1
                            logger.warning("Gemini rate limit (429), aguardando %ds", espera)
                            time.sleep(espera)
                            continue
                        # Cota do modelo esgotada (provável limite DIÁRIO do nível
                        # gratuito) — cada modelo tem cota própria: tenta o próximo
                        # da lista antes de desistir do lote.
                        logger.warning("Gemini %s com cota esgotada; tentando próximo modelo", modelo)
                        cota_esgotada = exc
                        break
                    if exc.code in (401, 403):
                        raise ErroCotaIA(f"Chave do Gemini inválida ou sem permissão ({exc.code}).") from exc
                    if exc.code == 400:
                        # O Gemini rejeitou a ENTRADA (tipicamente o PDF): erro
                        # permanente — repetir com o mesmo arquivo não resolve.
                        logger.warning("Gemini rejeitou a entrada (400): %s", exc)
                        raise ErroEntradaIA(
                            "A IA não conseguiu ler o documento enviado — o PDF pode estar "
                            "corrompido, protegido por senha ou em formato não suportado. "
                            "Reexporte o PDF (imprimir → salvar como PDF) ou cole o resumo."
                        ) from exc
                    if exc.code and exc.code >= 500:
                        if tentativas_5xx < len(esperas_5xx):
                            espera = esperas_5xx[tentativas_5xx]
                            tentativas_5xx += 1
                            logger.warning("Gemini %s indisponível (%s), aguardando %ds",
                                           modelo, exc.code, espera)
                            time.sleep(espera)
                            continue
                        logger.warning("Gemini %s segue indisponível; tentando próximo modelo", modelo)
                        ultima_5xx = exc
                        break  # próximo modelo da lista
                    raise
                except httpx.HTTPError as exc:
                    # Falha de rede/transporte crua: com o retry interno do SDK
                    # desligado (attempts=1), timeouts e conexões derrubadas chegam
                    # aqui — trata como indisponibilidade transitória (mesma
                    # política dos 5xx: espera curta e depois próximo modelo).
                    if tentativas_5xx < len(esperas_5xx):
                        espera = esperas_5xx[tentativas_5xx]
                        tentativas_5xx += 1
                        logger.warning("Falha de rede com o Gemini (%s), aguardando %ds",
                                       type(exc).__name__, espera)
                        time.sleep(espera)
                        continue
                    logger.warning("Rede com o Gemini segue falhando (%s); tentando próximo modelo",
                                   type(exc).__name__)
                    ultima_5xx = exc
                    break  # próximo modelo da lista
        if cota_esgotada is not None:
            raise ErroCotaIA(
                "Cota do Gemini esgotada (429 persistente — provável limite diário do "
                "nível gratuito). As análises continuam no próximo ciclo."
            ) from cota_esgotada
        # Todos os modelos indisponíveis (5xx ou rede) — transitório: RuntimeError
        # vira 503 "tente novamente" nas rotas interativas e "erro" reenfileirável
        # no pipeline.
        raise RuntimeError(
            "IA indisponível no momento (sobrecarga ou falha de conexão) — "
            "tente novamente em instantes."
        ) from ultima_5xx

    def _gerar(self, modelo: str, contents: list, system: str, schema, max_tokens: int,
               thinking_budget: int | None = None):
        # schema=None: saída em texto corrido (redigir); com schema: JSON validado
        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
        )
        if schema is not None:
            config.response_mime_type = "application/json"
            config.response_schema = schema
        if thinking_budget is not None:
            config.thinking_config = genai_types.ThinkingConfig(thinking_budget=thinking_budget)
        return self.client.models.generate_content(
            model=modelo,
            contents=contents,
            config=config,
        )
