"""Base compartilhada para portais de compras do Sistema S na plataforma Paradigma WBC.

FIESC, FIERGS e FIEMS usam o mesmo software ("Portal de Compras", Paradigma WBC):
a página pública é /portal/Mural.aspx e a lista de processos vem de um web service
ASMX que responde JSON (bem mais estável que raspar o HTML):

    POST {base_url}/portal/WebService/Servicos.asmx/PesquisarProcessos
    Content-Type: application/json; charset=utf-8
    Body: {"dtoProcesso": {...}}  ->  resposta: {"d": [ {CWMuralProcesso}, ... ]}

Duas "visões" interessam (campo tmpTipoMuralProcesso):
- 0 (MURAL):  processos em andamento, com data de abertura e de encerramento.
- 2 (EDITAL): editais publicados (pega os recém-publicados/agendados que ainda
  não aparecem no mural). Deduplicado pelo número do processo.

Particularidades do payload (sentinelas de "nulo" do serializador .NET):
- string nula  -> "\\x13\\x12\\x12\\x13"
- int nulo     -> -2147483648
- data         -> "/Date(<ms epoch>)/"; DateTime.MinValue (negativo) = sem data.

Paginação por faixa de registros: dtoPaginacao {nPaginaDe: 1, nPaginaAte: 50},
depois {51, 100}, ... (mesma lógica do scroll infinito da página).

Cada portal concreto (fiesc.py, fiergs.py, fiems.py) só define fonte, uf,
base_url, orgao_padrao e fuso horário.
"""
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from .base import BaseCollector, LicitacaoColetada

logger = logging.getLogger(__name__)

# Sentinelas de nulo do Paradigma/.NET
NULO_STR = "\x13\x12\x12\x13"
NULO_INT = -2147483648

TIPO_MURAL = 0   # processos em andamento (tem data de encerramento)
TIPO_EDITAL = 2  # editais publicados (tem data de publicação)

TIMEOUT = 30
TENTATIVAS_ESPERA = [2, 6]       # backoff entre tentativas (total: 3 tentativas)
PAUSA_ENTRE_REQUISICOES = 1.0    # pausa preventiva entre requisições
TAMANHO_PAGINA = 50
MAX_PAGINAS = 10                 # teto de segurança por visão (10 x 50 = 500 registros)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json",
    "Content-Type": "application/json; charset=utf-8",
}

RE_DATE_MS = re.compile(r"/Date\((-?\d+)\)/")


class ParadigmaMuralCollector(BaseCollector):
    """Coletor genérico de um Portal de Compras Paradigma WBC. Não usar direto;
    subclasses definem os atributos abaixo."""

    fonte = "paradigma"
    base_url = ""      # ex.: https://portaldecompras.fiesc.com.br (sem barra final)
    uf = ""            # UF fixa do portal; se não estiver em `ufs`, retorna []
    orgao_padrao = ""  # usado quando o payload não traz o nome da entidade
    fuso_horas = -3    # fuso do portal (RS/SC/PR: -3; MS: -4)

    def __init__(self):
        self.falhas = 0  # requisições que falharam mesmo após retries

    # ---------- coleta ----------

    def coletar(self, ufs, palavras_chave, dias=3):
        self.falhas = 0
        if self.uf.upper() not in {(u or "").strip().upper() for u in ufs}:
            return []

        fuso = timezone(timedelta(hours=self.fuso_horas))
        agora = datetime.now(fuso)
        corte = agora - timedelta(days=dias)

        vistos: set[str] = set()
        resultados: list[LicitacaoColetada] = []

        with httpx.Client(timeout=TIMEOUT, headers=HEADERS) as client:
            for tipo in (TIPO_MURAL, TIPO_EDITAL):
                for item in self._coletar_visao(client, tipo, corte, agora):
                    lic = self._normalizar(item, tipo)
                    if lic.id_externo in vistos:
                        continue
                    vistos.add(lic.id_externo)
                    texto = f"{lic.objeto} {_limpar(item.get('sDsTitulo'))}"
                    if palavras_chave and not self.bate_palavra_chave(texto, palavras_chave):
                        continue
                    resultados.append(lic)

        logger.info("%s: %d licitações após filtros (%d requisições falharam)",
                    self.fonte, len(resultados), self.falhas)
        return resultados

    def _coletar_visao(self, client: httpx.Client, tipo: int,
                       corte: datetime, agora: datetime) -> list[dict]:
        """Pagina uma visão do mural, parando quando os registros saem do período."""
        itens: list[dict] = []
        for pagina in range(MAX_PAGINAS):
            if pagina:
                time.sleep(PAUSA_ENTRE_REQUISICOES)
            de = pagina * TAMANHO_PAGINA + 1
            dados = self._post_com_retry(client, self._montar_dto(tipo, de, de + TAMANHO_PAGINA - 1))
            if not dados:
                break
            uteis = [x for x in dados if self._no_periodo(x, corte, agora)]
            itens.extend(uteis)
            if len(dados) < TAMANHO_PAGINA:
                break  # última página
            if not uteis:
                break  # página inteira fora do período (listas vêm ordenadas por recência)
        return itens

    def _montar_dto(self, tipo: int, pagina_de: int, pagina_ate: int) -> dict:
        return {"dtoProcesso": {
            "nAnoFinalizacao": 0,
            "tmpTipoMuralProcesso": tipo,
            "nCdModulo": 0,
            "nCdModalidade": 0,
            "nCdModalidadeFase": 0,
            "nCdTipoModalidade": 0,
            "tmpTipoMuralVisao": 0,
            "nCdSituacao": 0,
            "nCdTipoProcesso": 0,
            "nCdEmpresa": 0,
            "sNrProcesso": "",
            "nCdProcesso": 0,
            "sDsObjeto": "",
            "sDtPeriodoDe": "",
            "sDtPeriodoAte": "",
            "sOrdenarPor": "TDTFINAL" if tipo == TIPO_MURAL else "NCDPROCESSO",
            "sOrdenarPorDirecao": "DESC",
            "dtoPaginacao": {"nPaginaDe": pagina_de, "nPaginaAte": pagina_ate},
            "dtoIdioma": {"nCdIdioma": 1},
            "bAbreItemAutomatico": False,
        }}

    def _post_com_retry(self, client: httpx.Client, corpo: dict) -> list[dict] | None:
        url = f"{self.base_url}/portal/WebService/Servicos.asmx/PesquisarProcessos"
        espera = 0.0
        for tentativa in range(1 + len(TENTATIVAS_ESPERA)):
            if espera:
                time.sleep(espera)
            try:
                resp = client.post(url, json=corpo)
                resp.raise_for_status()
                dados = resp.json().get("d")
                if not isinstance(dados, list):
                    raise ValueError(f"resposta inesperada: {str(dados)[:200]}")
                return dados
            except Exception as exc:
                espera = TENTATIVAS_ESPERA[tentativa] if tentativa < len(TENTATIVAS_ESPERA) else 0
                logger.warning("%s tentativa %d falhou: %s", self.fonte, tentativa + 1, exc)
        self.falhas += 1
        return None

    # ---------- período ----------

    def _no_periodo(self, item: dict, corte: datetime, agora: datetime) -> bool:
        """Mantém o que ainda está em disputa (encerramento no futuro) ou o que
        foi publicado nos últimos `dias` (abertura >= corte)."""
        ini = self._parse_data(item.get("tDtInicial"))
        fim = self._parse_data(item.get("tDtFinal"))
        if fim is not None and fim >= agora:
            return True
        if ini is not None and ini >= corte:
            return True
        return ini is None and fim is None  # sem datas: mantém (o filtro de palavras decide)

    def _parse_data(self, valor) -> datetime | None:
        m = RE_DATE_MS.search(valor or "")
        if not m:
            return None
        ms = int(m.group(1))
        if ms <= 0:  # DateTime.MinValue = sem data
            return None
        return datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=self.fuso_horas)))

    # ---------- normalização ----------

    def _normalizar(self, item: dict, tipo: int) -> LicitacaoColetada:
        numero = _limpar(item.get("sNrProcessoDisplay")) or _limpar(item.get("sNrEdital"))
        n_cd_processo = _int(item.get("nCdProcesso"))
        n_cd_edital = _int(item.get("nCdEdital"))

        if tipo == TIPO_EDITAL:
            link = f"{self.base_url}/portal/Mural.aspx?nNmTela=E&nCdEdital={n_cd_edital or n_cd_processo}"
        else:
            link = f"{self.base_url}/portal/Mural.aspx?nCdProcesso={n_cd_processo}"

        ini = self._parse_data(item.get("tDtInicial"))
        fim = self._parse_data(item.get("tDtFinal"))
        valor = item.get("dVlEstimado")

        return LicitacaoColetada(
            fonte=self.fonte,
            id_externo=numero or f"proc-{n_cd_processo}",
            orgao=_limpar(item.get("sNmEmpresa")) or _limpar(item.get("sNmApelido")) or self.orgao_padrao,
            municipio="",  # o mural não informa o município
            uf=self.uf,
            modalidade=_limpar(item.get("sNmModalidade")) or _limpar(item.get("sNmModalidadeTipo")),
            objeto=_limpar(item.get("sDsObjeto")) or _limpar(item.get("sDsTitulo")),
            valor_estimado=float(valor) if valor else None,
            data_abertura=ini.isoformat() if ini else "",
            data_encerramento=fim.isoformat() if fim else "",
            link=link,
            edital_url="",  # o edital só sai via chamadas autenticadas/HTML dinâmico
            raw=item,
        )


def _limpar(valor) -> str:
    """Remove as sentinelas de nulo do Paradigma e espaços sobrando."""
    if valor is None or valor == NULO_STR:
        return ""
    return str(valor).strip()


def _int(valor) -> int | None:
    if valor is None or valor == NULO_INT:
        return None
    return int(valor)
