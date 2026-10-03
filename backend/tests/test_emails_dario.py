"""Aba "E-mails do Dario": parsers dos boletins, casamento com a base, triagem e rotas.

As amostras abaixo reproduzem a estrutura REAL dos e-mails encaminhados em
02/10/2026 (BLL "Divulgador de editais" e Portal de Compras Públicas "Alerta de
Licitações"), com o rodapé encurtado. Há também a versão em texto puro (como o
Gmail copia), que a tela aceita em "Colar e-mail".

Rodar de dentro de backend/:  .venv\\Scripts\\python.exe -m pytest tests\\test_emails_dario.py -q
"""
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import security
from app.analyzer.schemas import AvaliacaoItemEmail
from app.collectors.base import LicitacaoColetada
from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import ItemEmail, Licitacao, Oportunidade, PerfilEmpresa, PERFIL_PADRAO
from app.services import emails as servico
from app.services import pipeline
from app.services.emails_parser import (
    conteudo_para_linhas, html_para_linhas, identificar_boletim, parse_bll, parse_pcp, texto_para_linhas,
)

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base.metadata.create_all(engine)


def _get_db_teste():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


def _banco_limpo():
    """Cada cenário parte do zero — o agente lembra decisões anteriores (repetidos,
    'já na base'), então estado de um teste mudaria o veredito do seguinte."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    _IAFalsa.chamadas.clear()


# ---------------------------------------------------------------------------
# Amostras
# ---------------------------------------------------------------------------

_BLL_ITEM = """
<tr><td><table align="center"><tbody><tr><td>
<table align="center"><tbody>
<tr><td align="center">{cidade} - {uf}</td></tr>
<tr><td align="center"><b>{orgao}</b></td></tr>
</tbody></table><br />
<table align="center"><tbody><tr>
<td align="center">PREGÃO ELETRÔNICO</td>
<td align="center" style="padding-left:3em">{numero}</td>
<td align="center" style="padding-left:3em"></td>
<td align="center" style="padding-left:3em">{tipo}</td>
</tr></tbody></table>
<table align="center"><tbody><tr>
<td align="center">Início Propostas: {inicio}</td>
<td align="center" style="padding-left:5em">Fim Propostas: {fim}</td>
</tr></tbody></table>
<p style="text-align:center;padding:10px"><a href="{link}" style="color:#ffffff" target="_blank">Acessar Processo</a></p>
<table align="center"><tbody>
<tr><td align="center"><b>OBJETO</b></td></tr>
<tr><td align="center">{objeto}</td></tr>
</tbody></table>
</td></tr></tbody></table><br /></td></tr>
"""

BLL_HTML = """<html><body>
<div name="messageBodySection"><div>Bom dia, segue para análise de viabilidade.&#160;</div><div>At.te&#160;</div></div>
<div name="messageSignatureSection"><br /><div><img src="cid:562B57B58CAE4BF99B8BF5E2FDBF275F" width="640" height="172" /></div></div>
<div name="messageReplySection">---------- Mensagem encaminhada ----------<br />
<b>De:</b> BLLCOMPRAS &lt;avisos@bllcompras.com&gt;<br />
<b>Data:</b> 2 de out. de 2026, 02:47 -0300<br />
<b>Para:</b> dario.ribeiro@prosperapagamentos.com<br />
<b>Assunto:</b> Divulgador de editais<br /><br />
<blockquote type="cite"><center class="wrapper"><div class="webkit">
<table width="100%"><tr><td>
<div><div style="text-align: center"><span style="font-size: 24px">Divulgador de editais</span></div></div>
<table align="center" border="1" cellspacing="0" style="width:100%"><tbody>
<tr><td style="background-color:#45605b" align="center"><h2 style="color:white">SÃO PAULO</h2></td></tr>
""" + _BLL_ITEM.format(
    cidade="SANTOS", uf="SP", orgao="CAIXA DE ASSISTENCIA AO SERVIDOR PUBLICO MUNICIPAL DE SANTOS",
    numero="014/2026", tipo="AQUISIÇÃO PARCELADA", inicio="11/08/2026 16:00", fim="23/10/2026 09:00",
    link="https://bllcompras.com/Process/ProcessView?param1=[gkz]Ery1Gmf8eeMtA4WMmgohcxEO5Cx8qSloxYeq8n05tU17_wg6rpTUAWA7TI/LGYkPs9oTiomSgyvhhdpr1Dlwdi/VgLiB7qaH_dzgKDB7wh8=",
    objeto="CONTRATAÇÃO DE INSTITUIÇÃO FINANCEIRA, PÚBLICA OU PRIVADA, PARA A PRESTAÇÃO DE SERVIÇOS BANCÁRIOS, "
           "compreendendo o processamento e crédito em conta da Folha de pagamento da Caixa de Assistência ao "
           "Servidor Público Municipal de Santos – CAPEP-SAÚDE",
) + _BLL_ITEM.format(
    cidade="BASTOS", uf="SP", orgao="MUNICIPIO DE BASTOS", numero="043/2026", tipo="AQUISIÇÃO PARCELADA",
    inicio="02/10/2026 08:00", fim="21/10/2026 08:00",
    link="https://bllcompras.com/Process/ProcessView?param1=[gkz]_V/0O2qNFQcSoKbY6HOdRI2jQPOgJwThvEjMw_v8fa_FeI8gLVH/_vhH/Q2Xcl18g9MKPGjRA2VWiS2V/4h6bAi50FqylwwDCXdzqj5_xNU=",
    objeto="LOCAÇÃO DE SOFTWARE PARA ADMINISTRAÇÃO, GERENCIAMENTO, EMISSÃO DE VALE ALIMENTAÇÃO EM CARTÃO "
           "MAGNÉTICO PARA OS SERVIDORES PÚBLICOS DA PREFEITURA.",
) + """
</tbody></table><br />
<table align="center" border="1" cellspacing="0" style="width:100%"><tbody>
<tr><td style="background-color:#45605b" align="center"><h2 style="color:white">PARANÁ</h2></td></tr>
""" + _BLL_ITEM.format(
    cidade="QUITANDINHA", uf="PR", orgao="MUNICIPIO DE QUITANDINHA", numero="0000032/2026", tipo="AQUISIÇÃO",
    inicio="25/09/2026 08:45", fim="13/10/2026 08:45",
    link="https://bllcompras.com/Process/ProcessView?param1=[gkz]J_M1_dkTHDNbMXB6M3tAJPXR0Isp0aI6cIi62CGkHU0s6aOCNI7vD5xjgRliMyi0XElbV3jpQxOOqVwhIFlLofP8/8Sbg8okOdtMgwSE/RE=",
    objeto="CONTRATAÇÃO DE EMPRESA ESPECIALIZADA NA PRESTAÇÃO DOS SERVIÇOS DE FORNECIMENTO E GERENCIAMENTO DE "
           "VALE-REFEIÇÃO POR MEIO DE CARTÃO ELETRÔNICO/MAGNÉTICO COM CHIP DE SEGURANÇA E SENHA INDIVIDUAL",
) + """
</tbody></table><br />
<table bgcolor="#024638"><tr><td>
<div><span style="color: #ffffff">Suporte ao Fornecedor<br />(41) 3097-4600<br />contato@bll.org.br</span></div>
<div><span style="color: #ffffff">Suporte à Prefeitura<br />(41) 3148-9870<br />contatoorgaos@bll.org.br</span></div>
<a href="https://www.facebook.com/bllcompras">Facebook</a>
</td></tr></table>
</td></tr></table></div></center></blockquote></div></body></html>"""

BLL_TEXTO = """Bom dia, segue para análise de viabilidade.

At.te

---------- Mensagem encaminhada ----------
De: BLLCOMPRAS <avisos@bllcompras.com>
Data: 2 de out. de 2026, 02:47 -0300
Para: dario.ribeiro@prosperapagamentos.com
Assunto: Divulgador de editais

> Divulgador de editais
>
> SÃO PAULO
> SANTOS - SP
> CAIXA DE ASSISTENCIA AO SERVIDOR PUBLICO MUNICIPAL DE SANTOS
>
> PREGÃO ELETRÔNICO
> 014/2026
> AQUISIÇÃO PARCELADA
> Início Propostas: 11/08/2026 16:00
> Fim Propostas: 23/10/2026 09:00
> Acessar Processo
> OBJETO
> CONTRATAÇÃO DE INSTITUIÇÃO FINANCEIRA, PÚBLICA OU PRIVADA, PARA A PRESTAÇÃO DE SERVIÇOS BANCÁRIOS, compreendendo o processamento e crédito em conta da Folha de pagamento da Caixa de Assistência ao Servidor Público Municipal de Santos – CAPEP-SAÚDE
>
> BASTOS - SP
> MUNICIPIO DE BASTOS
>
> PREGÃO ELETRÔNICO
> 043/2026
> AQUISIÇÃO PARCELADA
> Início Propostas: 02/10/2026 08:00
> Fim Propostas: 21/10/2026 08:00
> Acessar Processo
> OBJETO
> LOCAÇÃO DE SOFTWARE PARA ADMINISTRAÇÃO, GERENCIAMENTO, EMISSÃO DE VALE ALIMENTAÇÃO EM CARTÃO MAGNÉTICO PARA OS SERVIDORES PÚBLICOS DA PREFEITURA.
>
>
> PARANÁ
> QUITANDINHA - PR
> MUNICIPIO DE QUITANDINHA
>
> PREGÃO ELETRÔNICO
> 0000032/2026
> AQUISIÇÃO
> Início Propostas: 25/09/2026 08:45
> Fim Propostas: 13/10/2026 08:45
> Acessar Processo
> OBJETO
> CONTRATAÇÃO DE EMPRESA ESPECIALIZADA NA PRESTAÇÃO DOS SERVIÇOS DE FORNECIMENTO E GERENCIAMENTO DE VALE-REFEIÇÃO POR MEIO DE CARTÃO ELETRÔNICO/MAGNÉTICO COM CHIP DE SEGURANÇA E SENHA INDIVIDUAL
>
>
> Suporte ao Fornecedor
> (41) 3097-4600
> contato@bll.org.br
"""

_AWS = ("https://h60533f.r.sa-east-1.awstrack.me/L0/https:%2F%2Fwww.portaldecompraspublicas.com.br%2F18%2F"
        "Processos%2F{uf}%2F{orgao}%2F{codigo}%2F%3Futm_source=email_aviso%26utm_campaign=JL_02%2F10%2F2026"
        "/1/010301a0fc1d3031-11d98c24-be0d-40b6-9141-33f9cb622fdc-000000/ELCsONMbj8CjaTE4-Txd1dYPMOg=258")

_PCP_ITEM = ("<p class='processo' style='display: block;'><b><a style='color: #15a8bc' href='{link}' target='_blank' "
             "rel='noopener' title='Ver detalhes'>{objeto}</a></b><br />\r\n{data}<br />\r\n{orgao}</p>\r\n")

PCP_ITENS = [
    dict(uf="SC", orgao="Servico-Intermunicipal-de-Agua-e-Esgoto-SIMAE-CAO-2515", codigo="PE-PE6-2026-2026-512696",
         objeto="Contratação de empresa especializada na administração, gerenciamento, emissão, distribuição e "
                "fornecimento de vale-alimentação, na forma de cartão eletrônico dotado de tecnologia de chip com "
                "senha pessoal, preferencialmente com funcionalidade de...",
         data="06/10/2026 às 07:55", nome="Serviço Intermunicipal de Água e Esgoto - SIMAE/CAO"),
    dict(uf="GO", orgao="Prefeitura-Municipal-de-Senador-Canedo-992", codigo="CRED-04-2025-2025-422207",
         objeto="CREDENCIAMENTO DE INSTITUIÇÕES FINANCEIRAS PARA PRESTAÇÃO DE SERVIÇOS BANCÁRIOS PARA RECOLHIMENTO "
                "DE TRIBUTOS E DEMAIS RECEITAS PÚBLICAS MUNICIPAIS POR MEIO DE DUAM - DOCUMENTO ÚNICO DE ARRECADAÇÃO "
                "MUNICIPAL (DOCUMENTO EMITIDO PELO MUNICÍPIO), EM...",
         data="06/10/2026 às 23:59", nome="Prefeitura Municipal de Senador Canedo"),
    dict(uf="RS", orgao="Prefeitura-Municipal-de-Parobe-797", codigo="PMP-71-2026-2026-511340",
         objeto="Contratação de empresa especializada para administração, gerenciamento, emissão e fornecimento de "
                "cartões eletrônicos de vale-alimentação aos servidores municipais de Parobé/RS.",
         data="07/10/2026 às 07:59", nome="Prefeitura Municipal de Parobé"),
    dict(uf="RS", orgao="Camara-Municipal-de-Uruguaiana-3348", codigo="PE-5-2026-2026-514249",
         objeto="Gerenciamento, administração, emissão e disponibilização de créditos de auxílio-alimentação, por "
                "cartões eletrônicos, magnéticos e/ou tecnologia equivalente, que possuam marca de uma rede (bandeira) "
                "de processamento de transações, dotados de chip de...",
         data="13/10/2026 às 00:01", nome="Câmara Municipal de Uruguaiana"),
]

PCP_HTML = """<html><body>
<div name="messageBodySection"><div>Bom dia, segue para análise de viabilidade.&#160;</div><div>At.te&#160;</div></div>
<div name="messageReplySection">---------- Mensagem encaminhada ----------<br />
<b>De:</b> Portal de Compras Publicas &lt;falecom@portaldecompraspublicas.com.br&gt;<br />
<b>Assunto:</b> Alerta de Licitações - PROSPERA INSTITUICAO DE PAGAMENTO S.A, hoje temos 11 oportunidades para você.<br /><br />
<blockquote type="cite"><center style='width: 100%;'>
<table align='center' width='600'><tr><td>
<div style='padding: 20px 40px 0px;'><a href='http://h60533f.r.sa-east-1.awstrack.me/L0/'><img src='https://portalcpstorage.s3.sa-east-1.amazonaws.com/files/Banner/Aviso+de+Licita%C3%A7%C3%B5es.png' alt='' /></a></div>
<div style='background: #fff; padding: 25px 40px 0px;'>
<h1>Aviso de Licitações</h1>
<span><b>IMPORTANTE:</b> Você se inscreveu para receber oportunidades de: <span>ES, <span>GO, <span>RS, <span>SC, <span>SP.</span> Caso queira <b>reconfigurar</b> seus avisos de licitações, <a href='https://h60533f.r.sa-east-1.awstrack.me/L0/https:%2F%2Foperacao.portaldecompraspublicas.com.br%2F18%2Floginext%2F/1/x/y=258'>clique aqui.</a></span>
<span>Olá, PROSPERA INSTITUICAO DE PAGAMENTO S.A, selecionamos alguns processos de licitações que acreditamos ser do seu interesse.<br /><br />
Estamos usando a Inteligência Artificial (IA) para melhorar sua experiência e a busca por processos mais assertivos.</span><span class='avisoRobo'><img class='robo' width='57px' height='64px' src='https://portalcpstorage.s3.sa-east-1.amazonaws.com/files/Assets/mail/icones/robo-principal.png' />Toda vez que nossa IA encontrar um processo,<br />
esse robô<img class='icoRobo' width='24' height='26' src='https://x/robo-secundario.png' />aparecerá ao lado!</span>
""" + "".join(
    _PCP_ITEM.format(link=_AWS.format(uf=i["uf"], orgao=i["orgao"], codigo=i["codigo"]),
                     objeto=i["objeto"], data=i["data"], orgao=i["nome"])
    for i in PCP_ITENS
) + """
<p style='display: block;'>Temos, ao todo, <b style='color: #15a8bc; font-size: 25px'>11</b> processos cadastrados nas suas linhas de fornecimento e UF(s) escolhida(s).</p>
</span></span></span></span></span>
<div style='text-align: center'><a href='https://h60533f.r.sa-east-1.awstrack.me/L0/https:%2F%2Foperacao.portaldecompraspublicas.com.br%2F18%2Floginext%2F/1/x/z=258'>VER MAIS<br />OPORTUNIDADES</a></div>
</div>
<div style='padding: 25px 40px;'><p>Central de atendimento: 3003-5455 / <a href='https://h60533f.r.sa-east-1.awstrack.me/L0/https:%2F%2Fmail.google.com%2F/1/x/w=258'>falecom@portaldecompraspublicas.com.br</a></p></div>
</td></tr></table></center></blockquote></div></body></html>"""

PCP_TEXTO = """Bom dia, segue para análise de viabilidade.

---------- Mensagem encaminhada ----------
De: Portal de Compras Publicas <falecom@portaldecompraspublicas.com.br>
Assunto: Alerta de Licitações - PROSPERA INSTITUICAO DE PAGAMENTO S.A, hoje temos 11 oportunidades para você.

> Aviso de Licitações IMPORTANTE: Você se inscreveu para receber oportunidades de: ES, GO, MG, MS, MT, PR, RJ, RS, SC, SP. Caso queira reconfigurar seus avisos de licitações, clique aqui.
>
> Olá, PROSPERA INSTITUICAO DE PAGAMENTO S.A, selecionamos alguns processos de licitações que acreditamos ser do seu interesse.
>
> Estamos usando a Inteligência Artificial (IA) para melhorar sua experiência e a busca por processos mais assertivos.Toda vez que nossa IA encontrar um processo,
> esse robôaparecerá ao lado!
""" + "".join(f"> {i['objeto']}\n> {i['data']}\n> {i['nome']}\n" for i in PCP_ITENS) + """> Temos, ao todo, 11 processos cadastrados nas suas linhas de fornecimento e UF(s) escolhida(s).
> VER MAIS
> OPORTUNIDADES
> Central de atendimento: 3003-5455 / falecom@portaldecompraspublicas.com.br
"""


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def test_parse_bll_html_e_texto():
    linhas = html_para_linhas(BLL_HTML)
    assert identificar_boletim("Fwd: Divulgador de editais", linhas) == "bll"
    itens = parse_bll(linhas)
    assert len(itens) == 3, [i.como_dict() for i in itens]

    santos, bastos, quitandinha = itens
    assert (santos.municipio, santos.uf) == ("Santos", "SP")
    assert santos.orgao == "Caixa de Assistencia ao Servidor Publico Municipal de Santos"
    assert santos.modalidade == "Pregão Eletrônico"
    assert santos.numero_certame == "14/2026"
    assert santos.data_abertura == "2026-08-11T16:00:00"
    assert santos.data_encerramento == "2026-10-23T09:00:00"
    assert santos.link.startswith("https://bllcompras.com/Process/ProcessView?param1=")
    assert santos.objeto.startswith("CONTRATAÇÃO DE INSTITUIÇÃO FINANCEIRA")
    assert santos.extras.get("tipo") == "AQUISIÇÃO PARCELADA"
    assert bastos.objeto.startswith("LOCAÇÃO DE SOFTWARE")
    assert (quitandinha.municipio, quitandinha.uf, quitandinha.numero_certame) == ("Quitandinha", "PR", "32/2026")
    assert quitandinha.chave == "bll:PR:quitandinha:32/2026"

    # Texto colado do Gmail: mesmos itens (sem links), mesmas chaves
    do_texto = parse_bll(texto_para_linhas(BLL_TEXTO))
    assert [i.chave for i in do_texto] == [i.chave for i in itens]
    assert all(i.link == "" for i in do_texto)
    assert do_texto[2].objeto == quitandinha.objeto
    print("OK: BLL — 3 itens do HTML e do texto colado, campos e chaves estáveis")


def test_parse_pcp_html_e_texto():
    linhas = html_para_linhas(PCP_HTML)
    assert identificar_boletim("Fwd: Alerta de Licitações - PROSPERA, hoje temos 11 oportunidades", linhas) == "pcp"
    itens = parse_pcp(linhas)
    assert len(itens) == 4, [i.como_dict() for i in itens]

    simae, canedo, parobe, uruguaiana = itens
    assert (simae.uf, simae.chave) == ("SC", "pcp:512696")
    assert simae.orgao == "Serviço Intermunicipal de Água e Esgoto - SIMAE/CAO"
    assert simae.data_encerramento == "2026-10-06T07:55:00"
    assert (canedo.uf, canedo.municipio, canedo.modalidade, canedo.numero_certame) == \
        ("GO", "Senador Canedo", "Credenciamento", "4/2025")
    assert parobe.link == ("https://www.portaldecompraspublicas.com.br/18/Processos/RS/"
                           "Prefeitura-Municipal-de-Parobe-797/PMP-71-2026-2026-511340/")
    assert (parobe.uf, parobe.municipio, parobe.numero_certame, parobe.chave) == ("RS", "Parobé", "71/2026", "pcp:511340")
    assert (uruguaiana.modalidade, uruguaiana.numero_certame, uruguaiana.municipio) == \
        ("Pregão Eletrônico", "5/2026", "Uruguaiana")
    assert uruguaiana.objeto.endswith("...")

    # Texto colado: sem URL não há id do PCP, mas município/UF saem do órgão e do objeto
    do_texto = parse_pcp(conteudo_para_linhas(PCP_TEXTO))
    assert len(do_texto) == 4
    assert (do_texto[2].municipio, do_texto[2].uf) == ("Parobé", "RS")
    assert do_texto[3].municipio == "Uruguaiana" and do_texto[3].uf == ""
    assert all(i.chave.startswith("pcp:") for i in do_texto)
    print("OK: PCP — 4 itens do HTML (URL desembrulhado, UF/id/número) e do texto colado")


# ---------------------------------------------------------------------------
# Casamento com a base + triagem + importação + enriquecimento pela coleta
# ---------------------------------------------------------------------------

class _IAFalsa:
    """Aderente quando o objeto fala de alimentação/benefício em cartão."""

    chamadas: list = []

    def triar_emails(self, itens, perfil):
        _IAFalsa.chamadas.append(len(itens))
        saida = []
        for i, it in enumerate(itens):
            obj = it["objeto"].lower()
            ok = "aliment" in obj or "refei" in obj or "benef" in obj
            saida.append(AvaliacaoItemEmail(indice=i, aderente=ok, score=8 if ok else 1,
                                            motivo="objeto de VA/VR em cartão" if ok else "serviço bancário"))
        return saida


def _licitacao_pncp_parobe():
    return Licitacao(
        fonte="pncp", id_externo="87123456000199-1-000071/2026", orgao="MUNICIPIO DE PAROBE",
        municipio="Parobé", uf="RS", modalidade="Pregão - Eletrônico",
        objeto="[Portal de Compras Públicas] - Contratação de empresa especializada para administração, "
               "gerenciamento, emissão e fornecimento de cartões eletrônicos de vale-alimentação aos "
               "servidores municipais de Parobé/RS.",
        valor_estimado=1200000.0, data_encerramento="2026-10-07T07:59:00",
        link="https://pncp.gov.br/app/editais/87123456000199/2026/71",
        edital_url="https://pncp.gov.br/pncp-api/v1/orgaos/87123456000199/compras/2026/71/arquivos",
        sistema="Portal de Compras Publicas",
        endereco_licitacao="https://www.portaldecompraspublicas.com.br/18/Processos/RS/Prefeitura-Municipal-de-Parobe-797/PMP-71-2026-2026-511340/",
        raw_json={"numeroCompra": "71", "anoCompra": 2026},
    )


def test_agente_fim_a_fim():
    _banco_limpo()
    db = TestingSession()
    db.add(PerfilEmpresa(id=1, **PERFIL_PADRAO))
    db.add(_licitacao_pncp_parobe())
    db.commit()

    with patch.object(servico, "criar_analisador", lambda: _IAFalsa()), \
         patch.object(servico, "provedor_ativo", lambda: "falsa"):
        email = servico.processar_boletim(
            db, gmail_id="msg-pcp-1", assunto="Fwd: Alerta de Licitações - PROSPERA, hoje temos 11 oportunidades",
            remetente="dario@x", recebido_em=None, html=PCP_HTML, origem="gmail",
        )
        assert email is not None and email.tipo == "pcp" and email.total_itens == 4
        por_chave = {i.chave: i for i in email.itens}
        # Parobé já estava na base (coleta PNCP) -> sinalizado, não duplicado
        assert por_chave["pcp:511340"].situacao == "ja_na_base"
        assert por_chave["pcp:511340"].licitacao_id is not None
        # Senador Canedo (GO) -> fora das UFs do perfil, sem gastar IA
        assert por_chave["pcp:422207"].situacao == "fora_do_perfil"
        assert "GO" in por_chave["pcp:422207"].motivo
        # SIMAE (SC) e Uruguaiana (RS) aguardam a IA
        assert {por_chave["pcp:512696"].situacao, por_chave["pcp:514249"].situacao} == {"novo"}

        triagem = servico.triar_pendentes(db)
        assert triagem["triados"] == 2 and triagem["importadas"] == 2, triagem
        assert _IAFalsa.chamadas[-1] == 2  # UMA chamada para o lote

        importadas = db.execute(select(Licitacao).where(Licitacao.fonte == "email_dario")).scalars().all()
        assert len(importadas) == 2
        uru = next(l for l in importadas if l.id_externo == "pcp:514249")
        assert uru.status_analise == "pendente"           # pipeline analisa pelo link do portal
        assert uru.sistema == "Portal de Compras Publicas"
        assert uru.endereco_licitacao.endswith("PE-5-2026-2026-514249/")
        assert uru.raw_json["triagem_score"] == 8
        assert db.execute(select(Oportunidade).where(Oportunidade.licitacao_id == uru.id)).scalar_one().estagio == "identificada"
        db.refresh(por_chave["pcp:514249"])
        assert por_chave["pcp:514249"].situacao == "importada"
        assert por_chave["pcp:514249"].licitacao_id == uru.id

        # Mesmo boletim no dia seguinte: tudo "repetido", herdando as decisões
        de_novo = servico.processar_boletim(
            db, gmail_id="msg-pcp-2", assunto="Fwd: Alerta de Licitações", remetente="dario@x",
            recebido_em=None, html=PCP_HTML,
        )
        assert {i.situacao for i in de_novo.itens} == {"repetido"}
        rep = next(i for i in de_novo.itens if i.chave == "pcp:514249")
        assert rep.licitacao_id == uru.id
        assert servico.processar_boletim(db, gmail_id="msg-pcp-2", assunto="", remetente="",
                                         recebido_em=None, html=PCP_HTML) is None  # já processado

        # BLL colado em texto: Quitandinha (PR) aderente; Santos/Bastos (SP) fora do perfil pela UF
        bll = servico.processar_boletim(
            db, gmail_id="colado-1", assunto="", remetente="colado", recebido_em=None,
            texto=BLL_TEXTO, origem="colado",
        )
        assert bll.tipo == "bll" and bll.total_itens == 3
        servico.triar_pendentes(db)
        por_chave = {i.chave: i for i in bll.itens}
        assert por_chave["bll:PR:quitandinha:32/2026"].situacao == "importada"
        assert por_chave["bll:SP:santos:14/2026"].situacao == "fora_do_perfil"
        assert por_chave["bll:SP:bastos:43/2026"].situacao == "fora_do_perfil"

        # Importação forçada pelo time de um item fora do perfil
        lic_bastos = servico.importar_item(db, por_chave["bll:SP:bastos:43/2026"], forcado=True, por="Henrique",
                                           motivo="Importada manualmente por Henrique")
        assert lic_bastos.fonte == "email_dario" and lic_bastos.raw_json["importacao_forcada"] is True
        assert por_chave["bll:SP:bastos:43/2026"].situacao == "importada"

    # ---- A coleta do PNCP encontra a licitação de Uruguaiana depois: enriquece, não duplica ----
    coletada = LicitacaoColetada(
        fonte="pncp", id_externo="88000000000100-1-000005/2026", orgao="CAMARA MUNICIPAL DE URUGUAIANA",
        municipio="Uruguaiana", uf="RS", modalidade="Pregão - Eletrônico",
        objeto="[Portal de Compras Públicas] - Gerenciamento, administração, emissão e disponibilização de "
               "créditos de auxílio-alimentação, por cartões eletrônicos, magnéticos e/ou tecnologia equivalente, "
               "que possuam marca de uma rede (bandeira) de processamento de transações, dotados de chip de "
               "segurança, para os servidores da Câmara Municipal de Uruguaiana.",
        valor_estimado=350000.0, data_abertura="2026-09-30T08:00:00", data_encerramento="2026-10-13T00:01:00",
        link="https://pncp.gov.br/app/editais/88000000000100/2026/5",
        edital_url="https://pncp.gov.br/pncp-api/v1/orgaos/88000000000100/compras/2026/5/arquivos",
        sistema="Portal de Compras Publicas", endereco_licitacao="",
        raw={"numeroCompra": "5", "anoCompra": 2026},
    )

    class ColetorFalso:
        fonte = "pncp"
        falhas = 0

        def coletar(self, ufs, palavras, dias=3):
            return [coletada]

    with patch.object(pipeline, "coletores_ativos", lambda s: [ColetorFalso()]):
        resultado = pipeline.executar_coleta(db, dias=3)
    assert resultado["novas_licitacoes"] == 0
    assert resultado.get("cards_de_email_enriquecidos") == 1, resultado
    assert db.execute(select(Licitacao).where(Licitacao.fonte == "pncp",
                                              Licitacao.id_externo == coletada.id_externo)).scalar_one_or_none() is None
    db.refresh(uru)
    assert uru.edital_url == coletada.edital_url
    assert uru.valor_estimado == 350000.0
    assert uru.link.startswith("https://pncp.gov.br/app/editais/")
    assert uru.status_analise == "pendente"
    assert uru.raw_json["fonte_publica_id_externo"] == coletada.id_externo
    item_uru = db.execute(select(ItemEmail).where(ItemEmail.licitacao_id == uru.id,
                                                  ItemEmail.situacao == "importada")).scalars().first()
    assert "Localizada depois na coleta" in item_uru.motivo
    db.close()
    print("OK: agente fim a fim — já na base, UF fora, triagem em lote, importação, repetidos, "
          "colado em texto, importação forçada e enriquecimento pela coleta do PNCP")


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

ADMIN_EMAIL = "admin-emails@teste.com"
ADMIN_SENHA = "senha-inicial"


def _aguardar_job(cliente, job_id, segundos=20):
    fim = time.time() + segundos
    while time.time() < fim:
        job = cliente.get(f"/api/extracoes/{job_id}").json()
        if job["status"] != "processando":
            return job
        time.sleep(0.1)
    raise AssertionError("job não terminou")


def test_rotas_emails():
    _banco_limpo()
    override_anterior = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = _get_db_teste
    try:
        settings.admin_email = ADMIN_EMAIL
        settings.admin_senha_inicial = ADMIN_SENHA
        db = TestingSession()
        security.bootstrap_admin(db)
        db.add(PerfilEmpresa(id=1, **PERFIL_PADRAO))
        db.commit()
        db.close()

        cliente = TestClient(app)
        assert cliente.post("/api/auth/login", json={"email": ADMIN_EMAIL, "senha": ADMIN_SENHA}).status_code == 200

        r = cliente.get("/api/emails/status")
        assert r.status_code == 200 and r.json()["gmail_configurado"] is False

        # Sem Gmail configurado, sincronizar avisa (409) em vez de falhar no meio
        assert cliente.post("/api/emails/sincronizar").status_code == 409

        with patch("app.database.SessionLocal", TestingSession), \
             patch.object(servico, "criar_analisador", lambda: _IAFalsa()), \
             patch.object(servico, "provedor_ativo", lambda: "falsa"):
            r = cliente.post("/api/emails/colar", json={"conteudo": PCP_TEXTO, "assunto": "Alerta de Licitações"})
            assert r.status_code == 202, r.text
            job = _aguardar_job(cliente, r.json()["job_id"])
            assert job["status"] == "pronto", job
            resultado = job["resultado"]
            assert resultado["email"]["tipo"] == "pcp" and resultado["email"]["total_itens"] == 4
            # Texto colado não traz UF (sem URL): os 4 vão à IA — 3 de VA/VR aderentes, Canedo (DUAM) fora
            assert (resultado["importadas"], resultado["fora_do_perfil"]) == (3, 1), resultado

            # Colar o mesmo conteúdo de novo -> 409 (já processado)
            r = cliente.post("/api/emails/colar", json={"conteudo": PCP_TEXTO})
            job = _aguardar_job(cliente, r.json()["job_id"])
            assert job["status"] == "erro" and job["codigo"] == 409

            # Conteúdo que não é boletim -> 422 com explicação
            r = cliente.post("/api/emails/colar", json={"conteudo": "Oi Henrique, " * 10})
            job = _aguardar_job(cliente, r.json()["job_id"])
            assert job["status"] == "erro" and job["codigo"] == 422

        r = cliente.get("/api/emails")
        assert r.status_code == 200
        emails = [e for e in r.json() if e["tipo"] == "pcp"]
        assert emails, r.json()
        itens = emails[0]["itens"]
        fora = next(i for i in itens if i["situacao"] == "fora_do_perfil")
        importada = next(i for i in itens if i["situacao"] == "importada")

        # Importar mesmo assim -> vira card; o card aparece em /api/licitacoes com fonte email_dario
        r = cliente.post(f"/api/emails/itens/{fora['id']}/importar")
        assert r.status_code == 200, r.text
        assert r.json()["situacao"] == "importada" and r.json()["licitacao_id"]
        lic = cliente.get(f"/api/licitacoes/{r.json()['licitacao_id']}").json()
        assert lic["fonte"] == "email_dario" and lic["status_analise"] == "pendente"
        ops = cliente.get("/api/oportunidades").json()
        assert any(o["licitacao"]["id"] == lic["id"] for o in ops)

        # Já importada -> 409; ignorar item importado -> 409
        assert cliente.post(f"/api/emails/itens/{importada['id']}/importar").status_code == 409
        assert cliente.post(f"/api/emails/itens/{importada['id']}/ignorar").status_code == 409

        status = cliente.get("/api/emails/status").json()
        assert status["total_emails"] >= 1 and status["por_situacao"].get("importada", 0) >= 2
        print("OK: rotas — status, colar (202 + job), duplicado 409, não-boletim 422, listar, importar, ignorar")
    finally:
        if override_anterior:
            app.dependency_overrides[get_db] = override_anterior
        else:
            app.dependency_overrides.pop(get_db, None)


if __name__ == "__main__":
    test_parse_bll_html_e_texto()
    test_parse_pcp_html_e_texto()
    test_agente_fim_a_fim()
    test_rotas_emails()
