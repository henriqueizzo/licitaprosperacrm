"""Coletor da API ConLicitação (para assinantes).

A API do ConLicitação exige token de acesso e libera o IP do cliente.
Endpoints típicos (confirmar na documentação do assinante):
  - https://consultaonline.conlicitacao.com.br/api/filtros
  - https://consultaonline.conlicitacao.com.br/api/filtro/{id}/licitacoes

Quando o token estiver disponível, preencher CONLICITACAO_TOKEN no .env
e ajustar o parse conforme o retorno real da API.
"""
import logging

import httpx

from .base import BaseCollector, LicitacaoColetada

logger = logging.getLogger(__name__)

BASE_URL = "https://consultaonline.conlicitacao.com.br/api"


class ConLicitacaoCollector(BaseCollector):
    fonte = "conlicitacao"

    def __init__(self, token: str):
        self.token = token

    def coletar(self, ufs, palavras_chave, dias=3):
        headers = {"x-auth-token": self.token}
        resultados: list[LicitacaoColetada] = []
        try:
            with httpx.Client(timeout=60, headers=headers) as client:
                # 1. Lista os filtros configurados na conta do assinante
                filtros = client.get(f"{BASE_URL}/filtros").json()
                for filtro in filtros.get("filtros", []):
                    fid = filtro.get("id")
                    resp = client.get(f"{BASE_URL}/filtro/{fid}/licitacoes", params={"order": "desc"})
                    resp.raise_for_status()
                    for lic in resp.json().get("licitacoes", []):
                        item = self._normalizar(lic)
                        if item.uf and ufs and item.uf not in ufs:
                            continue
                        resultados.append(item)
        except Exception as exc:
            logger.warning("ConLicitação: falha na coleta (token/IP liberado?): %s", exc)
        return resultados

    def _normalizar(self, lic: dict) -> LicitacaoColetada:
        orgao = lic.get("orgao", {}) or {}
        return LicitacaoColetada(
            fonte=self.fonte,
            id_externo=str(lic.get("id", "")),
            orgao=orgao.get("nome", ""),
            municipio=orgao.get("cidade", ""),
            uf=orgao.get("uf", ""),
            modalidade=lic.get("modalidade", ""),
            objeto=lic.get("objeto", ""),
            valor_estimado=lic.get("valor_estimado"),
            data_abertura=lic.get("abertura_datetime") or "",
            data_encerramento=lic.get("prazo_datetime") or "",
            link=lic.get("url", ""),
            edital_url="",  # documentos vêm no detalhe da licitação
            raw=lic,
        )
