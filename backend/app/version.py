"""Centraliza a versão do projeto lendo o `pyproject.toml`.

Uso:
    from app.version import VERSION

O arquivo tenta ler `project.version` (PEP 621) e ainda suporta `tool.poetry.version` como fallback.
"""

from pathlib import Path
import tomllib
from typing import Optional


def _read_pyproject_version(pyproject_path: Path) -> Optional[str]:
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)

        # PEP 621: [project] version
        version = None
        project = data.get("project")
        if isinstance(project, dict):
            version = project.get("version")

        # Fallback: poetry-style
        if not version:
            tool = data.get("tool")
            if isinstance(tool, dict):
                poetry = tool.get("poetry")
                if isinstance(poetry, dict):
                    version = poetry.get("version")

        return version
    except Exception:
        return None


def get_version() -> str:
    """Retorna a versão do projeto lida do `pyproject.toml`.

    Se não for possível ler o arquivo, retorna `0.0.0` como fallback.
    """
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[2]
    pyproject_path = project_root / "pyproject.toml"

    version = _read_pyproject_version(pyproject_path)
    if version:
        return str(version)
    return "0.0.0"


VERSION = get_version()
