#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
APP_MODULE="backend.main:app"

if command -v poetry >/dev/null 2>&1; then
  RUNNER=(poetry run python -m uvicorn)
else
  RUNNER=(python3 -m uvicorn)
fi

echo "🚀 Iniciando a versão web do Emissor NFSe"
echo "   App: ${APP_MODULE}"
echo "   URL: http://localhost:${PORT}"
echo "   Host: ${HOST}"
echo ""

"${RUNNER[@]}" "$APP_MODULE" --host "$HOST" --port "$PORT" --reload

