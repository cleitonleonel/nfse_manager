#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UI_DIR="$SCRIPT_DIR/ui"

if [[ ! -d "$UI_DIR" ]]; then
  echo "Erro: diretório ui/ não encontrado em $UI_DIR" >&2
  exit 1
fi

cd "$UI_DIR"

if [[ ! -x ./dev.sh ]]; then
  chmod +x ./dev.sh
fi

echo "🚀 Iniciando a versão desktop (Tauri) do Emissor NFSe"
echo "   Diretório: $UI_DIR"
echo ""

exec ./dev.sh

