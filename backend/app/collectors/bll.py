"""Coletor BLL Compras (bll.org.br) — sem API pública; requer scraping.

Stub: a implementar. O portal usa busca paginada em
https://bllcompras.com/Process/ProcessSearch — o scraping exige sessão
e tratamento de captcha/anti-bot, então será feito numa fase posterior.
Muitas licitações da BLL também são publicadas no PNCP (fonte já ativa).
"""
import logging

from .base import BaseCollector, LicitacaoColetada

logger = logging.getLogger(__name__)


class BLLCollector(BaseCollector):
    fonte = "bll"

    def coletar(self, ufs, palavras_chave, dias=3) -> list[LicitacaoColetada]:
        logger.info("BLL: coletor ainda não implementado (stub)")
        return []
