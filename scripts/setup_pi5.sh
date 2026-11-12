#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

INSTALL_SERVICE=false
if [[ "${1:-}" == "--install-service" && $# -eq 1 ]]; then
    INSTALL_SERVICE=true
elif [[ $# -ne 0 ]]; then
    echo "Usage: $0 [--install-service]" >&2
    exit 2
fi

VENV_PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PYTHON" ]]; then
    python3 -m venv "$ROOT/.venv"
fi
"$VENV_PYTHON" -m pip install -r "$ROOT/requirements.txt"

mkdir -p "$ROOT/config" "$ROOT/data" "$ROOT/logs"
if [[ ! -f "$ROOT/config/gateway.env" ]]; then
    cp "$ROOT/config/gateway.pi5.env.example" "$ROOT/config/gateway.env"
    echo "Created config/gateway.env from the Pi 5 example."
fi

SERVICE_USER="${SUDO_USER:-$(id -un)}"
echo "If needed, add $SERVICE_USER to dialout with: sudo usermod -aG dialout $SERVICE_USER"
echo "Configure MQTT_HOST and credentials in config/gateway.env before starting the gateway."
PYTHONPATH="$ROOT/src:$ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    "$VENV_PYTHON" scripts/run_gateway.py --config config/gateway.env --check-config

if [[ "$INSTALL_SERVICE" == true ]]; then
    SERVICE_TMP="$(mktemp)"
    trap 'rm -f "$SERVICE_TMP"' EXIT
    DJUA_SERVICE_USER="$SERVICE_USER" DJUA_SERVICE_ROOT="$ROOT" python3 - \
        "$ROOT/deploy/pi5/djua-sms-gateway.service" > "$SERVICE_TMP" <<'PY'
from pathlib import Path
import os
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
text = text.replace("__USER__", os.environ["DJUA_SERVICE_USER"])
text = text.replace("__ROOT__", os.environ["DJUA_SERVICE_ROOT"])
sys.stdout.write(text)
PY
    sudo install -m 0644 "$SERVICE_TMP" /etc/systemd/system/djua-sms-gateway.service
    sudo systemctl daemon-reload
    sudo systemctl enable --now djua-sms-gateway.service
fi
