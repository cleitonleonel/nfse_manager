"""Ponto de entrada da API FastAPI modularizada do Emissor NFSe.

Inicializa a aplicação, registra os routers por domínio e monta a pasta de
frontend como conteúdo estático.
"""

import logging
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.models import init_db  # noqa: E402
from app.api.routers import (  # noqa: E402
    clients,
    invoices,
    downloads,
    analytics,
    reports,
    system,
    catalogs,
    tax,
    emission,
)
from app.version import VERSION as __PROJECT_VERSION  # noqa: E402

# Initialize database
init_db()

# Create FastAPI app
app = FastAPI(
    title="NFSe Download Manager API",
    description="API para gerenciamento e sincronização de NFSe",
    version=__PROJECT_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Register routers
app.include_router(clients.router)
app.include_router(invoices.router)
app.include_router(downloads.router)
app.include_router(analytics.router)
app.include_router(reports.router)
app.include_router(system.router)
app.include_router(catalogs.router)
app.include_router(tax.router)
app.include_router(emission.router)


@app.get("/api/health", tags=["system"])
def health_check():
    """Endpoint leve de healthcheck para containers e orquestração."""
    return {"status": "ok", "version": __PROJECT_VERSION}


# Serve frontend static files with no-cache for development
class NoCacheStaticFiles(StaticFiles):
    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response


FRONTEND_DIR = Path("frontend") if Path("frontend").exists() else PROJECT_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", NoCacheStaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
