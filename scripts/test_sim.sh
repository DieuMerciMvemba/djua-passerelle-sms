#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

PYTHON_BIN="python3"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
fi

echo "==========================================================================="
echo "🧪 DIAGNOSTIC & TEST DU MODULE SIM (USB / UART)"
echo "==========================================================================="

PID=$(pgrep -f "scripts/run_gateway.py" || true)
if [[ -n "$PID" ]]; then
    echo "ℹ️  Note : La passerelle DJUA_SMS est active en tâche de fond (PID: $PID)."
    echo "    Si le port USB est actuellement utilisé, vous pouvez temporairement"
    echo "    l'arrêter avec : kill $PID"
    echo "==========================================================================="
fi

exec "$PYTHON_BIN" "$PROJECT_ROOT/scripts/test_sim_connection.py" "$@"
