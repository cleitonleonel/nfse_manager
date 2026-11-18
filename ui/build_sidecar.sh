#!/usr/bin/env bash
# =============================================================================
# build_sidecar.sh — Empacota o servidor Python como binário para o Tauri
# =============================================================================
# Uso:
#   cd ui/
#   ./build_sidecar.sh
#
# O binário resultante é copiado para src-tauri/binaries/server-<target-triple>
# que é o formato esperado pelo Tauri para sidecars.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BINARIES_DIR="$SCRIPT_DIR/src-tauri/binaries"

echo "🔧 NFSe Manager — Build Sidecar"
echo "   Projeto: $PROJECT_ROOT"
echo ""

# Detectar o Rust target triple (usado pelo Tauri para nomear o binário)
TARGET_TRIPLE=$(rustc -Vv | grep host | cut -f2 -d' ')
echo "🎯 Target: $TARGET_TRIPLE"

# Selecionar Python com dependências do projeto
if [[ -n "${PYTHON_BIN:-}" ]]; then
    PY_CMD=("$PYTHON_BIN")
elif python3 -c "import fastapi, pynfse" 2>/dev/null; then
    PY_CMD=(python3)
elif command -v poetry >/dev/null 2>&1; then
    PY_CMD=(poetry run python)
else
    PY_CMD=(python3)
fi

echo "🐍 Python: ${PY_CMD[*]}"

# Garantir que PyInstaller está instalado
echo ""
echo "📦 Verificando PyInstaller..."
cd "$PROJECT_ROOT"

if ! "${PY_CMD[@]}" -c "import PyInstaller" 2>/dev/null; then
    echo "   Instalando PyInstaller..."
    "${PY_CMD[@]}" -m pip install pyinstaller
fi

# Limpar build anterior
echo ""
echo "🧹 Limpando builds anteriores..."
rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build" "$PROJECT_ROOT/__pycache__"

# Rodar PyInstaller
echo ""
echo "🏗️  Empacotando servidor Python..."
cd "$PROJECT_ROOT"
"${PY_CMD[@]}" -m PyInstaller \
    --noconfirm \
    --onefile \
    --name server \
    --paths backend \
    --collect-submodules app \
    --collect-all pynfse \
    --collect-all signxml \
    --collect-all cryptography \
    --hidden-import uvicorn.logging \
    --hidden-import uvicorn.loops \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols \
    --hidden-import uvicorn.protocols.http \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets \
    --hidden-import uvicorn.protocols.websockets.auto \
    --hidden-import uvicorn.lifespan \
    --hidden-import uvicorn.lifespan.on \
    --hidden-import fastapi \
    --hidden-import sqlalchemy \
    --hidden-import sqlalchemy.dialects.postgresql \
    --hidden-import sqlalchemy.dialects.sqlite \
    --hidden-import psycopg2 \
    --hidden-import httpx2 \
    --hidden-import openpyxl \
    --hidden-import reportlab \
    --hidden-import lxml \
    --hidden-import bs4 \
    --hidden-import multipart \
    --hidden-import requests \
    --hidden-import requests_pkcs12 \
    --add-data "frontend:frontend" \
    --add-data "pyproject.toml:." \
    --add-data "backend/migrations:backend/migrations" \
    server.py

# Criar diretório de binários do Tauri
echo ""
echo "📁 Copiando binário para src-tauri/binaries/..."
mkdir -p "$BINARIES_DIR"
cp "$PROJECT_ROOT/dist/server" "$BINARIES_DIR/server-$TARGET_TRIPLE"
chmod +x "$BINARIES_DIR/server-$TARGET_TRIPLE"

echo ""
echo "✅ Sidecar criado em: src-tauri/binaries/server-$TARGET_TRIPLE"
echo ""
echo "▶️  Para compilar o app Tauri:"
echo "   cd ui/ && npm run build"
