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

# Garantir que PyInstaller está instalado
echo ""
echo "📦 Verificando PyInstaller..."
cd "$PROJECT_ROOT"

if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "   Instalando PyInstaller..."
    pip3 install pyinstaller
fi

# Limpar build anterior
echo ""
echo "🧹 Limpando builds anteriores..."
rm -rf "$PROJECT_ROOT/dist" "$PROJECT_ROOT/build" "$PROJECT_ROOT/__pycache__"

# Rodar PyInstaller
echo ""
echo "🏗️  Empacotando servidor Python..."
cd "$PROJECT_ROOT"
pyinstaller \
    --onefile \
    --name server \
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
    --hidden-import lxml \
    --hidden-import bs4 \
    --hidden-import requests \
    --hidden-import requests_pkcs12 \
    --add-data "frontend:frontend" \
    --add-data "downloads:downloads" \
    server.py

# Criar diretório de binários do Tauri
echo ""
echo "📁 Copiando binário para src-tauri/binaries/..."
mkdir -p "$BINARIES_DIR"
cp "$PROJECT_ROOT/dist/server" "$BINARIES_DIR/server-$TARGET_TRIPLE"

echo ""
echo "✅ Sidecar criado em: src-tauri/binaries/server-$TARGET_TRIPLE"
echo ""
echo "▶️  Para compilar o app Tauri:"
echo "   cd ui/ && npm run build"
