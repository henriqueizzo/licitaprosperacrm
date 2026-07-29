# Formato do PDF de análise para o Cadastro Manual

Guia para quem gera o **relatório de análise de edital** que o operador anexa no
Cadastro Manual (campo "anexe o PDF ... da nossa análise do edital"). Seguindo este
formato, a importação preenche os campos do cadastro, grava a análise no card
(classificação, scores, alertas) e cria o checklist de Documentação — sem erros.

## 1. Requisitos do ARQUIVO (os que causam erro quando violados)

| Requisito | Por quê |
|---|---|
| **PDF de texto** (texto selecionável — dá para copiar/colar) | PDF escaneado/foto sem OCR é rejeitado com erro 422. Gere o PDF exportando de Word/Google Docs ("Salvar como PDF" / "Imprimir → Salvar como PDF"). Nunca fotografe ou escaneie páginas. |
| **Sem senha ou proteção** | PDF protegido é rejeitado pela IA. |
| **Até 19 MB** | Acima disso a rota recusa (413). Um relatório de análise em texto fica muito abaixo disso. |
| **Texto em página corrida, uma coluna** | Evite caixas de texto flutuantes e layout em 2 colunas — a extração de texto embaralha a ordem de leitura. |
| **Tabelas como tabelas de texto** (não imagens) | Tabela colada como imagem/print não é lida no plano B de leitura local. |
| **Sem emojis/ícones decorativos** | Poluem a extração e podem corromper caracteres. |

## 2. Estrutura que o CRM reconhece como "relatório de análise"

O sistema decide que o PDF é um relatório (e não um edital) por estas âncoras — elas
**precisam existir com estes títulos**:

1. O documento **começa com a seção `TABELAS DE DADOS DO CERTAME`**.
2. Contém a seção **`TABELA DE DOCUMENTOS PARA HABILITAÇÃO`**.
3. Contém **`SCORE FINAL`** com as duas linhas:
   - `Prospera Benefícios: X/10`
   - `Prospera Pagamentos: Y/10`
4. Contém **`CLASSIFICAÇÃO FINAL`** com exatamente UMA destas opções:
   `EXCELENTE OPORTUNIDADE` · `BOA OPORTUNIDADE` · `OPORTUNIDADE MODERADA` ·
   `ALTO RISCO` · `NÃO RECOMENDADO`.

Se alguma âncora faltar, o sistema trata o PDF como edital: os campos do cadastro são
preenchidos e o checklist é extraído do próprio documento, mas a classificação e os
scores não entram no card.

## 3. De onde o cadastro puxa cada campo

**Tabela 1 — Resumo do Certame** (nomes dos parâmetros exatamente assim):

| Parâmetro na Tabela 1 | Vira no CRM |
|---|---|
| Nome do Certame | Objeto |
| Código/Número do Certame | Número do certame |
| Modalidade | Modalidade |
| Órgão/Prefeitura | Órgão |
| Cidade | Município |
| Estado (UF) | UF (sigla de 2 letras, ex.: `SC`) |
| Valor Total Estimado | Valor estimado |
| Data Máx. Credenciamento | Data de vencimento |
| Análise Preliminar de Credenciamento | Viabilidade de credenciamento — o texto deve começar com **"Viável."** ou **"Inviável."** |

**Tabela 2 — Responsável pelo Certame** → campo Responsável (nome + cargo).

**Tabela 3 — Envio da Documentação** → o `Portal/Site (URL)` vira o link do card e o
endereço da licitação; a forma de envio/e-mail vira Observações.

Formatos que evitam erro de conversão:
- **Datas**: `DD/MM/AAAA` (ex.: `17/07/2026`). Nunca "17 de julho".
- **Valores**: formato brasileiro completo, ex.: `R$ 940.000,00`.
- **Campo sem informação**: escreva `Não informado no edital` (nunca deixe em branco,
  nem invente).

## 4. TABELA DE DOCUMENTOS PARA HABILITAÇÃO (vira o checklist de Documentação)

É a parte mais importante para o controle de documentos. Regras:

- 3 colunas: `Categoria | Documento Exigido | Referência no Edital`.
- **Uma linha por documento** — nunca agrupe vários documentos numa linha só.
  Cada subitem do edital (`a.1`, `b.2`, …) é uma linha.
- Categoria: exatamente uma destas 5 (outras categorias são remapeadas para a mais
  próxima, mas o ideal é já usar estas):
  - `HABILITAÇÃO JURÍDICA`
  - `REGULARIDADE FISCAL E TRABALHISTA`
  - `QUALIFICAÇÃO TÉCNICA`
  - `QUALIFICAÇÃO ECONÔMICO-FINANCEIRA`
  - `OUTROS DOCUMENTOS / DECLARAÇÕES`
- Referência: item/cláusula/página do edital (ex.: `Item 8.4, a.1, p. 6`) ou
  `Não informado no edital`.
- Seja exaustivo: declarações de anexos-modelo, garantias, atestados, termos de
  ciência — tudo que a empresa precise apresentar em qualquer fase entra na tabela.

## 5. Bloco pronto para colar no prompt que gera o PDF

```
REGRAS DE FORMATO DO RELATÓRIO (para importação no LicitaProsperaCRM):
1. O relatório DEVE começar pela seção "TABELAS DE DADOS DO CERTAME", com a
   Tabela 1 (Resumo do Certame), a Tabela 2 (Responsável pelo Certame) e a
   Tabela 3 (Envio da Documentação), usando exatamente os nomes de parâmetros
   padrão (Nome do Certame, Código/Número do Certame, Modalidade,
   Órgão/Prefeitura, Cidade, Estado (UF), Valor Total Estimado,
   Data Máx. Credenciamento, Análise Preliminar de Credenciamento etc.).
2. A "Análise Preliminar de Credenciamento" deve começar com a palavra
   "Viável." ou "Inviável.".
3. Incluir a seção "TABELA DE DOCUMENTOS PARA HABILITAÇÃO" com 3 colunas
   (Categoria | Documento Exigido | Referência no Edital), UMA LINHA POR
   DOCUMENTO, usando somente as categorias: HABILITAÇÃO JURÍDICA;
   REGULARIDADE FISCAL E TRABALHISTA; QUALIFICAÇÃO TÉCNICA; QUALIFICAÇÃO
   ECONÔMICO-FINANCEIRA; OUTROS DOCUMENTOS / DECLARAÇÕES.
4. Incluir a seção "SCORE FINAL" com as linhas "Prospera Benefícios: X/10" e
   "Prospera Pagamentos: Y/10", e a seção "CLASSIFICAÇÃO FINAL" com exatamente
   uma das opções: EXCELENTE OPORTUNIDADE, BOA OPORTUNIDADE, OPORTUNIDADE
   MODERADA, ALTO RISCO, NÃO RECOMENDADO.
5. Datas sempre em DD/MM/AAAA; valores sempre como "R$ 999.999,99"; campo sem
   informação = "Não informado no edital". Não usar emojis nem ícones.
6. Texto em uma coluna, tabelas como tabelas de texto (nunca imagens). O PDF
   final deve ter texto selecionável (exportado, não escaneado) e não pode ter
   senha.
```

## 6. O que acontece se o PDF fugir do formato

| Situação | Comportamento do CRM |
|---|---|
| PDF escaneado/sem texto, protegido ou corrompido | Erro 422 pedindo para reexportar o PDF. |
| PDF é o edital (sem as âncoras de relatório) | Campos preenchidos + checklist de documentação extraído do edital; sem scores/classificação. |
| Relatório sem a tabela de documentos | Análise importada, mas o checklist de Documentação fica vazio. |
| Categoria fora das 5 | Remapeada para a categoria mais próxima (mantém o nome do documento). |
