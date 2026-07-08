"""Coletor do Portal de Compras do Sistema FIESC (FIESC/SESI/SENAI/IEL de Santa Catarina).

Página pública:  https://portaldecompras.fiesc.com.br/portal/Mural.aspx  (e ?nNmTela=E)
Endpoint JSON:   POST /portal/WebService/Servicos.asmx/PesquisarProcessos
Plataforma:      Paradigma WBC — toda a lógica está em paradigma_mural.py.

O Sistema S não publica no PNCP; este portal é a fonte oficial das contratações
de SESI/SC, SENAI/SC, FIESC e IEL/SC.
"""
from .paradigma_mural import ParadigmaMuralCollector


class FIESCCollector(ParadigmaMuralCollector):
    fonte = "fiesc"
    uf = "SC"
    base_url = "https://portaldecompras.fiesc.com.br"
    orgao_padrao = "Sistema FIESC (SESI/SENAI-SC)"
    fuso_horas = -3
