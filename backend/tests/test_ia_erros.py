"""Mapeamento de erros da IA nas extrações por PDF (regressão do "500 Falha inesperada").

Caso real (22/07): "Preencher automaticamente" com PDF de análise devolvia
"500 Falha inesperada na leitura do PDF". Dois caminhos escapavam do tratamento:
- APIError 400 do Gemini (PDF que o provedor rejeita) → agora ErroEntradaIA → 422
  com mensagem clara (repetir não resolve);
- erro de rede do httpx (cru desde que o retry interno do SDK foi desligado)
  → agora retry curto + fallback de modelo → RuntimeError → 503 "tente novamente".

Rodar de dentro de backend/:  .venv\\Scripts\\python.exe tests\\test_ia_erros.py
(também funciona com pytest, se instalado)
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from google.genai import errors as genai_errors

from app.analyzer.gemini_analyzer import AnalisadorEditalGemini
from app.analyzer.schemas import ErroCotaIA, ErroEntradaIA


def _analisador_com_gerar(gerar):
    """Instância sem __init__ (não precisa de chave/cliente) com _gerar substituído."""
    analisador = AnalisadorEditalGemini.__new__(AnalisadorEditalGemini)
    analisador._gerar = gerar
    return analisador


def _erro_api(code: int) -> genai_errors.APIError:
    return genai_errors.APIError(code, {"error": {"message": f"erro {code}", "status": "X"}})


def test_400_vira_erro_entrada():
    analisador = _analisador_com_gerar(lambda *a, **k: (_ for _ in ()).throw(_erro_api(400)))
    try:
        analisador._gerar_com_retry(["oi"], esperas_429=[0], esperas_5xx=[0])
        raise AssertionError("deveria ter levantado ErroEntradaIA")
    except ErroEntradaIA as exc:
        assert "PDF" in str(exc)
    print("OK: APIError 400 vira ErroEntradaIA (mensagem clara, sem 'tente novamente')")


def test_erro_de_rede_persistente_vira_runtime_error():
    chamadas = []

    def gerar(*a, **k):
        chamadas.append(1)
        raise httpx.ConnectError("connection reset")

    analisador = _analisador_com_gerar(gerar)
    try:
        analisador._gerar_com_retry(["oi"], esperas_429=[0], esperas_5xx=[0])
        raise AssertionError("deveria ter levantado RuntimeError")
    except RuntimeError as exc:
        assert "tente novamente" in str(exc)
    # 1 tentativa + 1 retry por modelo (principal + fallback) = 4 chamadas
    assert len(chamadas) == 4, f"esperava 4 chamadas, houve {len(chamadas)}"
    print("OK: erro de rede persistente vira RuntimeError 'tente novamente' (com retry+fallback)")


def test_erro_de_rede_transitorio_e_absorvido():
    chamadas = []

    def gerar(*a, **k):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise httpx.ReadTimeout("timeout")
        return "resposta"

    analisador = _analisador_com_gerar(gerar)
    assert analisador._gerar_com_retry(["oi"], esperas_429=[0], esperas_5xx=[0]) == "resposta"
    print("OK: erro de rede transitório é absorvido pelo retry")


def test_429_persistente_segue_como_cota():
    analisador = _analisador_com_gerar(lambda *a, **k: (_ for _ in ()).throw(_erro_api(429)))
    try:
        analisador._gerar_com_retry(["oi"], esperas_429=[0], esperas_5xx=[0])
        raise AssertionError("deveria ter levantado ErroCotaIA")
    except ErroCotaIA:
        pass
    print("OK: 429 persistente segue virando ErroCotaIA")


def test_job_mapeia_erros():
    from app.api.routes import _JOBS, _iniciar_job

    def esperar(job_id):
        for _ in range(100):
            if _JOBS[job_id]["status"] != "processando":
                return _JOBS[job_id]
            time.sleep(0.05)
        raise AssertionError("job não terminou")

    job = esperar(_iniciar_job(lambda: (_ for _ in ()).throw(ErroEntradaIA("PDF ilegível"))))
    assert (job["codigo"], job["erro"]) == (422, "PDF ilegível")

    job = esperar(_iniciar_job(lambda: (_ for _ in ()).throw(ValueError("boom"))))
    assert job["codigo"] == 500
    assert "ValueError" in job["erro"], job["erro"]
    print("OK: job assíncrono mapeia ErroEntradaIA→422 e inclui a classe no 500 genérico")


if __name__ == "__main__":
    test_400_vira_erro_entrada()
    test_erro_de_rede_persistente_vira_runtime_error()
    test_erro_de_rede_transitorio_e_absorvido()
    test_429_persistente_segue_como_cota()
    test_job_mapeia_erros()
    print("\nTodos os testes passaram.")
