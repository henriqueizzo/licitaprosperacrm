# LicitaProsperaCRM — Documentação Técnica

> Documento de onboarding para desenvolvedores. Cobre o contexto de negócio, a visão
> do produto e a documentação técnica completa do sistema (arquitetura, dados, código,
> deploy e operação), com as lições aprendidas e sugestões de evolução.
>
> Última atualização: 2026-07-20 · Produção: https://licitaprosperacrm.onrender.com

---

## 1. O projeto — Prospera Benefícios

O **Grupo Prospera** atua em dois segmentos, com duas empresas:

| Empresa | O que vende | Características relevantes |
|---|---|---|
| **Prospera Benefícios** | Vale-alimentação (VA), vale-refeição (VR), benefícios flexíveis, cartões multibenefícios | S.A. de capital fechado; cartões **"No Name"** (sem nome do portador no plástico); **arranjo aberto** de pagamento (bandeiras Visa/Mastercard) |
| **Prospera Pagamentos** | Adquirência, maquininhas (POS), gateway, TEF, conta digital | Concorre com Cielo, Stone, PagSeguro etc. |

Um dos canais comerciais do grupo é a **venda para o setor público via licitações**:
prefeituras e órgãos contratam fornecimento e gestão de vale-alimentação para seus
servidores (pregões eletrônicos, credenciamentos, concorrências — Lei 14.133/2021).
A atuação prioritária é a **região Sul (RS, SC, PR)**, mas certames aderentes de
outras UFs também interessam.

O problema que motivou o sistema: acompanhar licitações manualmente é inviável —
são centenas de publicações por dia espalhadas em vários portais, os editais têm
dezenas de páginas, e detalhes jurídicos específicos do setor **inviabilizam ou
viabilizam** a participação (exigência de nome do portador no cartão elimina o
modelo No Name; certame exclusivo para ME/EPP elimina uma S.A.; taxa negativa e
modelo pós-pago são passíveis de impugnação pela legislação do PAT).

## 2. O sistema — visão de produto

O **LicitaProsperaCRM** é um CRM completo do funil de licitações:

1. **Coleta automática** de licitações públicas (PNCP + murais do Sistema S), a cada
   6 horas, filtrando por palavras-chave e UFs do perfil da empresa.
2. **Análise dos editais por IA** com um prompt oficial da diretoria: cada edital é
   lido na íntegra (incluindo termo de referência e anexos) e a IA produz uma análise
   estratégica com score 0–10 para cada empresa do grupo, classificação final,
   viabilidade de credenciamento, alertas de impugnação e o **checklist de documentos
   de habilitação**.
3. **Pipeline kanban** (estilo CRM): toda licitação coletada vira um card, que o time
   arrasta pelos estágios `identificada → em análise → impugnação → proposta enviada →
   disputa → ganhou / perdeu-nogo`.
4. **Gestão de documentação**: o checklist extraído pela IA vira uma lista operacional
   onde o time anexa os arquivos (certidões, declarações etc.); declarações podem ser
   geradas em Word pela IA com os dados oficiais da empresa.
5. **Cadastro manual + importação de análise por PDF**: licitações fora dos coletores
   entram pelo cadastro manual (com preenchimento automático por IA a partir de resumo,
   link ou PDF); um relatório de análise em PDF pode ser anexado a qualquer card para
   preencher a análise e completar campos vazios.
6. **Dashboard executivo, controle de usuários e auditoria de uso** (horas de uso por
   dia por funcionário, eventos por tipo).

Usuários: time comercial/licitações da Prospera (~3–5 pessoas), com papéis
admin/comum. O sistema roda 24/7 na nuvem (custo atual: R$ 0 — free tiers).

---

## 3. Documentação técnica

### 3.1 Arquitetura geral

```
                       ┌─────────────────────────────────────────────┐
                       │                RENDER (free)                │
  cron-job.org ──────► │  FastAPI (uvicorn)                          │
  (coleta 6/6h,        │  ├── /api/*  (JSON, sessão por cookie)      │ ◄──── Navegador
   keep-alive 10min)   │  ├── SPA React (build Vite servido pelo     │       (SPA React)
                       │  │    próprio FastAPI — same-origin)        │
                       │  └── APScheduler (coleta agendada in-proc)  │
                       └───────┬──────────────┬──────────────────────┘
                               │              │
                    ┌──────────▼───┐   ┌──────▼───────────────────────┐
                    │  Supabase    │   │  Fontes externas             │
                    │  Postgres    │   │  ├── PNCP (API pública)      │
                    │  (dados)     │   │  ├── FIESC/FIERGS/FIEMS      │
                    └──────────────┘   │  │    (Paradigma WBC)        │
                                       │  ├── ConLicitação (esqueleto)│
                                       │  └── IA: Gemini (free) ou    │
                                       │       Claude API             │
                                       └──────────────────────────────┘
```

- **Monólito de um serviço só**: o FastAPI serve a API e o build do frontend
  (`frontend/dist`) — cookie de sessão fica same-origin, sem CORS em produção.
- **Banco**: Postgres (Supabase) em produção; SQLite local em desenvolvimento.
  O código é dialect-aware (mesmas migrações rodam nos dois).
- **IA plugável**: fábrica escolhe Gemini (gratuito) ou Claude conforme env vars.

### 3.2 Stack

| Camada | Tecnologia | Versão/observação |
|---|---|---|
| Backend | Python 3.12 + FastAPI + Uvicorn | `fastapi>=0.115` |
| ORM | SQLAlchemy 2.x (estilo `Mapped`) | migrações próprias, sem Alembic |
| Validação | Pydantic v2 + pydantic-settings | schemas da IA e payloads |
| Agendador | APScheduler (BackgroundScheduler) | coleta in-process |
| IA | `google-genai` (Gemini) e `anthropic` (Claude) | saída estruturada validada por schema |
| HTTP client | httpx | coletores e downloads |
| Documentos | python-docx | declarações em Word |
| Auth | bcrypt + cookie HttpOnly | sessão opaca, hash SHA-256 no banco |
| Frontend | React 18 + Vite | JavaScript puro (sem TS), sem lib de estado |
| Drag & drop | `@dnd-kit/core` | kanban |
| Banco prod | Supabase Postgres (pooler session, porta 5432) | `psycopg2-binary` |
| Hospedagem | Render free (blueprint `render.yaml`) | deploy automático via push no GitHub |
| Cron externo | cron-job.org | coleta 6/6h + keep-alive 10min |

### 3.3 Estrutura de pastas

```
LicitaProsperaCRM/
├── backend/
│   ├── app/
│   │   ├── main.py               # app FastAPI, lifespan (migrações, scheduler), SPA
│   │   ├── config.py             # Settings (pydantic-settings, lê .env)
│   │   ├── database.py           # engine, SessionLocal, migrar_esquema() idempotente
│   │   ├── models.py             # modelos SQLAlchemy (tabelas)
│   │   ├── security.py           # bcrypt, sessões, bootstrap admin, dependencies
│   │   ├── api/
│   │   │   ├── auth.py           # /api/auth/*, /api/usuarios
│   │   │   └── routes.py         # todas as demais rotas /api/*
│   │   ├── analyzer/
│   │   │   ├── __init__.py       # fábrica criar_analisador() / provedor_ativo()
│   │   │   ├── schemas.py        # ResultadoAnalise, CamposLicitacao, ExtracaoCadastro, ErroCotaIA
│   │   │   ├── prompts.py        # prompt oficial + instruções de saída + prompts de extração
│   │   │   ├── gemini_analyzer.py
│   │   │   └── claude_analyzer.py
│   │   ├── collectors/
│   │   │   ├── base.py           # LicitacaoColetada (dataclass) e contrato dos coletores
│   │   │   ├── pncp.py           # coletor principal (API pública do PNCP)
│   │   │   ├── paradigma_mural.py# base FIESC/FIERGS/FIEMS (Paradigma WBC)
│   │   │   ├── fiesc.py / fiergs.py / fiems.py
│   │   │   ├── conlicitacao.py   # esqueleto (aguardando token da API)
│   │   │   └── bll.py            # não usado (coberto via PNCP)
│   │   └── services/
│   │       ├── pipeline.py       # orquestra coleta → dedupe → oportunidade → análise
│   │       ├── dedupe.py         # detecção de licitações espelhadas
│   │       ├── dashboard.py      # agregações do dashboard executivo
│   │       ├── declaracoes.py    # geração de declarações .docx (IA + template)
│   │       └── atividade.py      # log de uso (eventos, tempo por dia)
│   ├── tests/                    # testes funcionais (rodam com python direto ou pytest)
│   ├── scripts/migrar_para_postgres.py
│   ├── requirements.txt
│   └── .env                      # segredos locais (NUNCA commitar)
├── frontend/
│   ├── src/
│   │   ├── App.jsx               # abas, roteamento simples por estado
│   │   ├── api.js                # wrapper fetch (cookie, 401 global, erros)
│   │   ├── styles.css            # design system inteiro (CSS variables)
│   │   └── components/           # Pipeline, Licitacoes, CadastroManual, Documentacao,
│   │                             # DetalhesLicitacao, Dashboard, Atividade, Usuarios,
│   │                             # Perfil, Login, Janela, Filtros, CampoBusca...
│   └── package.json
├── docs/                         # esta documentação
├── render.yaml                   # blueprint do Render
├── DEPLOY.md                     # guia passo a passo de deploy (escrito para leigos)
└── .claude/skills/design-prospera/SKILL.md  # design system (consultar antes de mudar UI)
```

### 3.4 Configuração (variáveis de ambiente)

Lidas de `backend/.env` local ou das env vars do Render (`config.py`):

| Variável | Default | Uso |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./licitaprospera.db` | `postgres://`/`postgresql://` são normalizados para `postgresql+psycopg2://` automaticamente |
| `GEMINI_API_KEY` | vazio | chave do AI Studio (nível gratuito) |
| `GEMINI_MODEL` | `gemini-flash-latest` | alias que acompanha o flash mais novo |
| `ANTHROPIC_API_KEY` | vazio | chave da API Anthropic |
| `CLAUDE_MODEL` | `claude-opus-4-8` | modelo usado no analisador Claude |
| `IA_PROVIDER` | vazio (auto) | `gemini` \| `anthropic` \| vazio = Gemini se houver chave, senão Claude |
| `COLETA_INTERVALO_HORAS` | 6 | 0 desliga o agendador in-process |
| `ADMIN_EMAIL` / `ADMIN_SENHA_INICIAL` | vazio | bootstrap do 1º admin (só se não houver usuários) |
| `COOKIE_SECURE` | false | **true em produção** (cookie exige HTTPS) |
| `SESSAO_DIAS` | 7 | validade da sessão |
| `CRON_TOKEN` | vazio | habilita `POST /api/pipeline/executar-cron` (vazio = rota desabilitada) |
| `FRONTEND_DIST` | `../frontend/dist` | se existir, o FastAPI serve o SPA |
| `CONLICITACAO_TOKEN` | vazio | auto-ativa o coletor ConLicitação quando chegar |

### 3.5 Modelo de dados

Todas as tabelas são criadas por `Base.metadata.create_all` + `migrar_esquema()`
(ver §3.6). Chaves: SQLite em dev, Postgres em produção.

| Tabela | Propósito | Campos-chave |
|---|---|---|
| `usuarios` | Login (email + bcrypt) | `is_admin`, `ativo`, `ultimo_acesso` (atualizado no máx. 1x/min) |
| `sessoes` | Sessões de login | guarda **apenas o SHA-256** do token (token vai no cookie HttpOnly `sessao`) |
| `licitacoes` | Licitação coletada/cadastrada | `UNIQUE(fonte, id_externo)` é a identidade; `status_analise`: `pendente\|analisada\|erro\|manual`; `suspensa` (marcador, não estágio); `sistema` (plataforma de disputa — BLL, PCP…) e `endereco_licitacao` (link da licitação nessa plataforma; PNCP preenche via `linkSistemaOrigem`/prefixo do objeto, backfill no startup); `raw_json` (payload da fonte) |
| `licitacoes_excluidas` | Lápides de exclusão | sem elas o PNCP recriaria a licitação excluída no ciclo seguinte |
| `analises` | Resultado da análise IA (1 por licitação) | `score_beneficios`/`score_pagamentos` (0–10), `classificacao_final`, `credenciamento_viavel/analise`, `alertas_impugnacao` (JSON), `documentos_habilitacao` (JSON — alimenta o checklist), `analise_completa` (texto integral), `prazos`/`riscos`/`exigencias_*` (JSON), `tokens_entrada/saida` |
| `oportunidades` | Card do kanban (1 por licitação) | `estagio` (ver `Oportunidade.ESTAGIOS`), `notas`, `responsavel` |
| `documentos_anexos` | Arquivos do checklist | conteúdo em `LargeBinary` **dentro do banco** (decisão de produto); `item_checklist` casa com o texto do documento do checklist (NULL = anexo avulso); máx. 25 MB |
| `execucoes_pipeline` | Histórico de cada execução | `gatilho` (`manual\|agendador\|cron`), contadores, `avisos` (JSON — falhas de coletores) |
| `perfil_empresa` | Perfil usado pela IA (registro único id=1) | palavras-chave da coleta, UFs, restrições, dados oficiais p/ declarações |
| `eventos_uso` | Telemetria de uso (aba Atividade) | `tipo` controlado por código; rotas de listagem **não** geram evento |

**Relações**: `Licitacao 1—1 Analise`, `Licitacao 1—1 Oportunidade`,
`Licitacao 1—N DocumentoAnexo`. Exclusão de licitação apaga análise, card e
documentos e grava a lápide (eventos de auditoria são preservados com
`licitacao_id = NULL`).

### 3.6 Migrações (`database.py::migrar_esquema`)

Não usamos Alembic: `migrar_esquema()` roda **em todo startup**, é idempotente e
dialect-aware (introspecção via `sqlalchemy.inspect`). O que ela faz:

- `ALTER TABLE ... ADD COLUMN` para colunas novas que não existam;
- renomeação de estágios legados do kanban (`_RENOMEACOES_ESTAGIOS`);
- backfill de oportunidades (toda licitação sem card ganha um);
- remoção de análises duplicadas (mantém a mais recente por licitação);
- correção de dados corrompidos via `UPDATE` com parâmetro bound;
- `_ALARGAMENTOS`: `ALTER COLUMN ... TYPE Text` (só Postgres) para colunas que
  nasceram `String(N)`;
- liga RLS em toda tabela do schema public (só Postgres — o Supabase expõe uma
  Data API pública e tabelas sem RLS geram alerta; o app não é afetado porque
  conecta como dono das tabelas).

**Regras de ouro (aprendidas em produção):**

1. **Campo de texto livre (usuário ou IA) NUNCA em `String(N)` — sempre `Text`.**
   O SQLite ignora o limite; o Postgres estoura 500 (aconteceu 2x: `custo_emissao_cartoes`
   e `oportunidades.responsavel`).
2. **DDL só com ASCII.** Literal acentuado dentro de `ALTER TABLE` chegou corrompido
   (U+FFFD) ao Postgres de produção. Valores acentuados entram via `UPDATE`
   parametrizado, nunca em DDL.
3. Migração nova deve ser **idempotente** (vai rodar em todo deploy).

### 3.7 Coletores (`app/collectors/`)

Contrato: cada coletor implementa `coletar(ufs, palavras_chave, dias) -> list[LicitacaoColetada]`.
O pipeline persiste com dedupe por `(fonte, id_externo)` + dedupe de espelhadas (§3.9).

**PNCP (`pncp.py`) — fonte principal.** API pública e gratuita do Portal Nacional
de Contratações Públicas (Lei 14.133). Conhecimento operacional acumulado:

- Endpoints: `/v1/contratacoes/proposta` (propostas abertas — principal) e
  `/publicacao` (complemento). Modalidades filtradas: 6 (pregão eletrônico),
  8 (dispensa), 4 (concorrência eletrônica).
- **`dataFinal` no endpoint `/proposta` é o TETO da data de ENCERRAMENTO**, não
  "hoje". Usamos `PROPOSTA_HORIZONTE_DIAS = 45` (dataFinal = hoje+45d). Com
  `dataFinal=hoje` só vem o que encerra no dia — bug que fez o sistema "ver os
  mesmos 17 casos por uma semana" e perder licitações milionárias.
- `tamanhoPagina` máximo real = **50** (100/500 retornam 400).
- O portal é instável: 500 de banco frequentes → retry com backoff; **429 com
  `Retry-After`** respeitado + pausa de 0,6 s entre páginas. Coleta completa leva
  15–30 min por causa disso (roda em background, não importa).
- URLs de download vêm com uma **porta interna inválida** (`pncp.gov.br:57667`)
  que é removida por regex.
- `baixar_documentos(edital_url)` baixa **TODOS os PDFs** da licitação (edital
  primeiro, depois TR e anexos), teto conjunto de 19 MB (limite inline do Gemini);
  falha em um anexo não derruba o conjunto. *Motivo: os documentos de habilitação
  costumam estar nos anexos — baixar só o 1º arquivo fazia a análise perder
  exigências inteiras.*

**Sistema S (`paradigma_mural.py` + `fiesc/fiergs/fiems.py`).** FIESC (SC),
FIERGS (RS) e FIEMS (MS) usam a mesma plataforma Paradigma WBC — web service JSON
`POST {base}/portal/WebService/Servicos.asmx/PesquisarProcessos`. A base é
compartilhada; cada portal é uma subclasse fina com sua URL. Limitação: o mural
não traz município/valor/arquivo do edital (a análise roda só com metadados).

**Bloqueados/decididos:**
- **FIEP (PR)**: Cloudflare JS challenge — se um dia liberar, criar `fiep.py`
  herdando a base com `base_url portaldecompras.sistemafiep.org.br`.
- **Licitações-e (Banco do Brasil)**: inviável — CAPTCHA obrigatório + fingerprint
  TLS (o `curl_cffi` contorna o TLS e está instalado no venv, mas o CAPTCHA não).
- **BLL/BNC/Portal de Compras Públicas/Licitar Digital**: já cobertos via PNCP
  (toda licitação da Lei 14.133 é publicada lá).

**ConLicitação (`conlicitacao.py`)**: esqueleto pronto, auto-ativa com
`CONLICITACAO_TOKEN`. O parse é um chute educado — **validar contra a API real
quando o token do suporte chegar** (a API entrega conforme filtros configurados
no painel do assinante; autenticação por header `x-auth-token`; pedir liberação
dos outbound IPs do Render).

### 3.8 Análise IA (`app/analyzer/`)

**Fábrica multi-provedor** (`__init__.py`): `criar_analisador()` devolve
`AnalisadorEditalGemini` ou `AnalisadorEdital` (Claude) conforme `IA_PROVIDER`/chaves.
Ambos implementam a mesma interface:

| Método | Uso | Retorno |
|---|---|---|
| `analisar(dados, perfil, pdfs)` | análise completa do edital (pipeline) | `(ResultadoAnalise, UsoIA)` |
| `extrair(texto=, pdf_bytes=)` | preenchimento automático do cadastro + importação de análise | `ExtracaoCadastro {campos, analise?}` |
| `redigir(instrucao, system)` | texto corrido (declarações Word) | `str` |

- `analisar` aceita `bytes` **ou `list[bytes]`** (edital + TR + anexos).
- `extrair` reconhece dois tipos de documento: edital comum (só `campos`) ou
  **relatório de análise do time** (estrutura do prompt oficial) — nesse caso
  TRANSCREVE a análise para `analise` (sem re-analisar). É o que alimenta o botão
  "Anexar análise (PDF)" e o cadastro manual.
- Saída estruturada: Pydantic (`ResultadoAnalise` etc.) validado pelo provedor
  (`response_schema` no Gemini; `messages.parse` no Claude).
- `ErroCotaIA`: exceção de semântica especial — saldo/cota esgotada. O pipeline
  **interrompe o lote sem marcar "erro"** (licitações continuam pendentes para o
  próximo ciclo) e o cabeçalho acende o LED âmbar.

**Prompt** (`prompts.py`): `PROMPT_OFICIAL` é o prompt da diretoria (não alterar
sem alinhamento) + `INSTRUCOES_SAIDA_ESTRUTURADA` (nossa camada de integração).
Pontos críticos verificados pela IA: personalização do cartão (No Name), regime
societário (S.A.), arranjo de pagamento, taxa negativa, pré/pós-pago. O checklist
`documentos_habilitacao` é tratado como **lista operacional de envio** — o prompt
manda varrer subitem por subitem em todos os documentos e reler antes de responder.

**Gemini (produção)** — nível gratuito do AI Studio:
- Modelos: `gemini-flash-latest` com fallback `gemini-flash-lite-latest` (o alias
  `-latest` evita "model no longer available"; versões fixas somem para contas novas).
- Retry: 429 com esperas [30, 60]s; 5xx com [15, 45]s; **chamadas interativas
  (extrair/redigir) usam esperas curtas de 8 s** — o proxy do Render corta requisições
  em ~100 s e retry longo faz o usuário clicar de novo (já causou gravação duplicada).
- **Cota gratuita: ~20 requisições/DIA por modelo.** Ao esgotar (429 persistente),
  o código tenta o próximo modelo da lista (cota separada) antes de levantar
  `ErroCotaIA`.
- Limites de saída: análise 32k tokens, extração 32k (o *thinking* do Gemini
  consome o mesmo orçamento — 16k truncava o JSON da transcrição integral).
- PDFs inline até ~19 MB por requisição.

**Claude (alternativa paga)**: `claude-opus-4-8`, `messages.parse` com thinking
adaptativo, system prompt com `cache_control` (prefixo cacheado entre análises).
`max_tokens` 16k (teto prático para chamadas não-streaming). Custo medido por
análise (~104k tokens de entrada com PDFs grandes): Opus ~US$ 0,64 · Sonnet
~US$ 0,25 · Haiku ~US$ 0,13.

### 3.9 Pipeline (`services/pipeline.py`) e dedupe (`services/dedupe.py`)

`executar_pipeline(db, dias, limite_analises, gatilho)`:

1. **Coleta** de todos os coletores ativos; falhas individuais viram `avisos`
   (persistidos em `execucoes_pipeline` e exibidos no LED âmbar do cabeçalho).
2. **Dedupe** por `(fonte, id_externo)` + lápides + espelhadas (abaixo).
3. **Toda licitação nova vira Oportunidade** no estágio `identificada` (não existe
   gate por score — decisão de produto: humano decide arrastando para `perdeu_nogo`).
4. **Análise IA** das pendentes (`status_analise='pendente'`, fonte != manual),
   até `limite_analises=10` por execução (backlog grande precisa de vários ciclos).
   `ErroCotaIA` interrompe o lote sem queimar as pendentes.

**Regra de fonte da análise** (cascata, em `executar_analises` + `_fonte_pelo_link`):
1. **Tem documento?** → analisa os **PDFs** (edital + TR + anexos);
2. **Não tem?** → considera o **link do certame**: se o link apontar direto para um
   PDF, ele vira o documento; se for página, o HTML vira texto; os dados brutos da
   coleta (`raw_json`) complementam (páginas de portal costumam ser apps JS);
3. Sem nenhum dos dois → análise só com metadados (a IA sinaliza a limitação).

Gatilhos: botão na UI (`manual`), APScheduler in-process (`agendador`, ~2 min após
o startup e depois a cada 6 h) e cron externo (`cron`, via `POST
/api/pipeline/executar-cron` com header `X-Cron-Token` — responde 202 e roda em
`BackgroundTasks`).

**Dedupe de espelhadas** (`dedupe.py`): o mesmo pregão publicado por duas
plataformas ganha `numeroControlePNCP` diferentes. Regra conservadora: mesmo CNPJ
do órgão (extraído do id_externo; fallback órgão+município+UF) **+** mesmo valor
ao centavo **+** mesma data de encerramento **+** objeto equivalente (prefixo
"[Plataforma]" removido, `difflib` ≥ 0.85). Sem valor/data **nunca** deduplica.
No startup, espelhos são apagados mantendo o mais trabalhado (estágio > docs >
mexido > análise > mais antigo); grupo com mais de um card trabalhado por humano é
pulado com warning. Na coleta, espelho novo é ignorado.

### 3.10 API (rotas)

Autenticação: cookie `sessao` (HttpOnly). Tudo em `/api/*` exige sessão válida,
**exceto** `POST /api/auth/login`, `GET /api/saude` e `POST /api/pipeline/executar-cron`
(token próprio). Rotas `admin/*` e `/api/usuarios` exigem `is_admin`.

| Rota | Método | Descrição |
|---|---|---|
| `/api/saude` | GET | público: `{ok, ia_provider, commit}` — o `commit` (RENDER_GIT_COMMIT) confirma deploy backend-only |
| `/api/auth/login` · `logout` · `me` · `trocar-senha` | POST/GET | sessão |
| `/api/usuarios` (GET/POST) · `/api/usuarios/{id}` (PATCH) | — | gestão de usuários (admin) |
| `/api/pipeline/executar` · `coletar` · `analisar` | POST | dispara pipeline/etapas |
| `/api/pipeline/executar-cron` | POST | idem, para cron externo (X-Cron-Token, 202 + background) |
| `/api/pipeline/status` | GET | última execução, próxima estimada, avisos, histórico (20) |
| `/api/licitacoes` | GET | listagem (filtros `status`, `uf`, `limite`) |
| `/api/licitacoes` | POST | **cadastro manual** — sempre vira oportunidade; aceita `analise` (ResultadoAnalise) transcrita p/ gravar junto |
| `/api/licitacoes/extrair` | POST | preenchimento automático a partir de resumo/link (HTML→texto; PDF→IA) |
| `/api/licitacoes/extrair-arquivo` | POST | idem a partir de PDF anexado (multipart, ≤19 MB) |
| `/api/licitacoes/{id}/analise-arquivo` | POST | **importa relatório de análise (PDF) para card existente** — grava análise + completa campos vazios (nunca sobrescreve); 422 se o PDF não for relatório |
| `/api/licitacoes/{id}` | GET/PATCH/DELETE | detalhe · edição de campos (auditada) · exclusão com lápide |
| `/api/licitacoes/{id}/reanalisar` | POST | reanálise IA (existe no backend; **removida da UI** por risco de sobrecarga) |
| `/api/licitacoes/{id}/documentos` | GET/POST | checklist com anexos por item · upload (multipart, ≤25 MB) |
| `/api/documentos/{id}/download` · DELETE | — | download/remoção de anexo |
| `/api/licitacoes/{id}/declaracoes` | POST | gera declaração .docx (IA com fallback template; header `X-Texto-Origem: ia\|modelo`) |
| `/api/oportunidades` (GET) · `/{id}` (PATCH) | — | kanban: estágio, notas, responsável |
| `/api/perfil` | GET/PUT | perfil da empresa (parâmetros da coleta/análise + dados p/ documentos) |
| `/api/dashboard?dias=` | GET | KPIs, funil, coletas/dia, distribuições, vencimentos ≤14d |
| `/api/admin/atividade` · `/eventos` | GET | resumo por usuário (com `uso_por_dia`) e eventos (admin) |

Convenções úteis para quem for mexer:
- Serializadores centralizados em `routes.py` (`_licitacao_out`, `_analise_out`,
  `_docs_progresso`). A análise é buscada com `order_by(id.desc()).first()` — uma
  duplicata acidental **não pode** derrubar a listagem (lição de produção).
- Eventos de auditoria (`registrar_evento`) são "melhor esforço": nunca propagam
  erro para a rota principal.
- Truncamento defensivo nos campos `String(N)` em toda escrita vinda de usuário/IA.

### 3.11 Autenticação e segurança

- Senhas com **bcrypt**; troca de senha revoga as outras sessões do usuário.
- Sessão: token opaco `secrets.token_urlsafe(32)` no cookie **HttpOnly** `sessao`
  (Secure em produção); no banco fica só o SHA-256; validade 7 dias; sessões
  expiradas são varridas no login.
- Bootstrap: primeiro admin criado do `.env` **apenas** se não houver usuários.
- RLS ligado em todas as tabelas no Supabase (a Data API pública do Supabase
  exporia as tabelas sem isso).
- O cookie é same-origin porque o FastAPI serve o SPA — sem CORS em produção
  (CORS liberado apenas para `localhost:5173` em dev).

### 3.12 Frontend (`frontend/src/`)

React 18 + Vite, JavaScript puro, **sem** lib de estado/rotas — o estado vive nos
componentes e a navegação é por abas em `App.jsx`. Padrões:

- `api.js`: wrapper de `fetch` — cookie same-origin, tratamento global de 401
  (volta ao login), extração de `detail` das mensagens de erro.
- **Design system em `styles.css`** com CSS variables — tema claro, azul `#2563EB`,
  fonte Inter, cartões raio 16px com borda slate-200, badges pastel. **Antes de
  qualquer mudança visual, consulte `.claude/skills/design-prospera/SKILL.md`**.
- Componentes principais:
  - `Pipeline.jsx` — kanban (colunas com rolagem própria, drag & drop via dnd-kit
    com `DragOverlay`, MouseSensor distance 6px p/ separar clique de arraste,
    TouchSensor delay 250ms), cockpit de indicadores, filtros e busca sem acento.
  - `Cartao`/`CartaoVisual` — card compacto: faixa de cor pela classificação da IA,
    contagem regressiva de vencimento (amarelo ≤14d, vermelho ≤7d, selo "Vencida"),
    chip do responsável, progresso `docs 3/8`, selo "Suspensa".
  - `DetalhesLicitacao.jsx` — modal/linha expandida com a análise completa e ações:
    suspender/reativar, editar campos, **anexar análise (PDF)**, excluir. Reutilizado
    pelo kanban e pela aba Licitações (DRY).
  - `Documentacao.jsx` — checklist por categoria, upload por item + avulsos,
    gerar declaração Word, anexar análise quando não há checklist.
  - `CadastroManual.jsx` — form + preenchimento automático (resumo/link/PDF) com
    prévia da análise importada.
  - `Dashboard.jsx`, `Atividade.jsx` (horas de uso por dia), `Usuarios.jsx`,
    `Perfil.jsx`, `Janela.jsx` (modal reutilizável com minimizar/maximizar).
- Busca/filtros são client-side (helpers em `Filtros.jsx`), sem acento
  (`normalizar`).

### 3.13 Deploy e operação

**Fluxo de trabalho**: push no `master` do GitHub (`henriqueizzo/licitaprosperacrm`)
→ Render builda (`render.yaml`: pip install + npm ci + npm run build) e publica.
Confirmação de deploy: frontend pelo hash dos assets, backend pelo campo `commit`
de `GET /api/saude`.

**Render free — comportamentos que você PRECISA conhecer:**

| Sintoma | Causa | Mitigação em vigor |
|---|---|---|
| "Tela preta"/página de loading do Render | Serviço hibernou (free tier dorme após inatividade) | job keep-alive no cron-job.org (GET / a cada 10 min; 744h/mês cabem nas 750h free) |
| Coletas falhando com Bad Gateway | Chamada chegou durante hibernação/instabilidade | timeout do job de coleta 60s + notificação por e-mail |
| Keep-alive parou sozinho | cron-job.org **desativa** jobs após falhas consecutivas | notificações onFailure/onDisable ligadas (avisa por e-mail) |
| Requisição interativa morre em ~100s | Proxy do Render corta requests longas | chamadas interativas de IA usam retries curtos; pipeline (background) usa retries longos |
| Deploy "se perde" (push sem publicar) | Evento do Render não dispara às vezes | commit vazio (`git commit --allow-empty`) força novo deploy |
| 500 intermitente após deploy | Requisição durante o swap | aguardar 1–2 min; conferir `/api/saude` |

**Supabase Postgres**: pooler em modo session (`aws-1-us-east-2.pooler.supabase.com:5432`),
usuário `postgres.<ref>`; senha com `@` precisa ser URL-encoded (`%40`);
`pool_pre_ping` ligado. Migração SQLite→Postgres: `backend/scripts/migrar_para_postgres.py`
(aborta se o destino não estiver vazio).

**cron-job.org**: job "Coleta LicitaProspera" (0/6/12/18h BRT, POST executar-cron
com X-Cron-Token, timeout 60 s) e job "Manter LicitaProspera acordado" (10 min).
Ambos com notificação de falha por e-mail. Gerenciáveis via API com a chave do
usuário.

**Custo atual**: R$ 0 (Render free + Supabase free + Gemini free + cron-job.org).
Limitações correspondentes: hibernação, 512 MB RAM, ~20 análises/dia por modelo
Gemini. Ver sugestões (§3.16).

### 3.14 Desenvolvimento local

```powershell
# Backend (Windows)
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
# criar .env (copiar .env.example) com as chaves
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# Frontend (dev server com proxy — cookie funciona via same-origin no Vite)
cd frontend
npm ci
npm run dev        # http://localhost:5173

# Build de produção (o FastAPI serve o dist se existir)
npm run build
```

- Banco local: SQLite `backend/licitaprospera.db` (produção usa Postgres — os
  dados NÃO são os mesmos).
- **Servidores em janelas independentes** (`Start-Process` no PowerShell) — jobs
  em background de shell caem quando a sessão fecha.
- **Atenção: dev e produção compartilham a mesma chave Gemini** — testes locais
  consomem a cota diária de produção.

**Testes** (`backend/tests/` — rodam com `python tests\arquivo.py` ou pytest):

| Arquivo | Cobre |
|---|---|
| `test_auth.py` | login, sessões, troca de senha, gestão de usuários, permissões |
| `test_dashboard.py` | payload completo do dashboard |
| `test_cadastro_analise.py` | cadastro manual com/sem análise, análise inválida, importação por PDF (IA mockada), resiliência a análise duplicada |

Padrão dos testes: banco SQLite em memória (`StaticPool`) + `dependency_overrides`
de `get_db` + `TestClient`; IA sempre mockada (nenhum teste consome cota).

### 3.15 Regras e lições do projeto (leia antes de codar)

1. **`Text` para texto livre**, nunca `String(N)` (§3.6).
2. **DDL só ASCII**; valores com acento via UPDATE parametrizado (§3.6).
3. **Chamada interativa de IA = retries curtos** (proxy do Render corta em ~100s);
   retries longos só em background (pipeline).
4. **Busca de análise por licitação usa `first()`**, não `scalar_one_or_none()` —
   duplicata não pode derrubar a API.
5. **Migração/limpeza idempotente no startup** é o mecanismo padrão de consertar
   dados de produção.
6. **Cadastro manual não passa pela análise IA automática** (regra de negócio);
   análise entra por importação de PDF.
7. **Toda licitação coletada vira card** — não recriar gates por score.
8. Exclusão de licitação **precisa** da lápide, senão a coleta recria.
9. PNCP: horizonte de 45 dias em `dataFinal`, página máx. 50, retry em 429/500 (§3.7).
9b. **Fonte da análise: tem documento → PDF; não tem → link do certame** (§3.9).
10. O prompt oficial (`PROMPT_OFICIAL`) é da diretoria — mudanças só na camada
    `INSTRUCOES_SAIDA_ESTRUTURADA`.
11. Design: consultar a skill `design-prospera` antes de mudar UI.
12. Commits: mensagens sem acento (histórico em ASCII por causa do PowerShell 5.1).

### 3.16 Sugestões de evolução (backlog técnico)

**Infra/operação**
- **Render Starter (US$ 7/mês)**: elimina hibernação, keep-alive e boa parte da
  fragilidade operacional. Recomendado se o uso virar diário.
- **Chave Gemini separada para produção** (ou tier pago / voltar ao Claude com
  créditos): hoje dev e produção dividem ~20 análises/dia por modelo.
- Monitoramento de erros (Sentry free tier) — hoje o diagnóstico é por probes
  externos e reprodução local.
- Backup automatizado do Postgres (Supabase faz snapshot, mas exportação períodica
  externa é barata e prudente) — atenção especial aos anexos em `LargeBinary`.

**Arquitetura/código**
- **Alembic** para migrações versionadas quando o time crescer (o `migrar_esquema`
  atual funciona bem, mas não tem histórico nem rollback).
- Mover anexos de `LargeBinary` para storage de objetos (Supabase Storage/S3) se o
  volume crescer — banco com BLOBs encarece backup e migração.
- CI (GitHub Actions): rodar os testes + build do frontend em cada push (hoje os
  testes rodam localmente antes do push).
- Paginação real em `/api/licitacoes` (hoje `limite=100` e filtros client-side —
  ok para o volume atual, não escala para milhares).
- Rate limiting nas rotas de IA (evitar duplo clique/abuso de cota).
- TypeScript no frontend se o time de devs preferir (hoje JS puro).

**Produto/coleta**
- Integração ConLicitação (aguardando token — esqueleto pronto, validar parse e
  conferir se a API traz valor+data para o dedupe de espelhadas).
- Detecção automática de suspensão pelo campo de situação do PNCP na coleta.
- Kanban: envelhecimento do card (dias parado no estágio), ordenação por vencimento,
  colunas Ganhou/Perdeu recolhidas.
- Notificações (e-mail/WhatsApp) para vencimentos próximos e licitações novas de
  alta aderência.

---

*Dúvidas sobre decisões históricas: o `git log` tem mensagens detalhadas por
feature, e `DEPLOY.md` cobre o passo a passo de infraestrutura do zero.*
