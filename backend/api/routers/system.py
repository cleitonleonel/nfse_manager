"""Router de Sistema - Verificação de updates, suporte e navegação de pastas."""

import logging
from pathlib import Path
from fastapi import APIRouter
import httpx

from backend.schemas import SupportMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system", "support"])

CURRENT_VERSION = "1.2.0"


@router.post("/support/message")
async def send_support_message(payload: SupportMessage):
    """Enviar mensagem de suporte."""
    logger.info(f"Support Message Received: {payload}")
    return {"message": "Mensagem enviada com sucesso! Nossa equipe entrará em contato em breve."}


@router.get("/system/check-update")
async def check_system_update():
    """Verificar atualizações do sistema."""
    REPO_OWNER = "cleitonleonel"
    REPO_NAME = "nfse_manager"

    headers = {
        "Accept": "application/vnd.github.v3+json"
    }

    try:
        async with httpx.AsyncClient() as client:
            url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
            response = await client.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                latest_tag = data.get("tag_name", "").replace("v", "")

                update_available = latest_tag > CURRENT_VERSION

                return {
                    "current_version": CURRENT_VERSION,
                    "latest_version": latest_tag,
                    "update_available": update_available,
                    "download_url": data.get("html_url"),
                    "changelog": data.get("body"),
                    "msg": "Nova versão disponível!" if update_available else "Você está na versão mais recente."
                }
            elif response.status_code == 404:
                return {
                    "current_version": CURRENT_VERSION,
                    "update_available": False,
                    "msg": "Ainda não há releases públicos para este sistema."
                }
            else:
                return {"current_version": CURRENT_VERSION,
                        "error": f"API GitHub retornou status {response.status_code}"}

    except Exception as e:
        logger.error(f"Erro ao verificar atualização: {e}")
        return {"current_version": CURRENT_VERSION, "error": str(e)}


@router.get("/system/list-folders")
def list_folders(path: str | None = None):
    """Listar diretórios para navegação de pastas."""
    try:
        target_path = Path(path) if path else Path.cwd()
        if not target_path.exists() or not target_path.is_dir():
            target_path = Path.cwd()

        items = []
        if target_path.parent != target_path:
            items.append({
                "name": ".. (Subir Nível)",
                "path": str(target_path.parent),
                "is_up": True
            })

        for item in target_path.iterdir():
            try:
                if item.is_dir() and not item.name.startswith('.'):
                    items.append({
                        "name": item.name,
                        "path": str(item.absolute()),
                        "is_up": False
                    })
            except (PermissionError, OSError):
                continue

        return {
            "current": str(target_path.absolute()),
            "folders": sorted(items, key=lambda x: (not x.get('is_up', False), x['name'].lower()))
        }
    except Exception as e:
        logger.error(f"Erro ao listar pastas: {e}")
        return {"error": str(e), "folders": []}
