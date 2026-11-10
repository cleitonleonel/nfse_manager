#!/usr/bin/env bash
# Script simples para criar tag e release no GitHub.
# Requisitos: git e (opcionalmente) gh (GitHub CLI) no PATH.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION=$(PYTHONPATH="$ROOT_DIR/backend" python3 -c 'from app.version import VERSION; print(VERSION)')

if [[ -z "$VERSION" ]]; then
  echo "Não foi possível ler a versão do projeto." >&2
  exit 1
fi

echo "Versão detectada: $VERSION"

# Não permitir pre-releases por padrão (ex.: 1.0.0-alpha)
if [[ "$VERSION" == *"-"* || "$VERSION" == *"+"* ]]; then
  echo "Versão parece ser pre-release (contém '-' ou '+'). Use --force para forçar." >&2
  exit 2
fi

cd "$ROOT_DIR"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Área de trabalho git não está limpa. Commit ou stash suas alterações." >&2
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
git push origin "$TAG"

if command -v gh >/dev/null 2>&1; then
  echo "Criando release no GitHub via gh..."
  # tenta usar CHANGELOG.md se existir
  if [[ -f CHANGELOG.md ]]; then
    gh release create "$TAG" -t "$TAG" -F CHANGELOG.md
  else
    gh release create "$TAG" -t "$TAG" -n "Release $TAG"
  fi
  echo "Release criada com gh."
else
  echo "gh (GitHub CLI) não encontrado. Tag criada e publicada; crie a release manualmente no GitHub." >&2
fi

echo "Concluído."

