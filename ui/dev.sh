#!/usr/bin/env bash
# =============================================================================
# dev.sh — Inicia o app Tauri em modo desenvolvimento
# =============================================================================
# Em modo dev:
#   - O servidor Python é iniciado diretamente (sem PyInstaller)
#   - O Tauri abre a janela apontando para http://localhost:8000
#   - Hot-reload do frontend está disponível (basta salvar os arquivos)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 NFSe Manager — Modo Desenvolvimento"
echo ""

# Verificar se o servidor já está rodando
if curl -s http://localhost:8000/api/clients > /dev/null 2>&1; then
    echo "✅ Servidor Python já está rodando em localhost:8000"
else
    echo "▶️  Iniciando servidor Python..."
    cd "$PROJECT_ROOT"
    python3 server.py &
    PYTHON_PID=$!
    echo "   PID: $PYTHON_PID"

    # Aguardar o servidor subir
    echo -n "   Aguardando servidor "
    for i in {1..15}; do
        sleep 1
        echo -n "."
        if curl -s http://localhost:8000/api/clients > /dev/null 2>&1; then
            echo " ✅"
            break
        fi
    done
fi

echo ""
echo "🖥️  Iniciando Tauri..."
cd "$SCRIPT_DIR"

# Instalar dependências npm se necessário
if [ ! -d "node_modules" ]; then
    echo "📦 Instalando dependências npm..."
    npm install
fi

npm run tauri dev

# Cleanup: matar o servidor Python ao fechar o Tauri
if [ -n "$PYTHON_PID" ]; then
    echo ""
    echo "🛑 Encerrando servidor Python (PID: $PYTHON_PID)..."
    kill "$PYTHON_PID" 2>/dev/null || true
fi
