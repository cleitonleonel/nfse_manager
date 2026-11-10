"""Router de Sistema - verificação de updates, suporte, downloads e navegação de pastas.

Fluxo de atualização:
1. Consultar a última release do GitHub.
2. Baixar o ZIP da release em background com progresso.
3. Extrair em `release/staging/<versão>/` para revisão segura.
4. Ao confirmar, aplicar os arquivos sobre o sistema e reiniciar.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import shlex
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import httpx2 as httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.api.state import tasks_status
from app.schemas import SupportMessage, UpdateApplyRequest, UpdateDownloadRequest
from app.version import VERSION as CURRENT_VERSION

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system", "support"])

REPO_OWNER = "cleitonleonel"
REPO_NAME = "nfse_manager"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json"}

PROJECT_ROOT = Path(__file__).resolve().parents[4]
RELEASE_ROOT = PROJECT_ROOT / "release"
STAGING_ROOT = RELEASE_ROOT / "staging"
DOWNLOAD_ROOT = RELEASE_ROOT / "downloads"
BACKUP_ROOT = RELEASE_ROOT / "backup"


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for piece in (version or "").split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            break
    return tuple(parts) if parts else (0,)


def _latest_release_data() -> dict:
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
    response = httpx.get(url, headers=GITHUB_HEADERS, timeout=30.0, follow_redirects=True)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"API GitHub retornou status {response.status_code}")
    return response.json()


def _stage_from_zip(zip_path: Path, staging_dir: Path, task_id: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as zipf:
        members = [m for m in zipf.infolist() if m.filename and not m.filename.endswith("/")]
        total = max(1, len(members))

        top_prefix = None
        for member in members:
            parts = Path(member.filename).parts
            if parts:
                top_prefix = parts[0]
                break

        for idx, member in enumerate(members):
            rel = Path(member.filename)
            if top_prefix and rel.parts and rel.parts[0] == top_prefix:
                rel = Path(*rel.parts[1:])
            if not rel.parts:
                continue

            target = staging_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipf.open(member, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)

            tasks_status[task_id].update(
                {
                    "phase": "extracting",
                    "message": f"Extraindo arquivos da atualização... ({idx + 1}/{total})",
                    "progress": min(95, 40 + int(55 * ((idx + 1) / total))),
                }
            )


def _download_release_package(task_id: str, version: str | None = None) -> None:
    release_info = None
    try:
        tasks_status[task_id] = {
            "status": "running",
            "phase": "checking",
            "message": "Consultando a última release no GitHub...",
            "progress": 0,
        }

        release_info = _latest_release_data()
        latest_tag = (release_info.get("tag_name") or "").removeprefix("v")
        if version and version != latest_tag:
            logger.info("Versão solicitada %s difere da latest %s; usando latest.", version, latest_tag)

        zipball_url = release_info.get("zipball_url")
        if not zipball_url:
            raise RuntimeError("A release mais recente não possui zipball_url.")

        tasks_status[task_id].update(
            {
                "phase": "downloading",
                "message": f"Baixando atualização {latest_tag or version or CURRENT_VERSION}...",
                "progress": 1,
            }
        )

        download_dir = DOWNLOAD_ROOT / (latest_tag or version or CURRENT_VERSION)
        staging_dir = STAGING_ROOT / (latest_tag or version or CURRENT_VERSION)
        download_dir.mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir(parents=True, exist_ok=True)
        zip_path = download_dir / "release.zip"

        with httpx.Client(follow_redirects=True, timeout=None) as client:
            with client.stream("GET", zipball_url, headers=GITHUB_HEADERS) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length", "0") or 0)
                written = 0
                with zip_path.open("wb") as f:
                    for chunk in response.iter_bytes(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        f.write(chunk)
                        written += len(chunk)
                        if total > 0:
                            pct = int(min(35, (written / total) * 35))
                        else:
                            pct = 20
                        tasks_status[task_id].update(
                            {
                                "phase": "downloading",
                                "message": f"Baixando atualização... {written // 1024} KB",
                                "progress": max(1, pct),
                            }
                        )

        tasks_status[task_id].update(
            {
                "phase": "extracting",
                "message": "Extraindo atualização para a pasta release/...",
                "progress": 40,
            }
        )

        _stage_from_zip(zip_path, staging_dir, task_id)

        tasks_status[task_id] = {
            "status": "completed",
            "phase": "ready",
            "message": f"Atualização {latest_tag} baixada e preparada em release/staging.",
            "progress": 100,
            "version": latest_tag,
            "staged_path": str(staging_dir),
            "zip_path": str(zip_path),
            "release_url": release_info.get("html_url"),
            "restart_required": True,
        }
    except Exception as exc:
        logger.error("Falha ao baixar atualização: %s", exc, exc_info=True)
        tasks_status[task_id] = {
            "status": "failed",
            "phase": "failed",
            "message": str(exc),
            "progress": 0,
            "release_url": release_info.get("html_url") if release_info else None,
        }


def _copy_tree_transactional(source_dir: Path, target_dir: Path) -> None:
    backup_dir = BACKUP_ROOT / f"backup_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    copied_backups: list[tuple[Path, Path]] = []

    def _should_skip(rel: Path) -> bool:
        parts = rel.parts
        if not parts:
            return False
        if rel.suffix == ".db":
            return True
        if parts[0] in {"release", "downloads", "certificados", "__pycache__", ".git"}:
            return True
        if len(parts) >= 2 and parts[0] == "backend" and parts[1] in {"downloads", "certificados", "__pycache__"}:
            return True
        return False

    try:
        for file_path in sorted(source_dir.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(source_dir)
            if _should_skip(rel):
                continue

            dest = target_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                backup_dest = backup_dir / rel
                backup_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, backup_dest)
                copied_backups.append((dest, backup_dest))

            shutil.copy2(file_path, dest)
    except Exception:
        for original, backup_file in reversed(copied_backups):
            try:
                shutil.copy2(backup_file, original)
            except Exception:
                pass
        raise


def _restart_self_after_delay(delay: float = 1.0) -> None:
    time.sleep(delay)
    restart_cmd = os.environ.get("NFSE_MANAGER_RESTART_CMD")
    if restart_cmd:
        args = shlex.split(restart_cmd)
        if args:
            subprocess.Popen(args, cwd=str(PROJECT_ROOT))
            os._exit(0)

    os.execv(sys.executable, [sys.executable] + sys.argv)


@router.post("/support/message")
async def send_support_message(payload: SupportMessage):
    """Enviar mensagem de suporte."""
    logger.info("Support Message Received: %s", payload)
    return {"message": "Mensagem enviada com sucesso! Nossa equipe entrará em contato em breve."}


@router.get("/system/check-update")
async def check_system_update():
    """Verificar atualizações do sistema."""
    try:
        data = _latest_release_data()
        latest_tag = (data.get("tag_name") or "").removeprefix("v")
        update_available = _version_tuple(latest_tag) > _version_tuple(CURRENT_VERSION)

        return {
            "current_version": CURRENT_VERSION,
            "latest_version": latest_tag,
            "update_available": update_available,
            "download_url": data.get("html_url"),
            "zipball_url": data.get("zipball_url"),
            "changelog": data.get("body"),
            "msg": "Nova versão disponível!" if update_available else "Você está na versão mais recente.",
        }
    except HTTPException as exc:
        if exc.status_code == 502:
            return {
                "current_version": CURRENT_VERSION,
                "update_available": False,
                "error": exc.detail,
                "msg": "Não foi possível consultar o GitHub agora.",
            }
        raise
    except Exception as e:
        logger.error("Erro ao verificar atualização: %s", e, exc_info=True)
        return {"current_version": CURRENT_VERSION, "error": str(e)}


@router.post("/system/update/download")
def start_update_download(payload: UpdateDownloadRequest, background_tasks: BackgroundTasks):
    """Baixa a release mais recente em background para a pasta release/staging."""
    task_id = f"update_{os.urandom(4).hex()}"
    background_tasks.add_task(_download_release_package, task_id, payload.version)
    return {"task_id": task_id}


@router.post("/system/update/apply")
def apply_downloaded_update(payload: UpdateApplyRequest):
    """Aplica a atualização já baixada e agenda o reinício do processo."""
    status = tasks_status.get(payload.task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")

    staged_path = status.get("staged_path")
    if not staged_path:
        raise HTTPException(status_code=400, detail="Nenhuma atualização preparada para aplicar.")

    source_dir = Path(staged_path)
    if not source_dir.exists():
        raise HTTPException(status_code=404, detail="A pasta staged da atualização não existe mais.")

    tasks_status[payload.task_id] = {
        "status": "running",
        "phase": "applying",
        "message": "Aplicando atualização no sistema...",
        "progress": 0,
    }

    try:
        _copy_tree_transactional(source_dir, PROJECT_ROOT)
        tasks_status[payload.task_id].update(
            {
                "status": "completed",
                "phase": "ready_to_restart",
                "message": "Atualização aplicada com sucesso. Reiniciando o programa...",
                "progress": 100,
                "restart_required": True,
            }
        )

        thread = threading.Thread(target=_restart_self_after_delay, kwargs={"delay": 1.0}, daemon=True)
        thread.start()

        return {"message": "Atualização aplicada. O sistema será reiniciado em instantes."}
    except Exception as exc:
        logger.error("Falha ao aplicar atualização: %s", exc, exc_info=True)
        tasks_status[payload.task_id] = {
            "status": "failed",
            "phase": "failed",
            "message": f"Falha ao aplicar atualização: {exc}",
            "progress": 0,
            "restart_required": False,
        }
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/system/version")
def get_system_version():
    """Retorna a versão embutida lida do pyproject.toml sem consultar o GitHub."""
    return {"current_version": CURRENT_VERSION}


@router.get("/system/list-folders")
def list_folders(path: str | None = None):
    """Listar diretórios para navegação de pastas."""
    try:
        target_path = Path(path) if path else Path.cwd()
        if not target_path.exists() or not target_path.is_dir():
            target_path = Path.cwd()

        items = []
        if target_path.parent != target_path:
            items.append(
                {
                    "name": ".. (Subir Nível)",
                    "path": str(target_path.parent),
                    "is_up": True,
                }
            )

        for item in target_path.iterdir():
            try:
                if item.is_dir() and not item.name.startswith("."):
                    items.append(
                        {
                            "name": item.name,
                            "path": str(item.absolute()),
                            "is_up": False,
                        }
                    )
            except (PermissionError, OSError):
                continue

        return {
            "current": str(target_path.absolute()),
            "folders": sorted(items, key=lambda x: (not x.get("is_up", False), x["name"].lower())),
        }
    except Exception as e:
        logger.error("Erro ao listar pastas: %s", e, exc_info=True)
        return {"error": str(e), "folders": []}
