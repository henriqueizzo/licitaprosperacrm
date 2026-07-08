"""Coletor do Portal de Compras do Sistema FIERGS (FIERGS/SESI/SENAI/IEL do Rio Grande do Sul).

Página pública:  https://compras.sistemafiergs.org.br/portal/Mural.aspx  (e ?nNmTela=E)
Endpoint JSON:   POST /portal/WebService/Servicos.asmx/PesquisarProcessos
Plataforma:      Paradigma WBC — toda a lógica está em paradigma_mural.py.

O Sistema S não publica no PNCP; este portal é a fonte oficial das contratações
de SESI-RS, SENAI-RS, FIERGS e IEL-RS.
"""
from .paradigma_mural import ParadigmaMuralCollector


class FIERGSCollector(ParadigmaMuralCollector):
    fonte = "fiergs"
    uf = "RS"
    base_url = "https://compras.sistemafiergs.org.br"
    orgao_padrao = "Sistema FIERGS (SESI/SENAI-RS)"
    fuso_horas = -3
