"""Modelos da saída estruturada da análise — compartilhados entre os provedores
de IA (Claude e Gemini). O pipeline e o CRM só conhecem estes modelos; qual
provedor gerou a análise é detalhe de configuração (IA_PROVIDER)."""
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

CLASSIFICACOES = [
    "EXCELENTE OPORTUNIDADE",
    "BOA OPORTUNIDADE",
    "OPORTUNIDADE MODERADA",
    "ALTO RISCO",
    "NÃO RECOMENDADO",
]


class ErroCotaIA(Exception):
    """Saldo/cota do provedor de IA esgotado (billing, créditos, limite diário).

    O pipeline trata diferente de um erro comum: mantém a licitação como
    "pendente" (será analisada no próximo ciclo) e interrompe o lote em vez de
    queimar todas as pendentes marcando "erro".
    """


@dataclass
class UsoIA:
    """Uso de tokens normalizado entre provedores (mesma interface do usage da Anthropic)."""

    input_tokens: int
    output_tokens: int


class CamposLicitacao(BaseModel):
    """Campos cadastrais extraídos de um resumo/link para o Cadastro Manual."""

    objeto: str = Field(default="", description="Objeto/título da licitação")
    orgao: str = Field(default="", description="Órgão/entidade licitante")
    municipio: str = Field(default="", description="Município do órgão")
    uf: str = Field(default="", description="Sigla da UF com 2 letras maiúsculas")
    modalidade: str = Field(default="", description="Modalidade (ex.: Pregão Eletrônico)")
    numero_certame: str = Field(default="", description="Número/identificação do certame")
    valor_estimado: float | None = Field(default=None, description="Valor estimado em reais")
    data_abertura: str = Field(default="", description="Abertura das propostas, YYYY-MM-DD ou vazio")
    data_encerramento: str = Field(default="", description="Encerramento/limite, YYYY-MM-DD ou vazio")
    responsavel: str = Field(default="", description="Agente de contratação/pregoeiro/contato")
    observacoes: str = Field(default="", description="Outras informações úteis, 1-3 frases")


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

    def normalizar(self) -> "ResultadoAnalise":
        """Garante coerência dos scores mesmo se o modelo escorregar (escala 0-10)."""
        self.score_beneficios = max(0, min(10, self.score_beneficios))
        self.score_pagamentos = max(0, min(10, self.score_pagamentos))
        return self


class ExtracaoCadastro(BaseModel):
    """Saída do preenchimento automático do Cadastro Manual.

    Além dos campos cadastrais, o documento anexado pode ser o RELATÓRIO DE
    ANÁLISE que o time produz antes do cadastro (tabelas do certame + checklist
    de documentos + scores). Nesse caso a IA transcreve a análise para o campo
    `analise`, que o CRM grava como se fosse uma análise própria — habilitando o
    checklist de Documentação sem reanalisar o edital.
    """

    campos: CamposLicitacao
    analise: ResultadoAnalise | None = Field(
        default=None,
        description=(
            "Análise estruturada transcrita do documento, SOMENTE quando o documento "
            "anexado for um relatório de análise (com checklist de documentos, scores, "
            "classificação). null quando for apenas um edital/aviso sem análise."
        ),
    )
