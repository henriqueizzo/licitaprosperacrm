from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Usuario(Base):
    """Usuário do sistema (login por email + senha bcrypt)."""

    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(100))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Atualizado pela dependency de auth no máximo 1x por minuto (não escreve a cada request)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessoes: Mapped[list["Sessao"]] = relationship(back_populates="usuario", cascade="all, delete-orphan")


class Sessao(Base):
    """Sessão de login. Guarda apenas o SHA-256 do token (o token vai no cookie HttpOnly)."""

    __tablename__ = "sessoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expira_em: Mapped[datetime] = mapped_column(DateTime)

    usuario: Mapped[Usuario] = relationship(back_populates="sessoes")


class EventoUso(Base):
    """Evento de uso do sistema (alimenta a aba Atividade e o dashboard, só admin).

    `tipo` é um valor controlado por código (login, ver_documentos, download_documento,
    upload_documento, mover_estagio, cadastro_manual, coleta_manual, reanalise,
    extracao_cadastro). Rotas de listagem/polling NÃO geram evento, para não inflar
    a tabela. `detalhe` é texto livre montado pelo código — Text por segurança.
    """

    __tablename__ = "eventos_uso"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(40))
    licitacao_id: Mapped[int | None] = mapped_column(ForeignKey("licitacoes.id"), nullable=True)
    detalhe: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Licitacao(Base):
    """Licitação coletada de uma fonte externa."""

    __tablename__ = "licitacoes"
    __table_args__ = (UniqueConstraint("fonte", "id_externo", name="uq_fonte_id_externo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fonte: Mapped[str] = mapped_column(String(30))          # pncp | conlicitacao | bll
    id_externo: Mapped[str] = mapped_column(String(120))    # id na fonte de origem
    orgao: Mapped[str] = mapped_column(String(300), default="")
    municipio: Mapped[str] = mapped_column(String(120), default="")
    uf: Mapped[str] = mapped_column(String(2), default="")
    modalidade: Mapped[str] = mapped_column(String(80), default="")
    objeto: Mapped[str] = mapped_column(Text, default="")
    valor_estimado: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_abertura: Mapped[str] = mapped_column(String(30), default="")     # ISO
    data_encerramento: Mapped[str] = mapped_column(String(30), default="")  # ISO
    link: Mapped[str] = mapped_column(Text, default="")
    edital_url: Mapped[str] = mapped_column(Text, default="")
    # Sistema onde a disputa corre (BLL, Portal de Compras Públicas, ConLicitação…)
    # e o endereço da licitação nesse sistema (link que o time recebe por e-mail).
    sistema: Mapped[str] = mapped_column(Text, default="")
    endereco_licitacao: Mapped[str] = mapped_column(Text, default="")
    status_analise: Mapped[str] = mapped_column(String(20), default="pendente")  # pendente|analisada|erro|descartada_filtro
    # Certame suspenso (marcado pelo time): silencia o alerta de prazo no card
    # até a licitação ser reativada — o prazo antigo deixa de valer.
    suspensa: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    analise: Mapped["Analise | None"] = relationship(back_populates="licitacao", uselist=False)
    oportunidade: Mapped["Oportunidade | None"] = relationship(back_populates="licitacao", uselist=False)


class LicitacaoExcluida(Base):
    """Lápide de licitação excluída pelo time.

    Sem ela, a coleta traria a licitação de volta no próximo ciclo (o PNCP
    devolve tudo dentro do horizonte de 45 dias). A coleta consulta esta tabela
    e pula o que o time excluiu de propósito.
    """

    __tablename__ = "licitacoes_excluidas"
    __table_args__ = (UniqueConstraint("fonte", "id_externo", name="uq_excluida_fonte_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fonte: Mapped[str] = mapped_column(String(30))
    id_externo: Mapped[str] = mapped_column(String(120))
    descricao: Mapped[str] = mapped_column(Text, default="")   # órgão + objeto p/ referência
    excluido_por: Mapped[str] = mapped_column(Text, default="")  # nome do usuário
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Analise(Base):
    """Resultado da análise do edital pela IA."""

    __tablename__ = "analises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    licitacao_id: Mapped[int] = mapped_column(ForeignKey("licitacoes.id"))
    score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100 = maior score (0-10) x 10, p/ compatibilidade
    veredito: Mapped[str] = mapped_column(String(20))       # participar | nao_participar | revisar_manual
    justificativa: Mapped[str] = mapped_column(Text, default="")
    # Análise Prospera Benefícios + Prospera Pagamentos (prompt oficial)
    score_beneficios: Mapped[int] = mapped_column(Integer, default=0)   # 0-10 Prospera Benefícios
    score_pagamentos: Mapped[int] = mapped_column(Integer, default=0)   # 0-10 Prospera Pagamentos
    classificacao_final: Mapped[str] = mapped_column(String(40), default="")  # EXCELENTE OPORTUNIDADE ... NÃO RECOMENDADO
    credenciamento_viavel: Mapped[bool] = mapped_column(Boolean, default=True)
    credenciamento_analise: Mapped[str] = mapped_column(Text, default="")     # Análise Preliminar de Credenciamento
    alertas_impugnacao: Mapped[list | None] = mapped_column(JSON, nullable=True)
    custo_emissao_cartoes: Mapped[str] = mapped_column(Text, default="")  # "X × R$ 5,00 = R$ Y,00" (texto livre da IA)
    analise_completa: Mapped[str] = mapped_column(Text, default="")           # texto integral (tabelas + seções)
    objeto_resumido: Mapped[str] = mapped_column(Text, default="")
    prazos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    exigencias_habilitacao: Mapped[list | None] = mapped_column(JSON, nullable=True)
    exigencias_tecnicas: Mapped[list | None] = mapped_column(JSON, nullable=True)
    atestados_exigidos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    documentos_habilitacao: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{categoria, documento, referencia_edital}]
    riscos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saida: Mapped[int] = mapped_column(Integer, default=0)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    licitacao: Mapped[Licitacao] = relationship(back_populates="analise")


class DocumentoAnexo(Base):
    """Arquivo anexado ao checklist de documentação de uma licitação.

    O conteúdo do arquivo fica DENTRO do SQLite (LargeBinary), por decisão do usuário.
    `item_checklist` guarda o texto do documento do checklist a que o anexo se refere;
    é nullable para permitir anexos avulsos (fora do checklist).
    """

    __tablename__ = "documentos_anexos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    licitacao_id: Mapped[int] = mapped_column(ForeignKey("licitacoes.id"))
    item_checklist: Mapped[str | None] = mapped_column(Text, nullable=True)
    nome_arquivo: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    tamanho: Mapped[int] = mapped_column(Integer, default=0)
    conteudo: Mapped[bytes] = mapped_column(LargeBinary)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Oportunidade(Base):
    """Oportunidade no pipeline do CRM."""

    __tablename__ = "oportunidades"

    ESTAGIOS = [
        "identificada", "em_analise", "impugnacao", "proposta_enviada",
        "disputa", "ganhou", "perdeu_nogo",
    ]

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    licitacao_id: Mapped[int] = mapped_column(ForeignKey("licitacoes.id"))
    estagio: Mapped[str] = mapped_column(String(20), default="identificada")
    notas: Mapped[str] = mapped_column(Text, default="")
    # Text, não String(N): campo de texto livre do usuário — o Postgres impõe o
    # limite que o SQLite ignora (cadastro manual estourava 500 em produção)
    responsavel: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    licitacao: Mapped[Licitacao] = relationship(back_populates="oportunidade")


class ExecucaoPipeline(Base):
    """Registro de cada execução do pipeline (coleta + análise), por qualquer gatilho.

    Alimenta o status "última coleta / próxima estimada" exibido no cabeçalho.
    """

    __tablename__ = "execucoes_pipeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    executado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    gatilho: Mapped[str] = mapped_column(String(20), default="manual")  # manual | agendador | cron
    novas_licitacoes: Mapped[int] = mapped_column(Integer, default=0)
    analisadas: Mapped[int] = mapped_column(Integer, default=0)
    oportunidades_criadas: Mapped[int] = mapped_column(Integer, default=0)
    erros: Mapped[int] = mapped_column(Integer, default=0)
    # Avisos da execução (coletores que falharam, cobertura incompleta, IA desativada…).
    # Sem isso, uma coleta que falhou em todas as fontes fica indistinguível de
    # "não havia nada novo" — foi o que motivou a coluna.
    avisos: Mapped[list | None] = mapped_column(JSON)


class PerfilEmpresa(Base):
    """Perfil da empresa usado pela IA para pontuar aderência (registro único, id=1)."""

    __tablename__ = "perfil_empresa"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    descricao: Mapped[str] = mapped_column(Text, default="")
    cnaes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    ufs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    valor_minimo: Mapped[float | None] = mapped_column(Float, nullable=True)
    valor_maximo: Mapped[float | None] = mapped_column(Float, nullable=True)
    palavras_chave: Mapped[list | None] = mapped_column(JSON, nullable=True)
    restricoes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Dados oficiais para documentos gerados pelo CRM (declarações em Word)
    razao_social: Mapped[str] = mapped_column(Text, default="")
    cnpj: Mapped[str] = mapped_column(Text, default="")
    endereco: Mapped[str] = mapped_column(Text, default="")
    cidade_sede: Mapped[str] = mapped_column(Text, default="")   # "Cidade/UF" (linha de data)
    representante_nome: Mapped[str] = mapped_column(Text, default="")
    representante_cargo: Mapped[str] = mapped_column(Text, default="")


PERFIL_PADRAO = {
    "descricao": (
        "Grupo Prospera — duas empresas: PROSPERA BENEFÍCIOS (vale-alimentação/VA, vale-refeição/VR, "
        "benefícios flexíveis e cartões multibenefícios 'No Name', S.A. de capital fechado, arranjo "
        "aberto de pagamento) e PROSPERA PAGAMENTOS (adquirência, maquininhas/POS, gateway, TEF, "
        "conta digital e soluções de pagamento). Participa de licitações públicas nesses segmentos. "
        "Atuação prioritária na região Sul do Brasil."
    ),
    "cnaes": [],
    "ufs": ["RS", "SC", "PR"],
    "valor_minimo": None,
    "valor_maximo": None,
    "palavras_chave": [
        "vale refeição", "vale-refeição", "vale alimentação", "vale-alimentação",
        "auxílio alimentação", "auxílio-alimentação", "vale transporte", "vale-transporte",
        "cartão alimentação", "cartão refeição", "cartão benefício", "multibenefícios",
        "benefícios corporativos", "ticket alimentação", "ticket refeição",
    ],
    "restricoes": [],
    "razao_social": "",
    "cnpj": "",
    "endereco": "",
    "cidade_sede": "",
    "representante_nome": "Dario",
    "representante_cargo": "CEO — Prospera Benefícios",
}
