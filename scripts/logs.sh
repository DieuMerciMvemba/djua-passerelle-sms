#!/usr/bin/env bash
set -euo pipefail

SCRIPT_SOURCE="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="$PROJECT_ROOT/logs/gateway.log"

echo "==========================================================================="
echo "📜 SUIVI EN TEMPS RÉEL DES LOGS - PASSERELLE DJUA_SMS"
echo "==========================================================================="

PID=$(pgrep -f "scripts/run_gateway.py" || true)
if [[ -n "$PID" ]]; then
    echo "🟢 Statut passerelle : EN COURS D'EXÉCUTION (PID: $PID)"
else
    echo "🔴 Statut passerelle : ARRÊTÉE"
fi

echo "📁 Fichier cible    : $LOG_FILE"
echo "💡 Appuyez sur [Ctrl + C] pour quitter le suivi en temps réel à tout moment."
echo "==========================================================================="
echo ""

if [[ ! -f "$LOG_FILE" ]]; then
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"
fi

exec tail -n 50 -f "$LOG_FILE"
