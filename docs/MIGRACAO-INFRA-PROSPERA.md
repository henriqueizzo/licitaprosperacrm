# Migração para a infraestrutura da Prospera (AWS)

> Guia para o time de infra/DevOps migrar o LicitaProsperaCRM da stack atual
> (Render free + Supabase + cron-job.org + GitHub) para a infraestrutura da
> Prospera (EC2 + PostgreSQL na AWS + Bitbucket Pipelines).
>
> Leia junto com `docs/DOCUMENTACAO-TECNICA.md` (arquitetura e código) e
> `DEPLOY.md` (como a stack atual foi montada).
> Última atualização: 2026-07-21.

## De → Para

| Peça | Hoje | Destino |
|---|---|---|
| Backend + frontend | Render free (1 web service; FastAPI serve o SPA) | **EC2** (mesmo modelo: um serviço só) |
| Banco | Supabase Postgres (pooler session :5432) | **PostgreSQL na AWS** (RDS) |
| Repositório | GitHub `henriqueizzo/licitaprosperacrm` | **Bitbucket** (espelho e depois principal) |
| Deploy | Push no GitHub → build automático do Render | **Bitbucket Pipelines** → script de deploy na AWS |
| Agendamento | cron-job.org (coleta 6/6h + keep-alive 10min) | **Desnecessário** — scheduler interno basta (ver §5) |
| TLS/domínio | `*.onrender.com` (TLS do Render) | A definir: ALB + ACM **ou** nginx + certbot |

**Ganhos imediatos da migração:** sem hibernação (fim do keep-alive e das falhas
de coleta por Bad Gateway), sem o corte de ~100s do proxy do Render, IP de saída
fixo possível (necessário para a API da ConLicitação), recursos dedicados.

---

## 1. Contrato de runtime (o que a aplicação precisa)

- **Python 3.12** (produção) e **Node 20** (só no build do frontend).
- Build:
  ```bash
  pip install -r backend/requirements.txt
  cd frontend && npm ci && npm run build     # gera frontend/dist
  ```
- Start (a partir de `backend/`):
  ```bash
  uvicorn app.main:app --host 0.0.0.0 --port 8000
  ```
- **⚠ UMA instância, UM worker.** Não usar `--workers N` nem múltiplas instâncias:
  1. o **APScheduler** roda dentro do processo (N workers = N coletas em paralelo);
  2. os **jobs de extração por PDF** (`_JOBS` em `routes.py`) ficam em memória —
     o polling precisa cair no mesmo processo que iniciou o job.
  Escalar = subir o tamanho da EC2 (vertical). Se um dia precisar de horizontal,
  esses dois pontos têm de ir para o banco/fila primeiro.
- **Sem estado em disco**: os anexos de documentação são BLOB no banco; nenhum
  volume/persistência local é necessário. Logs vão para stdout (journald/CloudWatch).
- **Healthcheck**: `GET /api/saude` → `{ok, ia_provider, commit}` (público, sem auth).
  O `commit` vem de `RENDER_GIT_COMMIT` **ou `APP_COMMIT`** — a pipeline deve
  exportar `APP_COMMIT=$BITBUCKET_COMMIT` para o processo (ver §6).
- No primeiro boot a aplicação **se automigra**: cria tabelas, aplica
  `migrar_esquema()` (idempotente), backfills e dedupes. Nada de Alembic.
- Dimensionamento sugerido: **t3.small (2 vCPU / 2 GB)**. t3.micro (1 GB) é
  arriscado: análise de editais carrega até ~19 MB de PDFs em memória + base64.

### Variáveis de ambiente

| Variável | Obrigatória | Valor na infra Prospera |
|---|---|---|
| `DATABASE_URL` | ✅ | `postgresql://usuario:senha@host-rds:5432/licitaprospera` (o app normaliza o driver; senha com `@` → URL-encode `%40`) |
| `GEMINI_API_KEY` | ✅ (ou Anthropic) | chave do Gemini — **recomenda-se chave nova, só de produção** |
| `ANTHROPIC_API_KEY` | opcional | alternativa paga ao Gemini |
| `IA_PROVIDER` | opcional | vazio = auto (Gemini se houver chave) |
| `COOKIE_SECURE` | ✅ | `true` (exige HTTPS na frente) |
| `COLETA_INTERVALO_HORAS` | ✅ | `6` (scheduler interno; `0` desliga) |
| `ADMIN_EMAIL` / `ADMIN_SENHA_INICIAL` | só 1º boot em banco vazio | irrelevante ao migrar dados (usuários já existem) |
| `CRON_TOKEN` | opcional | só se optar por EventBridge (§5); vazio desabilita a rota |
| `FRONTEND_DIST` | opcional | default `../frontend/dist` já serve |
| `APP_COMMIT` | recomendado | setar na pipeline: `$BITBUCKET_COMMIT` |
| `CONLICITACAO_TOKEN` | futuro | quando o suporte da ConLicitação liberar (lembrar de cadastrar o IP de saída da EC2 lá) |

Segredos: usar o padrão da Prospera (SSM Parameter Store / Secrets Manager /
variáveis secured do Bitbucket). Nunca commitar `.env`.

---

## 2. Banco de dados (RDS PostgreSQL)

- Versão: PostgreSQL **14+** (produção atual roda em 15 no Supabase; qualquer 14/15/16 serve).
- Charset UTF-8; timezone irrelevante (o app trabalha em UTC e converte no código).
- Tamanho: hoje o banco é pequeno (dezenas de MB), mas os **anexos são BLOB** na
  tabela `documentos_anexos` (até 25 MB por arquivo) — provisionar armazenamento
  com folga e monitorar crescimento.
- `RLS` (row-level security) foi ligado no Supabase por causa da Data API pública
  deles; no RDS é inócuo — o startup continua aplicando sem efeito colateral.

### Migração dos dados (Supabase → RDS)

Método recomendado — dump/restore nativo (preserva tudo, inclusive BLOBs):

```bash
# 1) Congelar escrita: parar o serviço no Render (ou avisar o time p/ não usar)
# 2) Dump do Supabase (connection string atual de produção)
pg_dump "postgresql://postgres.fxquayfpoauimomoldld:SENHA@aws-1-us-east-2.pooler.supabase.com:5432/postgres" \
  --no-owner --no-privileges -Fc -f licitaprospera.dump

# 3) Restore no RDS (banco vazio criado antes)
pg_restore -d "postgresql://usuario:senha@host-rds:5432/licitaprospera" \
  --no-owner --no-privileges licitaprospera.dump
```

- `--no-owner --no-privileges`: os owners/grants do Supabase não existem no RDS.
- Alternativa (se preferir mexer menos com pg_tools): subir o app apontando para
  o RDS vazio (ele cria o schema) e usar `backend/scripts/migrar_para_postgres.py`
  adaptando origem/destino — mas o pg_dump é mais simples e completo.
- Validar depois do restore: contagens de `licitacoes`, `analises`,
  `oportunidades`, `documentos_anexos`, `usuarios` iguais às da origem.

### Backup contínuo (destino)

- **Snapshots automáticos do RDS** (retenção ≥ 7 dias) + snapshot manual antes de
  qualquer mudança grande.
- `pg_dump -Fc` agendado (diário) para S3 — cobre erro lógico (DELETE errado),
  que snapshot pontual não resolve sozinho.

---

## 3. EC2 — duas opções de empacotamento

> Decidir conforme o padrão da Prospera (pergunta em aberto, §8). As duas opções
> abaixo estão completas; a aplicação não exige nada além disso.

### Opção A — systemd + nginx (simples, sem Docker)

`/etc/systemd/system/licitaprospera.service`:

```ini
[Unit]
Description=LicitaProsperaCRM (FastAPI)
After=network.target

[Service]
User=app
WorkingDirectory=/opt/licitaprospera/backend
EnvironmentFile=/opt/licitaprospera/.env
ExecStart=/opt/licitaprospera/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

nginx (terminação TLS com certbot, ou atrás de ALB):

```nginx
server {
    server_name licitacoes.prospera.interno;  # definir domínio
    client_max_body_size 30m;      # uploads de PDF/anexos (limites do app: 19/25 MB)
    proxy_read_timeout 300s;       # análises interativas não sofrerem timeout do proxy

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Opção B — Docker

`Dockerfile` (multi-stage — build do frontend + runtime Python):

```dockerfile
FROM node:20-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY --from=frontend /src/frontend/dist /app/frontend/dist
ENV FRONTEND_DIST=../frontend/dist
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Rodar com `--restart always`, env vars injetadas (SSM/compose), e o proxy/ALB na
frente com os mesmos timeouts da opção A. **Sempre 1 container** (ver §1).

### Rede/segurança

- Security group: 443/80 públicos (ou só rede interna, a decidir), 22 restrito.
- **Elastic IP** na EC2 (ou NAT com IP fixo): a API da ConLicitação libera acesso
  por IP — o IP de saída precisa ser estável para cadastrá-lo lá.
- `COOKIE_SECURE=true` exige que o usuário sempre acesse por HTTPS.

---

## 4. Comportamentos que MUDAM com a saída do Render

| Item | Situação | Ação na migração |
|---|---|---|
| Keep-alive (cron-job.org, job 8062170) | Existia só porque o Render free hiberna | **Desativar/apagar** |
| Job de coleta (cron-job.org, job 8043538) | Chamava `POST /api/pipeline/executar-cron` 6/6h | **Desativar** — na EC2 o APScheduler interno cobre (ver §5) |
| Corte de ~100s do proxy | Motivou as rotas assíncronas de PDF e retries curtos | Manter como está (funciona ainda melhor sem o corte); configurar `proxy_read_timeout 300s` no nginx/ALB |
| `RENDER_GIT_COMMIT` no `/api/saude` | Setado pelo Render | Pipeline exporta `APP_COMMIT=$BITBUCKET_COMMIT` |
| `render.yaml` / `DEPLOY.md` | Blueprint da stack antiga | Ficam no repo como histórico; marcar como obsoletos quando a migração concluir |

## 5. Agendamento da coleta

Com a EC2 sempre de pé, **o agendador interno já resolve**: `COLETA_INTERVALO_HORAS=6`
faz a coleta rodar ~2 min após o boot e a cada 6 h dentro do próprio processo.
Nenhum cron externo é necessário.

Alternativa gerenciada (se a Prospera preferir observabilidade fora do app):
Amazon EventBridge Scheduler → `POST https://<host>/api/pipeline/executar-cron`
com header `X-Cron-Token: <CRON_TOKEN>` (rota responde 202 e processa em
background). Nesse caso, pode-se rodar com `COLETA_INTERVALO_HORAS=0`.

## 6. Bitbucket + pipeline de deploy

### Espelhar o repositório (GitHub → Bitbucket)

```bash
git clone --mirror https://github.com/henriqueizzo/licitaprosperacrm.git
cd licitaprosperacrm.git
git push --mirror https://bitbucket.org/<workspace>/licitaprosperacrm.git
```

Depois da migração, o Bitbucket vira o principal (o GitHub pode ficar como
espelho de segurança ou ser arquivado — decisão do time).

### Exemplo de `bitbucket-pipelines.yml`

Modelo com deploy por SSH (rsync + restart systemd). Adaptar ao padrão de
scripts/CodeDeploy da Prospera — os passos de build e teste são o contrato:

```yaml
image: python:3.12

pipelines:
  branches:
    master:
      - step:
          name: Testes backend
          caches: [pip]
          script:
            - pip install -r backend/requirements.txt
            - cd backend
            - python tests/test_auth.py
            - python tests/test_dashboard.py
            - python tests/test_cadastro_analise.py
      - step:
          name: Build frontend
          image: node:20
          caches: [node]
          script:
            - cd frontend && npm ci && npm run build
          artifacts:
            - frontend/dist/**
      - step:
          name: Deploy EC2
          deployment: production
          script:
            # Variáveis secured no Bitbucket: DEPLOY_HOST, DEPLOY_USER, chave SSH
            - pipe: atlassian/rsync-deploy:0.12.0
              variables:
                USER: $DEPLOY_USER
                SERVER: $DEPLOY_HOST
                REMOTE_PATH: /opt/licitaprospera
                LOCAL_PATH: '.'
                EXTRA_ARGS: '--exclude .git --exclude backend/.venv --exclude node_modules'
            - ssh $DEPLOY_USER@$DEPLOY_HOST "
                cd /opt/licitaprospera/backend &&
                /opt/licitaprospera/.venv/bin/pip install -r requirements.txt &&
                echo APP_COMMIT=$BITBUCKET_COMMIT | sudo tee /opt/licitaprospera/.env.commit &&
                sudo systemctl restart licitaprospera"
```

> Nota: o `EnvironmentFile` do systemd pode incluir `/opt/licitaprospera/.env.commit`
> (segundo `EnvironmentFile=` no unit) para o `APP_COMMIT` chegar ao processo.
> Verificação pós-deploy: `curl https://<host>/api/saude` → `commit` deve bater
> com o hash do Bitbucket (mesmo mecanismo usado hoje com o Render).

## 7. Checklist de migração (ordem sugerida)

1. ☐ Provisionar RDS (Postgres 14+) e EC2 (t3.small, Elastic IP), security groups.
2. ☐ Espelhar o repositório no Bitbucket; montar a pipeline (build + testes verdes).
3. ☐ Subir a aplicação na EC2 apontando para o **RDS vazio** (smoke: `/api/saude`,
   login com admin bootstrap, coleta manual, cadastro via PDF).
4. ☐ Janela de migração: parar o serviço no Render → `pg_dump` do Supabase →
   `pg_restore` no RDS → subir o app na EC2 → validar contagens e login dos
   usuários reais (senhas migram junto — são hashes bcrypt).
5. ☐ Apontar o DNS/URL definitivo; conferir HTTPS + cookie de sessão.
6. ☐ Desativar os jobs do cron-job.org (coleta e keep-alive).
7. ☐ **Rollback disponível**: manter o Render suspenso (não deletado) e o Supabase
   intacto por ~1–2 semanas; qualquer problema, religa o serviço antigo.
8. ☐ Ativar snapshots do RDS + pg_dump diário para S3.
9. ☐ Trocar/rotacionar segredos: nova `GEMINI_API_KEY` só de produção (a atual é
   compartilhada com o dev), novo `CRON_TOKEN` se usar EventBridge.
10. ☐ ConLicitação: cadastrar o IP de saída da EC2 quando o token chegar.
11. ☐ Atualizar `docs/DOCUMENTACAO-TECNICA.md` (§3.13) e marcar `render.yaml`/
    `DEPLOY.md` como legado.

## 8. Perguntas em aberto para o time de infra

1. **Empacotamento**: padrão Prospera é Docker ou serviço direto (systemd)? (§3)
2. **TLS/domínio**: ALB + ACM ou nginx + certbot? Qual será o domínio (público ou
   só rede interna/VPN)?
3. **RDS**: instância nova dedicada ou banco em instância compartilhada existente?
   Qual versão do PostgreSQL é padrão na casa?
4. **Segredos**: SSM Parameter Store, Secrets Manager ou variáveis secured do
   Bitbucket? Quem passa a custodiar as chaves de IA?
5. **Deploy**: SSH/rsync direto (como no exemplo), CodeDeploy, ou o padrão de
   scripts que a Prospera já usa nas outras aplicações?
6. **IP fixo de saída** para a ConLicitação: Elastic IP direto na EC2 ou NAT?
7. **Janela de migração**: quando o time pode ficar ~1h sem o sistema para o
   dump/restore?
8. **Chave de IA**: aproveitamos a migração para criar chave Gemini exclusiva de
   produção (ou avaliar tier pago/Claude com créditos)?

## 9. Backup do código-fonte (independente da migração)

- **Git bundle** (histórico completo em arquivo único): 
  `git bundle create licitaprosperacrm-AAAA-MM-DD.bundle --all` — restaurável com
  `git clone arquivo.bundle`. Gerar periodicamente e guardar fora da máquina.
- **Espelho em segundo remoto** (GitHub + Bitbucket simultâneos) — proteção
  contra perda de conta.
- ZIP da pasta do projeto cobre os arquivos não versionados (PDFs de análise,
  `.env` — este último só em local seguro).
- Os **dados** (inclusive anexos) estão 100% no Postgres — o backup de dados é o
  do banco (§2), não o do código.
