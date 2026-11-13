#!/usr/bin/env bash
# Raccourci 'dev' : démarre et s'attache directement à la session tmux DJUA_SMS
SCRIPT_DIR="$(cd -- "$(dirname -- "$(realpath "${BASH_SOURCE[0]}")")" && pwd)"
exec "$SCRIPT_DIR/djua_tmux.sh" attach "$@"
