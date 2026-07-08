import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.auth import router as auth_router
from .api.routes import router
from .config import settings
from .database import Base, SessionLocal, engine, migrar_esquema
from .security import bootstrap_admin, usuario_atual

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _job_pipeline():
    from .services.pipeline import executar_pipeline
    db = SessionLocal()
    try:
        resultado = executar_pipeline(db)
        logger.info("Pipeline agendado executado: %s", resultado)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    colunas_novas = migrar_esquema()
    if colunas_novas:
        logger.info("Migração aplicada — colunas adicionadas em `analises`: %s", ", ".join(colunas_novas))
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
app.include_router(auth_router)
app.include_router(router, dependencies=[Depends(usuario_atual)])


@app.get("/")
def raiz():
    return {
        "app": "LICITAPROSPERACRM",
        "docs": "/docs",
        "ia_configurada": bool(settings.anthropic_api_key),
        "conlicitacao_configurada": bool(settings.conlicitacao_token),
    }
