"""Parsers dos boletins de licitação encaminhados por e-mail (aba "E-mails do Dario").

Dois formatos conhecidos (ambos encaminhados pelo Dario a partir da caixa dele):
- BLL Compras — assunto "Divulgador de editais" (avisos@bllcompras.com): blocos por
  estado, cada licitação com "CIDADE - UF", órgão, modalidade, número, tipo, datas
  de início/fim das propostas, botão "Acessar Processo" e OBJETO.
- Portal de Compras Públicas — assunto "Alerta de Licitações - <empresa>, hoje temos
  N oportunidades" (falecom@portaldecompraspublicas.com.br): lista de parágrafos
  com link (via redirecionador awstrack) + objeto (truncado com "..."), data/hora da
  sessão e nome do órgão. A UF e o id do processo saem do URL.

Estratégia: reduzir HTML OU texto colado a uma lista de LINHAS — cada link vira uma
linha "@@LINK url" — e interpretar as linhas. Um parser por portal atende os dois
formatos de entrada (HTML lido do Gmail e texto colado pela equipe, que não traz
links). Determinístico, sem IA: instantâneo e sem gastar a cota do Gemini.
"""
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote

PORTAL_BLL = "BLL"
PORTAL_PCP = "Portal de Compras Publicas"

_ESTADOS = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPÁ": "AP", "AMAPA": "AP", "AMAZONAS": "AM",
    "BAHIA": "BA", "CEARÁ": "CE", "CEARA": "CE", "DISTRITO FEDERAL": "DF",
    "ESPÍRITO SANTO": "ES", "ESPIRITO SANTO": "ES", "GOIÁS": "GO", "GOIAS": "GO",
    "MARANHÃO": "MA", "MARANHAO": "MA", "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS",
    "MINAS GERAIS": "MG", "PARÁ": "PA", "PARA": "PA", "PARAÍBA": "PB", "PARAIBA": "PB",
    "PARANÁ": "PR", "PARANA": "PR", "PERNAMBUCO": "PE", "PIAUÍ": "PI", "PIAUI": "PI",
    "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS",
    "RONDÔNIA": "RO", "RONDONIA": "RO", "RORAIMA": "RR", "SANTA CATARINA": "SC",
    "SÃO PAULO": "SP", "SAO PAULO": "SP", "SERGIPE": "SE", "TOCANTINS": "TO",
}
UFS = set(_ESTADOS.values())

_MODALIDADES_SIGLA = {
    "PE": "Pregão Eletrônico", "PP": "Pregão Presencial", "PR": "Pregão",
    "CRED": "Credenciamento", "CR": "Credenciamento", "CE": "Concorrência Eletrônica",
    "CC": "Concorrência", "CP": "Concorrência Pública", "DE": "Dispensa Eletrônica",
    "DL": "Dispensa de Licitação", "DISP": "Dispensa de Licitação",
    "INEX": "Inexigibilidade", "IN": "Inexigibilidade", "CHP": "Chamamento Público",
    "TP": "Tomada de Preços", "LE": "Leilão Eletrônico",
}

_PALAVRAS_MODALIDADE = (
    "PREGÃO", "PREGAO", "CONCORRÊNCIA", "CONCORRENCIA", "DISPENSA", "CREDENCIAMENTO",
    "INEXIGIBILIDADE", "LEILÃO", "LEILAO", "CHAMAMENTO", "TOMADA DE PRE", "CONVITE",
    "DIÁLOGO", "DIALOGO", "CONCURSO",
)

_MINUSCULAS = {"de", "do", "da", "dos", "das", "e", "em", "a", "o", "à", "ao", "no", "na"}


@dataclass
class ItemBoletim:
    """Uma licitação citada no boletim (campos no formato do CRM)."""

    portal: str
    chave: str = ""
    orgao: str = ""
    municipio: str = ""
    uf: str = ""
    modalidade: str = ""
    numero_certame: str = ""
    objeto: str = ""
    data_abertura: str = ""      # ISO (YYYY-MM-DDTHH:MM:00) ou vazio
    data_encerramento: str = ""  # ISO ou vazio
    link: str = ""
    extras: dict = field(default_factory=dict)

    def como_dict(self) -> dict:
        return {
            "portal": self.portal, "chave": self.chave, "orgao": self.orgao,
            "municipio": self.municipio, "uf": self.uf, "modalidade": self.modalidade,
            "numero_certame": self.numero_certame, "objeto": self.objeto,
            "data_abertura": self.data_abertura, "data_encerramento": self.data_encerramento,
            "link": self.link, "extras": self.extras,
        }


# ---------------------------------------------------------------------------
# HTML / texto -> linhas
# ---------------------------------------------------------------------------

class _ExtratorLinhas(HTMLParser):
    """Reduz o HTML a linhas de texto; cada <a href> vira uma linha "@@LINK url"
    logo ANTES do texto do próprio link."""

    BLOCOS = {
        "p", "div", "br", "tr", "td", "th", "li", "h1", "h2", "h3", "h4", "h5",
        "table", "blockquote", "center", "section", "article", "ul", "ol", "hr",
    }
    IGNORAR = {"script", "style", "head", "title", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.linhas: list[str] = []
        self._atual: list[str] = []
        self._ignorar = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self._ignorar += 1
            return
        if tag in self.BLOCOS or tag == "a":
            self._quebra()
        if tag == "a":
            href = (dict(attrs).get("href") or "").strip()
            if href and not href.lower().startswith(("mailto:", "cid:", "#")):
                self.linhas.append("@@LINK " + href)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self.IGNORAR:
            self._ignorar = max(0, self._ignorar - 1)
            return
        if tag in self.BLOCOS or tag == "a":
            self._quebra()

    def handle_data(self, data):
        if not self._ignorar:
            self._atual.append(data)

    def _quebra(self):
        texto = re.sub(r"\s+", " ", "".join(self._atual)).strip()
        if texto:
            self.linhas.append(texto)
        self._atual = []

    def resultado(self) -> list[str]:
        self._quebra()
        return self.linhas


def html_para_linhas(html: str) -> list[str]:
    extrator = _ExtratorLinhas()
    extrator.feed(html or "")
    return extrator.resultado()


def texto_para_linhas(texto: str) -> list[str]:
    """Texto colado do Gmail: remove os marcadores de citação ("> ") e linhas vazias.
    URLs soltas numa linha viram "@@LINK url" (quem cola o e-mail como texto às
    vezes traz os links expandidos)."""
    linhas: list[str] = []
    for bruta in (texto or "").splitlines():
        linha = re.sub(r"^(\s*>)+\s?", "", bruta).strip()
        linha = re.sub(r"\s+", " ", linha)
        if not linha:
            continue
        if re.fullmatch(r"<?https?://\S+>?", linha):
            linhas.append("@@LINK " + linha.strip("<>"))
        else:
            linhas.append(linha)
    return linhas


def conteudo_para_linhas(conteudo: str) -> list[str]:
    """HTML se parecer HTML (tags), senão texto colado."""
    if re.search(r"<\s*(html|body|table|div|p|a|br)\b", conteudo or "", re.I):
        return html_para_linhas(conteudo)
    return texto_para_linhas(conteudo)


# ---------------------------------------------------------------------------
# Identificação do boletim
# ---------------------------------------------------------------------------

def identificar_boletim(assunto: str, linhas: list[str]) -> str:
    """'bll' | 'pcp' | 'desconhecido'."""
    a = (assunto or "").lower()
    if "divulgador de editais" in a:
        return "bll"
    if "alerta de licita" in a:
        return "pcp"
    amostra = " ".join(linhas[:60]).lower()
    if "divulgador de editais" in amostra or "bllcompras.com" in amostra:
        return "bll"
    if "portaldecompraspublicas" in amostra or "aviso de licita" in amostra:
        return "pcp"
    return "desconhecido"


def parse_boletim(tipo: str, linhas: list[str]) -> list[ItemBoletim]:
    if tipo == "bll":
        return parse_bll(linhas)
    if tipo == "pcp":
        return parse_pcp(linhas)
    return []


# ---------------------------------------------------------------------------
# BLL Compras — "Divulgador de editais"
# ---------------------------------------------------------------------------

_RE_CIDADE = re.compile(r"^(.{2,80}?)\s+-\s+([A-Z]{2})$")
_RE_NUMERO = re.compile(r"^\d{1,10}\s*/\s*\d{4}$")
_RE_INICIO = re.compile(r"^In[ií]cio\s+Propostas:\s*(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}))?", re.I)
_RE_FIM = re.compile(r"^Fim\s+Propostas:\s*(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}:\d{2}))?", re.I)
_FIM_BLL = ("SUPORTE AO FORNECEDOR", "SUPORTE À PREFEITURA", "SUPORTE A PREFEITURA")


def parse_bll(linhas: list[str]) -> list[ItemBoletim]:
    itens: list[ItemBoletim] = []
    atual: ItemBoletim | None = None
    esperando_objeto = False

    for linha in linhas:
        up = linha.upper()
        if up.startswith(_FIM_BLL):
            break
        if up in _ESTADOS:
            continue  # cabeçalho do estado — a UF vem na linha "CIDADE - UF"

        m = _RE_CIDADE.match(linha)
        if m and m.group(2) in UFS and not esperando_objeto and linha.upper() == linha:
            if atual is not None:
                itens.append(_fechar_bll(atual))
            atual = ItemBoletim(portal=PORTAL_BLL, municipio=_titulo(m.group(1)), uf=m.group(2))
            continue
        if atual is None:
            continue

        if linha.startswith("@@LINK "):
            url = linha[7:]
            if "bllcompras.com" in url.lower() and "process" in url.lower():
                atual.link = url
            continue
        if esperando_objeto:
            atual.objeto = linha
            esperando_objeto = False
            continue
        if up == "OBJETO":
            esperando_objeto = True
            continue
        if up == "ACESSAR PROCESSO":
            continue
        m = _RE_INICIO.match(linha)
        if m:
            atual.data_abertura = _iso(m.group(1), m.group(2))
            continue
        m = _RE_FIM.match(linha)
        if m:
            atual.data_encerramento = _iso(m.group(1), m.group(2))
            continue
        if _RE_NUMERO.match(linha):
            atual.numero_certame = normalizar_numero(linha)
            continue
        if not atual.orgao:
            atual.orgao = _titulo(linha) if linha.upper() == linha else linha
            continue
        if not atual.modalidade and any(p in up for p in _PALAVRAS_MODALIDADE):
            atual.modalidade = _titulo(linha)
            continue
        atual.extras.setdefault("tipo", linha)

    if atual is not None:
        itens.append(_fechar_bll(atual))
    return [i for i in itens if i.objeto or i.numero_certame]


def _fechar_bll(item: ItemBoletim) -> ItemBoletim:
    base = f"{item.uf}:{_slug(item.municipio)}:{item.numero_certame or _slug(item.objeto)[:40]}"
    item.chave = f"bll:{base}"
    return item


# ---------------------------------------------------------------------------
# Portal de Compras Públicas — "Alerta de Licitações"
# ---------------------------------------------------------------------------

_RE_DATA_PCP = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+[àa]s\s+(\d{2}:\d{2})$", re.I)
# .../Processos/{UF}/{orgao-slug}-{id do órgão}/{SIGLA-numero-ano-ano}-{id do processo}/
_RE_URL_PCP = re.compile(
    r"portaldecompraspublicas\.com\.br/\d+/Processos/([A-Za-z]{2})/([^/]+?)-(\d+)/([^/?#]+?)-(\d+)(?=[/?#]|$)",
    re.I,
)
_RE_ORGAO_MUNICIPIO = re.compile(
    r"^(?:Prefeitura|Prefeitura Municipal|C[âa]mara Municipal|C[âa]mara de Vereadores|"
    r"Munic[íi]pio|Fundo Municipal de \w+)\s+(?:de|do|da)\s+(.+?)\s*(?:[-/]\s*[A-Z]{2})?$",
    re.I,
)
_RE_OBJETO_MUNICIPIO = re.compile(r"\bde\s+([A-ZÀ-Ú][\wÀ-ú'’\- ]{2,40}?)\s*/\s*([A-Z]{2})\b")


def parse_pcp(linhas: list[str]) -> list[ItemBoletim]:
    itens: list[ItemBoletim] = []
    for i, linha in enumerate(linhas):
        m = _RE_DATA_PCP.match(linha)
        if not m or i == 0:
            continue
        objeto = linhas[i - 1]
        if objeto.startswith("@@LINK ") or _RE_DATA_PCP.match(objeto):
            continue
        link = ""
        if i >= 2 and linhas[i - 2].startswith("@@LINK "):
            link = desembrulhar_link(linhas[i - 2][7:])
        orgao = ""
        if i + 1 < len(linhas) and not linhas[i + 1].startswith("@@LINK ") \
                and not _RE_DATA_PCP.match(linhas[i + 1]) and not linhas[i + 1].lower().startswith("temos, ao todo"):
            orgao = linhas[i + 1]

        item = ItemBoletim(portal=PORTAL_PCP, objeto=objeto, orgao=orgao, link=link)
        item.data_encerramento = _iso(m.group(1), m.group(2))

        pcp_id = ""
        mu = _RE_URL_PCP.search(link) if link else None
        if mu:
            item.uf = mu.group(1).upper()
            pcp_id = mu.group(5)
            item.modalidade, item.numero_certame = _codigo_pcp(mu.group(4))
            item.extras["orgao_slug"] = mu.group(2)
        item.municipio, uf_texto = _municipio_pcp(orgao, objeto)
        if not item.uf and uf_texto:
            item.uf = uf_texto
        item.chave = f"pcp:{pcp_id}" if pcp_id else "pcp:" + _hash(f"{objeto}|{orgao}|{item.data_encerramento}")
        itens.append(item)
    return itens


def _codigo_pcp(codigo: str) -> tuple[str, str]:
    """'PE-5-2026-2026' -> ('Pregão Eletrônico', '5/2026'); 'CRED-04-2025-2025' -> ('Credenciamento', '4/2025')."""
    partes = [p for p in codigo.split("-") if p]
    if len(partes) < 2:
        return "", ""
    sigla = re.sub(r"\d", "", partes[0]).upper()
    modalidade = _MODALIDADES_SIGLA.get(sigla, "")
    numero = partes[1]
    anos = [p for p in partes[2:] if re.fullmatch(r"20\d{2}", p)]
    ano = anos[-1] if anos else ""
    if numero.isdigit():
        numero = str(int(numero))
    return modalidade, f"{numero}/{ano}" if ano else numero


def _municipio_pcp(orgao: str, objeto: str) -> tuple[str, str]:
    """(município, UF) — município pelo nome do órgão ("Prefeitura Municipal de X");
    UF (e município, se faltou) por menção "de X/UF" no objeto."""
    municipio = ""
    m = _RE_ORGAO_MUNICIPIO.match(orgao or "")
    if m:
        municipio = m.group(1).strip(" -")
    uf = ""
    mo = _RE_OBJETO_MUNICIPIO.search(objeto or "")
    if mo and mo.group(2) in UFS:
        uf = mo.group(2)
        if not municipio:
            municipio = mo.group(1).strip()
    return municipio, uf


def desembrulhar_link(url: str) -> str:
    """Links do PCP passam por um redirecionador (awstrack.me/L0/<url codificado>/...).
    Devolve o URL real, sem utm. Outros links voltam como vieram."""
    m = re.search(r"/L0/([^/]+)", url or "")
    if m and "%2F" in m.group(1).upper():
        real = unquote(m.group(1))
        return real.split("?", 1)[0]
    return (url or "").strip()


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------

def normalizar_numero(texto: str) -> str:
    """'0000032/2026' -> '32/2026'; 'PE 014/2026' -> '14/2026'."""
    m = re.search(r"(\d{1,10})\s*/\s*(\d{4})", texto or "")
    if not m:
        return (texto or "").strip()
    return f"{int(m.group(1))}/{m.group(2)}"


def _iso(data_br: str, hora: str | None) -> str:
    d, m, a = data_br.split("/")
    return f"{a}-{m}-{d}T{hora or '00:00'}:00"


def _titulo(texto: str) -> str:
    palavras = []
    for i, p in enumerate((texto or "").strip().split()):
        baixo = p.lower()
        palavras.append(baixo if (i > 0 and baixo in _MINUSCULAS) else baixo.capitalize())
    return " ".join(palavras)


def _slug(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto or "") if not unicodedata.combining(c)
    )
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


def _hash(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:16]
