# Como colocar o LicitaProsperaCRM no ar (100% gratuito)

Este guia coloca o sistema na internet usando três serviços gratuitos:

| Serviço | Para quê | Site |
|---|---|---|
| **GitHub** | Guardar o código | https://github.com |
| **Supabase** | Banco de dados Postgres (os seus dados) | https://supabase.com |
| **Render** | Rodar o sistema (backend + telas) | https://render.com |
| **cron-job.org** | "Despertador": aciona a coleta a cada 6h | https://cron-job.org |

O uso no seu computador continua funcionando exatamente como antes (SQLite local) —
nada muda no dia a dia local.

---

## Etapa A — Subir o código para o GitHub

1. Crie uma conta em https://github.com (se ainda não tiver).
2. No canto superior direito, clique em **+** → **New repository**.
   - **Repository name**: `LicitaProsperaCRM`
   - Marque **Private** (privado — só você vê o código).
   - NÃO marque nenhuma opção de inicialização (sem README, sem .gitignore).
   - Clique em **Create repository**.
3. No seu computador, abra o terminal (PowerShell) na pasta do projeto e rode
   (troque `SEU-USUARIO` pelo seu usuário do GitHub):

   ```powershell
   cd "C:\Users\Henrique Izzo\LicitaProsperaCRM"
   git remote add origin https://github.com/SEU-USUARIO/LicitaProsperaCRM.git
   git push -u origin master
   ```

   > Se o git pedir login, siga as instruções na tela (ele abre o navegador).
   > Se aparecer erro dizendo que o branch é `main`, troque `master` por `main` no comando.

Pronto: o código está no GitHub. **Nenhuma senha ou chave sobe junto** — o arquivo
`.env` (que tem os segredos) fica só no seu computador.

---

## Etapa B — Criar o banco de dados no Supabase e migrar os seus dados

### B.1 Criar o projeto

1. Crie uma conta em https://supabase.com (pode entrar com o GitHub).
2. Clique em **New project**:
   - **Name**: `licitaprosperacrm`
   - **Database Password**: crie uma senha forte e **GUARDE-A** (você vai precisar dela).
   - **Region**: escolha **South America (São Paulo)**.
3. Aguarde 1–2 minutos até o projeto ficar pronto.

### B.2 Pegar a connection string (endereço do banco)

1. No projeto, vá em **Settings** (engrenagem) → **Database**
   (ou clique no botão **Connect** no topo da tela).
2. Na seção **Connection string**, escolha o modo **Session pooler**
   (ele usa a **porta 5432** — é o modo certo para um sistema que fica no ar).
3. Copie a URI, algo como:

   ```
   postgresql://postgres.abcdefghij:[YOUR-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres
   ```

4. Troque `[YOUR-PASSWORD]` pela senha do banco que você criou no passo B.1.
   Guarde essa URI completa — ela é a sua **DATABASE_URL**.

### B.3 Copiar os dados do seu computador para o Supabase

No terminal, na pasta do projeto (use a URI do passo anterior entre aspas):

```powershell
cd "C:\Users\Henrique Izzo\LicitaProsperaCRM\backend"
.venv\Scripts\python.exe scripts\migrar_para_postgres.py --destino "postgresql://postgres.abcdefghij:SUA-SENHA@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
```

O script cria as tabelas e copia usuários, licitações, análises, oportunidades e
anexos, mantendo tudo igual. Ao final ele mostra quantas linhas copiou.

> **Segurança**: o script se recusa a rodar se o banco de destino já tiver dados —
> assim ele nunca duplica nem sobrescreve nada. Se precisar recomeçar do zero,
> apague as tabelas no Supabase (Table Editor) e rode de novo.

---

## Etapa C — Colocar o sistema no ar no Render

1. Crie uma conta em https://render.com (pode entrar com o GitHub).
2. Clique em **New** → **Blueprint**.
3. Conecte a sua conta do GitHub e selecione o repositório **LicitaProsperaCRM**
   (o Render lê o arquivo `render.yaml`, que já configura tudo).
4. O Render vai pedir os valores das variáveis secretas. Preencha:

   | Variável | O que é | Onde conseguir |
   |---|---|---|
   | `DATABASE_URL` | Endereço do banco | A URI do Supabase (etapa B.2, com a senha) |
   | `ANTHROPIC_API_KEY` | Chave da IA | https://console.anthropic.com → API Keys |
   | `ADMIN_SENHA_INICIAL` | Senha inicial do admin | Invente uma senha forte (troque no 1º acesso) |
   | `CRON_TOKEN` | Senha do "despertador" | Invente um texto longo e aleatório, ex. 40 letras/números. Guarde para a etapa D |
   | `ADMIN_EMAIL` | Email de login do admin | Seu email (já vem preenchido no blueprint — confira/edite) |

5. Clique em **Apply** e aguarde o primeiro deploy (5–10 minutos).
6. Ao final, o Render mostra o endereço do sistema, algo como
   `https://licitaprosperacrm.onrender.com`. Abra no navegador e entre com o
   `ADMIN_EMAIL` e a `ADMIN_SENHA_INICIAL`. **Troque a senha no primeiro acesso**
   (menu "Trocar senha").

> **Alternativa sem blueprint** (se preferir criar manualmente): New → **Web Service**
> → selecione o repositório e configure:
> - **Runtime**: Python
> - **Build Command**: `pip install -r backend/requirements.txt && cd frontend && npm ci && npm run build`
> - **Start Command**: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
> - **Plan**: Free
> - Em **Environment**, adicione as variáveis da tabela acima e mais:
>   `COOKIE_SECURE=true`, `FRONTEND_DIST=../frontend/dist`, `COLETA_INTERVALO_HORAS=6`,
>   `PYTHON_VERSION=3.12.10`.
>
> Se o build reclamar de Node/npm, adicione a variável `NODE_VERSION=20.11.0`.

---

## Etapa D — Agendar a coleta automática no cron-job.org

No plano gratuito o Render "adormece" o serviço após ~15 minutos sem uso, e o
agendador interno para junto. A solução: um serviço externo gratuito chama o
sistema a cada 6 horas — isso **acorda o serviço e dispara a coleta** de uma vez.

1. Crie uma conta em https://cron-job.org (gratuito).
2. Clique em **Create cronjob**:
   - **Title**: `Coleta LicitaProspera`
   - **URL**: `https://SEU-APP.onrender.com/api/pipeline/executar-cron`
     (troque `SEU-APP` pelo nome real do seu serviço no Render)
   - **Schedule**: **Every 6 hours** (a cada 6 horas)
3. Na aba **Advanced**:
   - **Request method**: `POST`
   - **Headers**: adicione um header com
     - **Key**: `X-Cron-Token`
     - **Value**: o mesmo valor que você colocou em `CRON_TOKEN` no Render
   - **Timeout**: aumente para o máximo permitido (a coleta + análise pode demorar
     alguns minutos, e o serviço ainda leva ~1 minuto para acordar).
4. Salve. Você pode clicar em **Test run** para executar na hora e conferir:
   a resposta deve ser um JSON com `novas_licitacoes`, `analisadas` etc.

> Sem o token certo a rota responde 401; sem `CRON_TOKEN` configurado no Render,
> a rota nem existe (404). Ou seja: só quem tem o token dispara a coleta.

---

## Como atualizar o sistema depois

Sempre que você (ou o Claude) alterar o código no seu computador:

```powershell
cd "C:\Users\Henrique Izzo\LicitaProsperaCRM"
git add -A
git commit -m "Descreva aqui o que mudou"
git push
```

O Render detecta o `git push` e **redeploya sozinho** em alguns minutos.
Dá para acompanhar na aba **Events/Logs** do serviço no painel do Render.

---

## Limitações do plano gratuito (bom saber)

- **O serviço dorme** após ~15 minutos sem ninguém usar. No primeiro acesso do dia,
  a tela pode demorar **~1 minuto** para abrir (o serviço está "acordando"). Depois
  disso fica rápido normalmente.
- O job do cron-job.org a cada 6h também acorda o serviço, então a coleta continua
  acontecendo mesmo com o sistema dormindo.
- O Render free oferece 750 horas/mês de execução — suficiente para um serviço.
- O Supabase free tem 500 MB de banco. Os anexos de documentos ficam no banco;
  se um dia encher, dá para migrar para um plano pago ou limpar anexos antigos.
- O plano gratuito do Supabase **pausa projetos sem atividade por ~1 semana** —
  como o cron roda a cada 6h e usa o banco, isso normalmente não acontece. Se o
  projeto pausar (aviso por email), reative no painel do Supabase com um clique.

## Uso local continua igual

No seu computador nada muda: o backend usa o SQLite (`backend\licitaprospera.db`)
e o frontend roda com o Vite em `http://localhost:5173`. O banco local e o banco
da nuvem são **independentes** — o que você cadastra localmente não aparece na
nuvem (e vice-versa). A migração da etapa B.3 é um evento único, de partida.
