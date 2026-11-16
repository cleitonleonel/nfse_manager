"""Carregador centralizado de configurações e variáveis do arquivo `.env`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Union

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


def load_dotenv_if_present(
    env_path: Optional[Union[Path, str]] = None,
    override: bool = False,
) -> Dict[str, str]:
    """Lê arquivos `.env` na raiz do projeto, em `backend/.env` ou num caminho informado e popula `os.environ`."""
    candidates = [Path(env_path)] if env_path is not None else [PROJECT_ROOT / ".env", BACKEND_DIR / ".env"]
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


load_dotenv_if_present()
