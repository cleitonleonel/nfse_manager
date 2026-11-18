"""Sincroniza a versão do `pyproject.toml` para todos os manifestos e arquivos estáticos.

Atualiza:
- `frontend/views/about.html` (badge e installed-version-tag, se estáticos)
- `ui/package.json` e `ui/package-lock.json`
- `ui/src-tauri/Cargo.toml`
- `ui/src-tauri/tauri.conf.json`

Uso:
    python scripts/sync_version.py
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import tomllib
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from app.version import VERSION
except Exception as e:
    print(f"Erro ao importar version: {e}")
    sys.exit(1)


def read_pyproject_version(pyproject_path: Path) -> Optional[str]:
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
        version = (data.get("project") or {}).get("version")
        if not version:
            version = ((data.get("tool") or {}).get("poetry") or {}).get("version")
        return str(version) if version else None
    except Exception:
        return None


def sync_about_html(path: Path, version: str) -> bool:
    if not path.exists():
        print(f"Arquivo não encontrado: {path}")
        return False

    text = path.read_text(encoding="utf-8")

    def _rep_badge(m):
        return m.group(1) + "v" + version + m.group(2)

    text, n1 = re.subn(r'(<span[^>]*class=["\']badge["\'][^>]*>)v?[0-9]+\.[0-9]+\.[0-9]+(</span>)', _rep_badge, text)

    def _rep_installed(m):
        return m.group(1) + version + m.group(2)

    text, n2 = re.subn(
        r'(<[^>]*id=["\']installed-version-tag["\'][^>]*>)v?[0-9]+\.[0-9]+\.[0-9]+(</[^>]+>)', _rep_installed, text
    )

    if n1 or n2:
        path.write_text(text, encoding="utf-8")
        print(f"Atualizado {path}: badge({n1}) installed-tag({n2})")
        return True
    return False


def _sync_json_version(path: Path, version: str, keys_path: List[str]) -> bool:
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    target = data
    for key in keys_path[:-1]:
        if not isinstance(target.get(key), dict):
            return False
        target = target[key]
    leaf = keys_path[-1]
    if target.get(leaf) == version:
        return False
    target[leaf] = version

    # Para package-lock.json, atualiza também packages[""].version quando existir
    if path.name == "package-lock.json":
        pkgs = data.get("packages")
        if isinstance(pkgs, dict) and isinstance(pkgs.get(""), dict):
            pkgs[""]["version"] = version

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def _sync_cargo_toml_version(path: Path, version: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r'(?ms)(^\[package\].*?^version\s*=\s*")([^"]+)(")')
    match = pattern.search(text)
    if not match or match.group(2) == version:
        return False
    updated = pattern.sub(rf'\g<1>{version}\g<3>', text, count=1)
    path.write_text(updated, encoding="utf-8")
    return True


def sync_all_version_files(root: Path, version: str) -> List[str]:
    """Sincroniza `version` para os manifestos Tauri/Node e `about.html`, retornando caminhos alterados."""
    updated: List[str] = []

    if sync_about_html(root / "frontend" / "views" / "about.html", version):
        updated.append("frontend/views/about.html")

    if _sync_json_version(root / "ui" / "package.json", version, ["version"]):
        updated.append("ui/package.json")

    if _sync_json_version(root / "ui" / "package-lock.json", version, ["version"]):
        updated.append("ui/package-lock.json")

    if _sync_json_version(root / "ui" / "src-tauri" / "tauri.conf.json", version, ["package", "version"]):
        updated.append("ui/src-tauri/tauri.conf.json")

    if _sync_cargo_toml_version(root / "ui" / "src-tauri" / "Cargo.toml", version):
        updated.append("ui/src-tauri/Cargo.toml")

    return updated


def main():
    root = Path(__file__).resolve().parents[1]
    version = read_pyproject_version(root / "pyproject.toml") or VERSION
    changed = sync_all_version_files(root, version)
    print(f"Versão sincronizada ({version}): {changed or 'nenhuma alteração necessária'}")


if __name__ == "__main__":
    main()
