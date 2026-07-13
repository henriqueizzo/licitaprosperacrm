import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.auth import router as auth_router
from .api.routes import cron_router, router
from .config import settings
from .database import Base, SessionLocal, engine, migrar_esquema
from .security import bootstrap_admin, usuario_atual

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _job_pipeline():
    from .services.pipeline import executar_pipeline
    db = SessionLocal()
    try:
        resultado = executar_pipeline(db, gatilho="agendador")
        logger.info("Pipeline agendado executado: %s", resultado)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    colunas_novas = migrar_esquema()
    if colunas_novas:
        logger.info("Migração aplicada — colunas adicionadas: %s", ", ".join(colunas_novas))
    db = SessionLocal()
    try:
        bootstrap_admin(db)  # cria o admin do .env se não houver nenhum usuário
    finally:
        db.close()
    scheduler = None
    if settings.coleta_intervalo_horas > 0:
        scheduler = BackgroundScheduler()
        # next_run_time: primeira coleta ~2 min após ligar (sem ela, a 1ª execução
        # só ocorreria após o intervalo cheio — e o PC raramente fica 6h ligado)
        scheduler.add_job(
            _job_pipeline, "interval",
            hours=settings.coleta_intervalo_horas,
            next_run_time=datetime.now() + timedelta(minutes=2),
        )
        scheduler.start()
        logger.info("Coleta automática: primeira em ~2 min, depois a cada %sh",
                    settings.coleta_intervalo_horas)
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="LICITAPROSPERACRM", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# /api/auth/* (login é aberto; me/logout/trocar-senha e /api/usuarios têm as
# próprias dependencies) — as demais rotas /api/* exigem sessão válida.
# cron_router: autenticação própria por token (X-Cron-Token), sem cookie.
app.include_router(auth_router)
app.include_router(cron_router)
app.include_router(router, dependencies=[Depends(usuario_atual)])


# ---------- Frontend (produção): serve o build do Vite pelo próprio FastAPI ----------
# Se frontend/dist existir (env FRONTEND_DIST, default ../frontend/dist relativo ao
# backend), um único serviço atende API + SPA e o cookie de sessão fica same-origin.
# Sem dist (dev local com Vite na 5173), o comportamento antigo é mantido.

class _AssetsImutaveis(StaticFiles):
    """Assets do Vite têm hash no nome — pode cachear 'para sempre'."""

    def file_response(self, *args, **kwargs):
        resposta = super().file_response(*args, **kwargs)
        resposta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resposta


def _dir_frontend_dist() -> Path | None:
    dist = Path(settings.frontend_dist)
    if not dist.is_absolute():
        # relativo à pasta backend/ (pai do pacote app/), independente do cwd
        dist = Path(__file__).resolve().parent.parent / dist
    dist = dist.resolve()
    return dist if (dist / "index.html").is_file() else None


_FRONTEND_DIST = _dir_frontend_dist()

if _FRONTEND_DIST:
    if (_FRONTEND_DIST / "assets").is_dir():
        app.mount("/assets", _AssetsImutaveis(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{caminho:path}", include_in_schema=False)
    def spa(caminho: str):
        """Fallback SPA: arquivos reais do dist são servidos; o resto cai no index.html.

        Rotas /api/* inexistentes continuam devolvendo 404 (não devolvem HTML).
        """
        if caminho == "api" or caminho.startswith("api/"):
            raise HTTPException(404, "Not Found")
        if caminho:
            arquivo = (_FRONTEND_DIST / caminho).resolve()
            # protege contra path traversal e só serve o que está dentro do dist
            if arquivo.is_file() and arquivo.is_relative_to(_FRONTEND_DIST):
                return FileResponse(arquivo)
        return FileResponse(_FRONTEND_DIST / "index.html")

    logger.info("Frontend (SPA) servido de %s", _FRONTEND_DIST)
else:
    @app.get("/")
    def raiz():
        return {
            "app": "LICITAPROSPERACRM",
            "docs": "/docs",
            "ia_configurada": bool(settings.anthropic_api_key),
            "conlicitacao_configurada": bool(settings.conlicitacao_token),
        }
