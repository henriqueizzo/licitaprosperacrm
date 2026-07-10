---
name: design-prospera
description: Design system "Centro de Comando" do LicitaProsperaCRM — usar sempre que criar ou alterar qualquer tela, componente ou estilo do frontend.
---

# Design system Prospera — "Centro de Comando"

Tema escuro azul-profundo aprovado em 2026-07-10. Toda tela nova ou alterada DEVE seguir estas regras. Os tokens vivem em `frontend/src/styles.css` (`:root`) — sempre usar as variáveis CSS, nunca cores hardcoded.

## Conceito

O CRM é uma sala de operações de licitações, não um formulário corporativo. O azul Prospera (#0050E5) é **luz**, não tinta: brilha em botões, abas ativas e scores. Fundos quase-pretos azulados, dados em fonte monoespaçada, rótulos técnicos em caps.

## Tokens (já definidos em styles.css)

- Fundos: `--void` #060A13 (página) · `--panel` #0C1424 (cartões) · `--panel-2` #111C33 (topo de gradientes) · bordas `--linha` #1C2C4D / `--linha-suave` #152341
- Marca: `--azul` #0050E5 (fills/gradientes) · `--azul-luz` #4D8DFF (texto/bordas em destaque) · `--gelo` #9DC2FF (títulos de seção)
- Texto: `--texto` #E6EDFB · `--texto-suave` #9DB0D4 · `--texto-mudo` #64769E
- Status: `--verde` #2BD576 · `--amarelo` #FFB224 · `--vermelho` #FF5D5D, cada um com `-fundo` (12% alpha) e `-borda` (38% alpha)
- Glow padrão de ação: `--glow-azul`; foco: `--foco`

## Tipografia (3 papéis, nunca misturar)

1. **Display** `var(--display)` = Chakra Petch (self-hosted em `frontend/public/fonts/`, pesos 500/600): títulos, rótulos de abas/colunas, botões primários, nomes de órgão. Rótulos em uppercase levam `letter-spacing` 0.05–0.16em.
2. **Corpo** `var(--corpo)` = Segoe UI: texto corrido, descrições, inputs.
3. **Mono** `var(--mono)` = Cascadia Mono/Consolas: TODO valor, data, score, contagem e rótulo técnico (th de tabela, tile-k). Números tabulares (`font-variant-numeric: tabular-nums`) onde alinham em coluna.

## Regras de componente

- **Superfícies**: cartões usam `linear-gradient(180deg, var(--panel-2), var(--panel))` + borda `--linha`; raio 10px (7px em elementos pequenos). Cartões do kanban têm `border-left: 2px solid var(--azul)`.
- **Ação primária**: gradiente `#1D6BFF → var(--azul)`, borda clara translúcida, `--glow-azul`, texto uppercase em Chakra Petch 600.
- **Chips de status** (scores, vereditos): fundo 12% alpha + borda 38% alpha + texto na cor plena, fonte mono. Verde ganha glow sutil; âmbar e vermelho não.
- **Semântica**: verde = aprovado/score alto, âmbar = revisar/moderado, vermelho = reprovado/score baixo. Nunca usar o azul da marca para status.
- **Grid de fundo**: o body já tem grid blueprint 34px + glow radial no topo — não repetir em containers internos (exceto `.login-fundo`, que tem o próprio).
- **LED pulsante** (`.led`): indica processo automático ativo; respeita `prefers-reduced-motion`.
- **Logomarca**: NUNCA alterar, recolorir ou aplicar filtro no `prospera-logo.png`. Sobre fundo escuro, sempre dentro de `.logo-chip` (chip branco arredondado).
- **Inputs**: fundo `--campo-fundo`, labels em mono uppercase pequeno; foco = borda `--azul-luz` + `--foco`.
- `color-scheme: dark` está no `:root` — controles nativos (date, checkbox) já rendem escuros.

## Ao criar telas novas

Reusar as classes existentes (`.tile`, `.cartao`, `.tabela`, `.veredito`, `.perfil`, `.acoes`) antes de criar novas. Indicadores agregados usam o padrão `.cockpit`/`.tile` (linha luminosa no topo via `::before`). Manter nomes de classe em português, como o restante do projeto.
