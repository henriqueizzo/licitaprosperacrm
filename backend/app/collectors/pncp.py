"""Coletor do PNCP — Portal Nacional de Contratações Públicas (API pública, sem autenticação).

Docs: https://pncp.gov.br/api/consulta/swagger-ui/index.html

Estratégia:
- Fonte principal: /v1/contratacoes/proposta (propostas EM ABERTO — o que ainda dá para disputar).
- Complemento:    /v1/contratacoes/publicacao (publicadas nos últimos N dias).
- O PNCP oscila com frequência (erros 500 de banco) → retry com backoff em cada página.
"""
import logging
import re
import time
from datetime import date, timedelta

import httpx

from .base import BaseCollector, LicitacaoColetada

logger = logging.getLogger(__name__)

PROPOSTA_URL = "https://pncp.gov.br/api/consulta/v1/contratacoes/proposta"
PUBLICACAO_URL = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
ARQUIVOS_URL = "https://pncp.gov.br/pncp-api/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos"
PAGINA_PNCP = "https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"

# Modalidades relevantes (Lei 14.133): 6=Pregão eletrônico, 8=Dispensa, 4=Concorrência eletrônica
MODALIDADES = [6, 8, 4]

# /proposta: `dataFinal` é o TETO da data de ENCERRAMENTO das propostas, não "hoje" —
# com dataFinal=hoje o endpoint devolve apenas o que encerra no próprio dia (uma fatia
# quase vazia). Usamos hoje+N dias para pegar tudo que ainda está em disputa; o que
# encerra além do horizonte continua em aberto e entra nas coletas seguintes.
PROPOSTA_HORIZONTE_DIAS = 45

# 50 é o máximo que a API de consulta aceita (100/500 retornam 400 "Tamanho de página inválido")
TAMANHO_PAGINA = 50

TIMEOUT = 60  # /proposta chega a passar de 30s para responder
TENTATIVAS_ESPERA = [3, 10]  # backoff entre tentativas (total: 3 tentativas por página)
ESPERA_RATE_LIMIT = [15, 30, 60]  # esperas maiores quando o PNCP devolve 429 (rate limit)
PAUSA_ENTRE_PAGINAS = 0.6  # pausa preventiva entre requisições para não estourar o rate limit


class PNCPCollector(BaseCollector):
    fonte = "pncp"

    def __init__(self):
        self.falhas = 0  # páginas que falharam mesmo após retries (para aviso na UI)

    def coletar(self, ufs, palavras_chave, dias=3):
        self.falhas = 0
        hoje = date.today()
        vistos: set[str] = set()
        resultados: list[LicitacaoColetada] = []

        with httpx.Client(timeout=TIMEOUT) as client:
            for uf in ufs:
                for modalidade in MODALIDADES:
                    # 1) Propostas em aberto (principal) — encerramento até hoje+horizonte
                    itens = self._paginar(client, PROPOSTA_URL, {
                        "dataFinal": (hoje + timedelta(days=PROPOSTA_HORIZONTE_DIAS)).strftime("%Y%m%d"),
                        "codigoModalidadeContratacao": modalidade,
                        "uf": uf,
                        "tamanhoPagina": TAMANHO_PAGINA,
                    })
                    # 2) Publicadas nos últimos N dias (complemento: pega as que ainda
                    #    não abriram o recebimento de propostas)
                    itens += self._paginar(client, PUBLICACAO_URL, {
                        "dataInicial": (hoje - timedelta(days=dias)).strftime("%Y%m%d"),
                        "dataFinal": hoje.strftime("%Y%m%d"),
                        "codigoModalidadeContratacao": modalidade,
                        "uf": uf,
                        "tamanhoPagina": TAMANHO_PAGINA,
                    })

                    for item in itens:
                        objeto = item.get("objetoCompra", "")
                        if not self.bate_palavra_chave(objeto, palavras_chave):
                            continue
                        lic = self._normalizar(item, uf)
                        if lic.id_externo in vistos:
                            continue
                        vistos.add(lic.id_externo)
                        resultados.append(lic)

        logger.info("PNCP: %d licitações após filtro de palavras-chave (%d páginas falharam)",
                    len(resultados), self.falhas)
        return resultados

    # ---------- infraestrutura ----------

    def _paginar(self, client: httpx.Client, url: str, params: dict) -> list[dict]:
        """Percorre todas as páginas de um endpoint de consulta, com retry por página."""
        itens: list[dict] = []
        pagina = 1
        while True:
            dados = self._get_com_retry(client, url, {**params, "pagina": pagina})
            if dados is None:  # falhou após retries ou 204 sem resultados
                break
            itens.extend(dados.get("data", []))
            if pagina >= dados.get("totalPaginas", 1):
                break
            pagina += 1
            time.sleep(PAUSA_ENTRE_PAGINAS)
        return itens

    def _get_com_retry(self, client: httpx.Client, url: str, params: dict) -> dict | None:
        espera = 0.0
        for tentativa in range(1 + len(TENTATIVAS_ESPERA)):
            if espera:
                time.sleep(espera)
            try:
                resp = client.get(url, params=params)
                if resp.status_code == 204:
                    return None  # sem resultados
                if resp.status_code == 429:
                    # Rate limit: espera o que o portal pedir (Retry-After) ou um backoff maior
                    retry_after = float(resp.headers.get("Retry-After") or 0)
                    espera = max(retry_after, ESPERA_RATE_LIMIT[min(tentativa, len(ESPERA_RATE_LIMIT) - 1)])
                    logger.warning("PNCP %s params=%s tentativa %d: rate limit (429), aguardando %.0fs",
                                   url.rsplit('/', 1)[-1], params, tentativa + 1, espera)
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                espera = TENTATIVAS_ESPERA[tentativa] if tentativa < len(TENTATIVAS_ESPERA) else 0
                logger.warning("PNCP %s params=%s tentativa %d falhou: %s",
                               url.rsplit('/', 1)[-1], params, tentativa + 1, exc)
        self.falhas += 1
        return None

    # ---------- normalização ----------

    def _normalizar(self, item: dict, uf: str) -> LicitacaoColetada:
        orgao = item.get("orgaoEntidade", {}) or {}
        unidade = item.get("unidadeOrgao", {}) or {}
        cnpj = orgao.get("cnpj", "")
        ano = item.get("anoCompra", "")
        seq = item.get("sequencialCompra", "")
        return LicitacaoColetada(
            fonte=self.fonte,
            id_externo=item.get("numeroControlePNCP", f"{cnpj}-{ano}-{seq}"),
            orgao=orgao.get("razaoSocial", ""),
            municipio=unidade.get("municipioNome", ""),
            uf=unidade.get("ufSigla", uf),
            modalidade=item.get("modalidadeNome", ""),
            objeto=item.get("objetoCompra", ""),
            valor_estimado=item.get("valorTotalEstimado"),
            data_abertura=item.get("dataAberturaProposta") or "",
            data_encerramento=item.get("dataEncerramentoProposta") or "",
            link=PAGINA_PNCP.format(cnpj=cnpj, ano=ano, seq=seq),
            edital_url=ARQUIVOS_URL.format(cnpj=cnpj, ano=ano, seq=seq),
            raw=item,
        )

    # Teto conjunto dos PDFs enviados à IA (limite inline do Gemini ~20 MB)
    MAX_BYTES_DOCUMENTOS = 19 * 1024 * 1024

    @staticmethod
    def baixar_documentos(edital_url: str) -> list[bytes]:
        """Baixa TODOS os arquivos PDF da licitação no PNCP, com retry.

        Os documentos de habilitação costumam estar no Termo de Referência e nos
        anexos — arquivos separados do edital. Baixar só o primeiro arquivo fazia
        a análise perder exigências inteiras; agora a IA recebe o conjunto
        (edital primeiro), respeitando o teto de bytes do provedor.
        """
        for tentativa, espera in enumerate([0] + TENTATIVAS_ESPERA):
            if espera:
                time.sleep(espera)
            resultado = PNCPCollector._tentar_baixar_todos(edital_url)
            if resultado is not None:
                return resultado
        return []

    @staticmethod
    def baixar_edital(edital_url: str) -> bytes | None:
        """Compatibilidade: retorna só o primeiro documento (edital), se houver."""
        documentos = PNCPCollector.baixar_documentos(edital_url)
        return documentos[0] if documentos else None

    @staticmethod
    def _tentar_baixar_todos(edital_url: str) -> list[bytes] | None:
        """Uma tentativa de download. None = erro transitório (retry); [] = sem PDF disponível."""
        try:
            with httpx.Client(timeout=120, follow_redirects=True) as client:
                resp = client.get(edital_url)
                resp.raise_for_status()
                arquivos = resp.json()
                if not arquivos:
                    return []
                # Edital primeiro; demais arquivos (TR, anexos) na sequência
                arquivos = sorted(
                    arquivos,
                    key=lambda a: 0 if "edital" in (a.get("titulo") or "").lower() else 1,
                )
                documentos: list[bytes] = []
                total = 0
                for arquivo in arquivos:
                    doc_url = arquivo.get("url") or arquivo.get("uri")
                    if not doc_url:
                        continue
                    # Bug do PNCP: o URL vem com porta interna inválida (ex.: pncp.gov.br:57667)
                    # que não aceita conexão externa — remove a porta para usar a padrão (443).
                    doc_url = re.sub(r"^(https://[^/:]+):\d+", r"\1", doc_url)
                    try:
                        doc = client.get(doc_url)
                        doc.raise_for_status()
                    except Exception as exc:
                        # Falha em um anexo não derruba o conjunto — o edital pode ter vindo
                        logger.warning("Falha ao baixar arquivo %s: %s", doc_url, exc)
                        continue
                    if b"%PDF" not in doc.content[:1024]:
                        logger.info("Arquivo %r não é PDF, ignorado", arquivo.get("titulo") or doc_url)
                        continue
                    if total + len(doc.content) > PNCPCollector.MAX_BYTES_DOCUMENTOS:
                        logger.warning(
                            "Arquivo %r excede o teto de %d MB do conjunto; analisando sem ele",
                            arquivo.get("titulo") or doc_url,
                            PNCPCollector.MAX_BYTES_DOCUMENTOS // (1024 * 1024),
                        )
                        continue
                    documentos.append(doc.content)
                    total += len(doc.content)
                return documentos
        except Exception as exc:
            logger.warning("Falha ao baixar documentos de %s: %s", edital_url, exc)
            return None
