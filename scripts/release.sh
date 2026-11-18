#!/usr/bin/env bash
# Script para criar tag e publicar release no GitHub (com changelog e instaladores locais opcionais).
# Requisitos: git e (opcionalmente) gh (GitHub CLI) no PATH.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORCE=0
if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
fi

if python3 -c "import tomllib" 2>/dev/null && PYTHONPATH="$ROOT_DIR/backend" python3 -c "from app.version import VERSION" 2>/dev/null; then
  PY_BIN=(python3)
elif command -v poetry >/dev/null 2>&1; then
  PY_BIN=(poetry run python)
else
  PY_BIN=(python3)
fi

VERSION=$(PYTHONPATH="$ROOT_DIR/backend" "${PY_BIN[@]}" -c 'from app.version import VERSION; print(VERSION)')

if [[ -z "$VERSION" ]]; then
  echo "Não foi possível ler a versão do projeto." >&2
  exit 1
fi

echo "Versão detectada: $VERSION"

# Não permitir pre-releases por padrão (ex.: 1.0.0-alpha)
if [[ "$FORCE" -ne 1 && ( "$VERSION" == *"-"* || "$VERSION" == *"+"* ) ]]; then
  echo "Versão parece ser pre-release (contém '-' ou '+'). Use --force para forçar." >&2
  exit 2
fi

cd "$ROOT_DIR"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Área de trabalho git não está limpa. Commit ou stash suas alterações antes de gerar a release." >&2
  git status --porcelain
  exit 3
fi

TAG="v${VERSION}"
if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "Tag $TAG já existe." >&2
  exit 4
fi

echo "Criando tag $TAG..."
git tag -a "$TAG" -m "Release $TAG"
git push origin HEAD "$TAG"

NOTES_FILE=""
if [[ -f CHANGELOG.md ]]; then
  NOTES_FILE="CHANGELOG.md"
elif [[ -f changelog.txt ]]; then
  NOTES_FILE="changelog.txt"
fi

# Coleta instaladores locais gerados pelo Tauri, se existirem
ASSETS=()
shopt -s nullglob
for asset in \
  ui/src-tauri/target/release/bundle/deb/*.deb \
  ui/src-tauri/target/release/bundle/appimage/*.AppImage \
  ui/src-tauri/target/release/bundle/msi/*.msi \
  ui/src-tauri/target/release/bundle/nsis/*.exe; do
  ASSETS+=("$asset")
done
shopt -u nullglob

if command -v gh >/dev/null 2>&1; then
  echo "Criando release no GitHub via gh..."
  GH_ARGS=("$TAG" -t "$TAG")
  if [[ -n "$NOTES_FILE" ]]; then
    GH_ARGS+=(-F "$NOTES_FILE")
  else
    GH_ARGS+=(-n "Release $TAG")
  fi
  if [[ ${#ASSETS[@]} -gt 0 ]]; then
    echo "Anexando instaladores locais: ${ASSETS[*]}"
    GH_ARGS+=("${ASSETS[@]}")
  fi
  gh release create "${GH_ARGS[@]}"
  echo "Release criada com gh."
else
  echo "gh (GitHub CLI) não encontrado. Tag $TAG publicada; o workflow GitHub Actions (desktop-installers.yml) criará os instaladores Windows/Linux na Release automaticamente." >&2
fi

echo "Concluído."
