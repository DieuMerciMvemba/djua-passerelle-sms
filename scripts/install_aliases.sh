#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

echo "Installation des commandes 'dev', 'djua-tmux', 'switch-env' et 'logs'..."

# 1. Tentative d'installation globale via /usr/local/bin (nécessite sudo si pas root)
INSTALLED_GLOBAL=false
if [[ $EUID -eq 0 ]]; then
    ln -sf "$SCRIPT_DIR/djua_tmux.sh" /usr/local/bin/djua-tmux
    ln -sf "$SCRIPT_DIR/dev.sh" /usr/local/bin/dev
    ln -sf "$SCRIPT_DIR/switch_env.sh" /usr/local/bin/switch-env
    ln -sf "$SCRIPT_DIR/logs.sh" /usr/local/bin/djua-logs
    INSTALLED_GLOBAL=true
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo ln -sf "$SCRIPT_DIR/djua_tmux.sh" /usr/local/bin/djua-tmux
    sudo ln -sf "$SCRIPT_DIR/dev.sh" /usr/local/bin/dev
    sudo ln -sf "$SCRIPT_DIR/switch_env.sh" /usr/local/bin/switch-env
    sudo ln -sf "$SCRIPT_DIR/logs.sh" /usr/local/bin/djua-logs
    INSTALLED_GLOBAL=true
fi

# 2. Installation dans ~/.bashrc de l'utilisateur courant pour disponibilité immédiate
BASHRC="$HOME/.bashrc"
touch "$BASHRC"

if ! grep -q "djua_tmux.sh" "$BASHRC"; then
    cat >> "$BASHRC" <<EOF

# DJUA_SMS - Commandes globales
alias djua-tmux='$SCRIPT_DIR/djua_tmux.sh'
alias dev='$SCRIPT_DIR/dev.sh'
alias switch-env='$SCRIPT_DIR/switch_env.sh'
alias djua-logs='$SCRIPT_DIR/logs.sh'
EOF
    echo "Aliases ajoutés dans $BASHRC."
fi

# 3. Installation dans ~/.local/bin si présent dans le PATH
LOCAL_BIN="$HOME/.local/bin"
if [[ -d "$LOCAL_BIN" && -w "$LOCAL_BIN" ]]; then
    ln -sf "$SCRIPT_DIR/djua_tmux.sh" "$LOCAL_BIN/djua-tmux"
    ln -sf "$SCRIPT_DIR/dev.sh" "$LOCAL_BIN/dev"
    ln -sf "$SCRIPT_DIR/switch_env.sh" "$LOCAL_BIN/switch-env"
    ln -sf "$SCRIPT_DIR/logs.sh" "$LOCAL_BIN/djua-logs"
    echo "Liens créés dans $LOCAL_BIN."
fi

echo "Installation terminée !"
echo "Pour recharger immédiatement votre terminal actuel :"
echo "  source ~/.bashrc"
echo "Ensuite, vous pouvez taper simplement :"
echo "  dev"
echo "  djua-tmux"
