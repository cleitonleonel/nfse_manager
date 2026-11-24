"""Carregador centralizado de configurações, variáveis `.env` e resolução portável de diretórios."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Optional, Union

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent

_FALSE_VALUES = {"0", "false", "no", "off"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


def load_dotenv_if_present(
    env_path: Optional[Union[Path, str]] = None,
    override: bool = False,
) -> Dict[str, str]:
    """Lê arquivos `.env` em `NFSE_ENV_FILE`, na raiz do projeto, em `backend/.env` ou no caminho informado."""
    if env_path is not None:
        candidates = [Path(env_path)]
    else:
        if (os.getenv("NFSE_DISABLE_DOTENV") or "").strip().lower() in _TRUE_VALUES:
            return {}
        candidates = []
        custom_env = (os.getenv("NFSE_ENV_FILE") or "").strip()
        if custom_env:
            candidates.append(Path(custom_env).expanduser())
        for cand in (PROJECT_ROOT / ".env", BACKEND_DIR / ".env", get_data_dir() / ".env"):
            if cand not in candidates:
                candidates.append(cand)

    loaded: Dict[str, str] = {}
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            for raw_line in candidate.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                if not key:
                    continue
                if override or key not in os.environ:
                    os.environ[key] = val
                loaded[key] = os.environ[key]
        except Exception:
            pass
    return loaded


def get_data_dir() -> Path:
    """Retorna o diretório base de dados da aplicação respeitando `NFSE_DATA_DIR` e `sys.frozen`."""
    custom = (os.getenv("NFSE_DATA_DIR") or "").strip()
    if custom:
        return Path(custom).expanduser()
    if getattr(sys, "frozen", False):
        if os.name == "nt" or sys.platform.startswith("win"):
            prog_data = (os.getenv("PROGRAMDATA") or "C:/ProgramData").strip()
            return Path(prog_data) / "NFSeManager"
        return Path.home() / ".local" / "share" / "nfse-manager"
    return BACKEND_DIR


def get_certs_dir() -> Path:
    """Retorna o diretório de certificados A1 (`NFSE_CERTS_DIR` -> `CERTIFICADOS_DIR` -> `data_dir/certificados`)."""
    custom = (os.getenv("NFSE_CERTS_DIR") or os.getenv("CERTIFICADOS_DIR") or "").strip()
    if custom:
        return Path(custom).expanduser()
    return get_data_dir() / "certificados"


def get_downloads_dir() -> Path:
    """Retorna o diretório de downloads/XML/PDF (`NFSE_DOWNLOADS_DIR` -> `DOWNLOADS_DIR` -> `data_dir/downloads`)."""
    custom = (os.getenv("NFSE_DOWNLOADS_DIR") or os.getenv("DOWNLOADS_DIR") or "").strip()
    if custom:
        return Path(custom).expanduser()
    return get_data_dir() / "downloads"


def get_catalogs_dir() -> Path:
    """Retorna o diretório de cache gravável dos catálogos fiscais (`NFSE_CATALOGS_DIR` -> `PYNFSE_CATALOGS_DIR` -> `data_dir/catalogs`)."""
    custom = (os.getenv("NFSE_CATALOGS_DIR") or os.getenv("PYNFSE_CATALOGS_DIR") or "").strip()
    if custom:
        return Path(custom).expanduser()
    return get_data_dir() / "catalogs"


def get_sqlite_db_path() -> Path:
    """Retorna o caminho do banco SQLite (`NFSE_DB_PATH` -> `data_dir/nfse.db`)."""
    custom = (os.getenv("NFSE_DB_PATH") or "").strip()
    if custom:
        return Path(custom).expanduser()
    return get_data_dir() / "nfse.db"


def get_deployment_mode(db_dialect: Optional[str] = None) -> str:
    """Retorna o modo de implantação (`NFSE_DEPLOYMENT_MODE` ou inferido pelo ambiente)."""
    raw = (os.getenv("NFSE_DEPLOYMENT_MODE") or "").strip().lower()
    if raw:
        return raw
    if db_dialect == "postgresql":
        return "server"
    if getattr(sys, "frozen", False):
        return "desktop"
    return "local"


def get_scheduler_mode() -> str:
    """Retorna o modo do worker agendado (`auto`, `leader` ou `disabled`)."""
    raw = (os.getenv("NFSE_SCHEDULER_MODE") or "auto").strip().lower()
    if raw in {"auto", "leader", "disabled"}:
        return raw
    return "auto"


def allow_public_register() -> bool:
    """Indica se o auto-cadastro público está habilitado após o primeiro admin (`NFSE_ALLOW_PUBLIC_REGISTER`)."""
    raw = (os.getenv("NFSE_ALLOW_PUBLIC_REGISTER") or "1").strip().lower()
    return raw not in _FALSE_VALUES


def allow_operator_create_client() -> bool:
    """Indica se usuários não-admin podem cadastrar novas empresas ficando vinculados a elas (`NFSE_ALLOW_OPERATOR_CREATE_CLIENT`)."""
    raw = (os.getenv("NFSE_ALLOW_OPERATOR_CREATE_CLIENT") or "1").strip().lower()
    return raw not in _FALSE_VALUES


def is_self_update_disabled() -> bool:
    """Indica se a auto-atualização in-place está bloqueada (`NFSE_DISABLE_SELF_UPDATE` ou `sys.frozen`)."""
    if getattr(sys, "frozen", False):
        return True
    raw = (os.getenv("NFSE_DISABLE_SELF_UPDATE") or "0").strip().lower()
    return raw in _TRUE_VALUES


def _storage_base_for_kind(kind: Optional[str]) -> Path:
    k = (kind or "").strip().lower()
    if k in {"certs", "cert", "certificados"}:
        return get_certs_dir()
    if k in {"downloads", "download"}:
        return get_downloads_dir()
    return get_data_dir()


def _is_windows_or_unc_path(raw: str) -> bool:
    norm = raw.replace("\\", "/")
    if norm.startswith("//"):
        return True
    return len(norm) >= 3 and norm[1] == ":" and norm[2] == "/"


def to_storage_relative_path(path: Union[str, Path], kind: str) -> str:
    """Converte um caminho dentro do diretório de storage para caminho relativo POSIX portável."""
    if not path:
        return ""
    p = Path(path)
    base = _storage_base_for_kind(kind)
    try:
        rel = p.resolve().relative_to(base.resolve())
        return rel.as_posix()
    except ValueError:
        if not p.is_absolute() and not _is_windows_or_unc_path(str(path)):
            norm = str(path).replace("\\", "/").lstrip("/")
            k = (kind or "").strip().lower()
            if k in {"certs", "cert", "certificados"} and norm.startswith("certificados/"):
                return norm[len("certificados/") :]
            if k in {"downloads", "download"} and norm.startswith("downloads/"):
                return norm[len("downloads/") :]
            return norm
        return p.as_posix()


def resolve_storage_path(stored_path: Optional[Union[str, Path]], kind: Optional[str] = None) -> Optional[Path]:
    """Resolve caminhos relativos POSIX, caminhos legados ou absolutos migrados para o storage atual."""
    if stored_path is None:
        return None
    raw = str(stored_path).strip()
    if not raw:
        return None

    norm_raw = raw.replace("\\", "/")
    p = Path(raw)
    k = (kind or "").strip().lower()

    if not p.is_absolute() and not _is_windows_or_unc_path(norm_raw):
        base = _storage_base_for_kind(kind)
        candidates = []
        if k in {"certs", "cert", "certificados"} and norm_raw.startswith("certificados/"):
            candidates.append(get_certs_dir() / norm_raw[len("certificados/") :])
        if k in {"downloads", "download"} and norm_raw.startswith("downloads/"):
            candidates.append(get_downloads_dir() / norm_raw[len("downloads/") :])
        candidates.extend([base / norm_raw, get_data_dir() / norm_raw, BACKEND_DIR / norm_raw])
        for cand in candidates:
            if cand.exists():
                return cand
        return candidates[0]

    if p.exists():
        return p

    # Rebase de caminhos absolutos legados (ex: container Docker / Windows / outro usuário)
    parts = [part for part in norm_raw.split("/") if part and part != "."]
    anchor_checks = []
    if k in {"", "certs", "cert", "certificados"}:
        anchor_checks.append(("certificados", get_certs_dir()))
    if k in {"", "downloads", "download"}:
        anchor_checks.append(("downloads", get_downloads_dir()))

    is_foreign_path = _is_windows_or_unc_path(norm_raw) if os.name != "nt" else False
    for anchor, target_base in anchor_checks:
        if anchor in parts:
            idx = len(parts) - 1 - parts[::-1].index(anchor)
            rel_parts = parts[idx + 1 :]
            if rel_parts:
                cand = target_base.joinpath(*rel_parts)
                if cand.exists():
                    return cand
                if is_foreign_path or not p.parent.exists():
                    return cand
            elif is_foreign_path or not p.parent.exists():
                return target_base

    return p


load_dotenv_if_present()
