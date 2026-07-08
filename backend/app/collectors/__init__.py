from .pncp import PNCPCollector
from .conlicitacao import ConLicitacaoCollector
from .bll import BLLCollector
from .fiesc import FIESCCollector
from .fiergs import FIERGSCollector
from .fiems import FIEMSCollector

# Coletores ativos no pipeline (ConLicitação entra quando houver token)
def coletores_ativos(settings):
    ativos = [PNCPCollector(), FIESCCollector(), FIERGSCollector(), FIEMSCollector()]
    if settings.conlicitacao_token:
        ativos.append(ConLicitacaoCollector(settings.conlicitacao_token))
    return ativos
