"""Sincroniza a versão do `pyproject.toml` para arquivos estáticos.

Atualmente substitui a versão exibida em:
- `frontend/views/about.html` (badge e installed-version-tag)

Uso:
    python scripts/sync_version.py

"""

from pathlib import Path
import re
import sys

# Garantir que o diretório backend esteja no sys.path para permitir import local
ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from app.version import VERSION
except Exception as e:
    print(f"Erro ao importar version: {e}")
    sys.exit(1)


def sync_about_html(path: Path, version: str) -> bool:
    if not path.exists():
        print(f"Arquivo não encontrado: {path}")
        return False

    text = path.read_text(encoding="utf-8")

    # Atualiza a badge (ex: <span class="badge">v0.1.0</span>)
    def _rep_badge(m):
        return m.group(1) + "v" + version + m.group(2)

    text, n1 = re.subn(r'(<span[^>]*class=["\']badge["\'][^>]*>)v?[0-9]+\.[0-9]+\.[0-9]+(</span>)', _rep_badge, text)

    # Atualiza o installed-version-tag (ex: <div ... id="installed-version-tag">0.1.0</div>)
    def _rep_installed(m):
        return m.group(1) + version + m.group(2)

    text, n2 = re.subn(
        r'(<[^>]*id=["\']installed-version-tag["\'][^>]*>)v?[0-9]+\.[0-9]+\.[0-9]+(</[^>]+>)', _rep_installed, text
    )

    if n1 or n2:
        path.write_text(text, encoding="utf-8")
        print(f"Atualizado {path}: badge({n1}) installed-tag({n2})")
        return True
    else:
        print(f"Nenhuma ocorrência de versão encontrada em {path}")
        return False


def main():
    root = Path(__file__).resolve().parents[1]
    about = root / "frontend" / "views" / "about.html"
    sync_about_html(about, VERSION)


if __name__ == "__main__":
    main()
