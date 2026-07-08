from dataclasses import dataclass, field


@dataclass
class LicitacaoColetada:
    """Formato normalizado de uma licitação, independente da fonte."""

    fonte: str
    id_externo: str
    orgao: str = ""
    municipio: str = ""
    uf: str = ""
    modalidade: str = ""
    objeto: str = ""
    valor_estimado: float | None = None
    data_abertura: str = ""      # ISO 8601
    data_encerramento: str = ""  # ISO 8601
    link: str = ""
    edital_url: str = ""
    raw: dict = field(default_factory=dict)


class BaseCollector:
    """Interface dos coletores. Cada fonte implementa `coletar`."""

    fonte = "base"

    def coletar(self, ufs: list[str], palavras_chave: list[str], dias: int = 3) -> list[LicitacaoColetada]:
        raise NotImplementedError

    @staticmethod
    def bate_palavra_chave(texto: str, palavras_chave: list[str]) -> bool:
        t = (texto or "").lower()
        return any(p.lower() in t for p in palavras_chave)
