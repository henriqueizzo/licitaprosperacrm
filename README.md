# LICITAPROSPERACRM

CRM integrado a portais de licitações públicas com análise de editais por IA (Claude).

## Fluxo

```
Coletor (PNCP / ConLicitação / BLL) → Analisador IA (lê o edital PDF)
    → Score de aderência vs perfil da empresa → Pipeline de oportunidades (CRM)
```

## Perfil da empresa

Benefícios corporativos (VR, VA, VT, multibenefícios) — região Sul (RS, SC, PR).
O perfil é editável em `GET/PUT /api/perfil`.

## Como rodar (backend)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # e preencha ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

API em http://localhost:8000 — documentação interativa em http://localhost:8000/docs

## Endpoints principais

| Método | Rota | Descrição |
|---|---|---|
| POST | /api/pipeline/executar | Roda coleta + análise agora |
| GET | /api/licitacoes | Licitações coletadas (+ análise) |
| GET | /api/oportunidades | Pipeline do CRM |
| PATCH | /api/oportunidades/{id} | Move estágio (identificada → ... → ganhou/perdeu) |
| GET/PUT | /api/perfil | Perfil da empresa usado pela IA |

## Fontes

- **PNCP** — ativo (API pública)
- **ConLicitação** — aguardando token de API do assinante (`CONLICITACAO_TOKEN` no .env)
- **BLL Compras** — stub (scraping a implementar)
