"""Ponto de entrada da API FastAPI modularizada do Emissor NFSe.

Inicializa a aplicação, registra os routers por domínio e monta a pasta de
frontend como conteúdo estático.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging

from backend.models import init_db
from backend.api.routers import clients, invoices, downloads, analytics, reports, system
from backend.version import VERSION as __PROJECT_VERSION

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


# Serve frontend static files with no-cache for development
class NoCacheStaticFiles(StaticFiles):
    def is_not_modified(self, response_headers, request_headers) -> bool:
        return False

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response


app.mount("/", NoCacheStaticFiles(directory="frontend", html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
