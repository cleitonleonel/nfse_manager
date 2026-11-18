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

# Verificar se já existe um servidor completo (API + Frontend) rodando na porta 8000
DEV_PORT=8000
PYTHON_PID=""

if curl -sf http://127.0.0.1:8000/api/health > /dev/null 2>&1 && curl -sf http://127.0.0.1:8000/ > /dev/null 2>&1; then
    echo "✅ Servidor Python (API + Frontend) já está rodando em 127.0.0.1:8000"
else
    # Se a porta 8000 já estiver ocupada (ex: container Docker nfse_backend API-only), usa outra porta livre
    if python3 -c "import socket, sys; s = socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', 8000)) == 0 else 1)" 2>/dev/null; then
        DEV_PORT=$(python3 -c "import socket; s = socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1]); s.close()")
        echo "ℹ️  Porta 8000 em uso (provavelmente Docker API-only). Iniciando servidor dev na porta ${DEV_PORT}..."
    else
        echo "▶️  Iniciando servidor Python na porta ${DEV_PORT}..."
    fi

    cd "$PROJECT_ROOT"
    if python3 -c "import uvicorn" >/dev/null 2>&1; then
        PY_CMD=(python3)
    elif command -v poetry >/dev/null 2>&1; then
        PY_CMD=(poetry run python)
    else
        PY_CMD=(python3)
    fi

    "${PY_CMD[@]}" server.py --host 127.0.0.1 --port "$DEV_PORT" &
    PYTHON_PID=$!
    echo "   PID: $PYTHON_PID"

    # Aguardar o servidor subir
    echo -n "   Aguardando servidor "
    for i in {1..20}; do
        sleep 1
        echo -n "."
        if curl -sf "http://127.0.0.1:${DEV_PORT}/api/health" > /dev/null 2>&1 && curl -sf "http://127.0.0.1:${DEV_PORT}/" > /dev/null 2>&1; then
            echo " ✅"
            break
        fi
    done
    export NFSE_SERVER_URL="http://127.0.0.1:${DEV_PORT}"
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
