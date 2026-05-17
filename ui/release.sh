#!/usr/bin/env bash
# =============================================================================
# release.sh — Build completo para distribuição
# =============================================================================
# Gera:  ui/src-tauri/target/release/bundle/
#   Linux:   .deb, .AppImage
#   Windows: .msi, .exe (via cross-compilation)
#   macOS:   .dmg, .app (requer macOS)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "📦 NFSe Manager — Release Build"
echo ""

# Passo 1: empacotar o servidor Python
echo "── PASSO 1/2: Empacotando servidor Python..."
bash "$SCRIPT_DIR/build_sidecar.sh"

echo ""
echo "── PASSO 2/2: Compilando app Tauri..."
cd "$SCRIPT_DIR"

if [ ! -d "node_modules" ]; then
    echo "📦 Instalando dependências npm..."
    npm install
fi

npm run tauri build

echo ""
echo "✅ Build concluído!"
echo "   Pacotes disponíveis em: src-tauri/target/release/bundle/"
ls "$SCRIPT_DIR/src-tauri/target/release/bundle/" 2>/dev/null || echo "   (Nenhum pacote encontrado ainda)"
