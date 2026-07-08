"""Coletor do Portal de Compras do Sistema FIEMS (FIEMS/SESI/SENAI/IEL de Mato Grosso do Sul).

Página pública:  https://compras.fiems.com.br/portal/Mural.aspx  (e ?nNmTela=E)
Endpoint JSON:   POST /portal/WebService/Servicos.asmx/PesquisarProcessos
Plataforma:      Paradigma WBC — toda a lógica está em paradigma_mural.py.

O Sistema S não publica no PNCP; este portal é a fonte oficial das contratações
de SESI/MS, SENAI/MS, FIEMS e IEL/MS. Fuso de MS: UTC-4.
"""
from .paradigma_mural import ParadigmaMuralCollector


class FIEMSCollector(ParadigmaMuralCollector):
    fonte = "fiems"
    uf = "MS"
    base_url = "https://compras.fiems.com.br"
    orgao_padrao = "Sistema FIEMS (SESI/SENAI-MS)"
    fuso_horas = -4
