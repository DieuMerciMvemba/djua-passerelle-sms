#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

echo "Installation des commandes 'dev' et 'djua-tmux'..."

# 1. Tentative d'installation globale via /usr/local/bin (nécessite sudo si pas root)
INSTALLED_GLOBAL=false
if [[ $EUID -eq 0 ]]; then
    ln -sf "$SCRIPT_DIR/djua_tmux.sh" /usr/local/bin/djua-tmux
    ln -sf "$SCRIPT_DIR/dev.sh" /usr/local/bin/dev
    INSTALLED_GLOBAL=true
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo ln -sf "$SCRIPT_DIR/djua_tmux.sh" /usr/local/bin/djua-tmux
    sudo ln -sf "$SCRIPT_DIR/dev.sh" /usr/local/bin/dev
    INSTALLED_GLOBAL=true
fi

# 2. Installation dans ~/.bashrc de l'utilisateur courant pour disponibilité immédiate
BASHRC="$HOME/.bashrc"
touch "$BASHRC"

if ! grep -q "djua_tmux.sh" "$BASHRC"; then
    cat >> "$BASHRC" <<EOF

# DJUA_SMS - Commandes tmux globales
alias djua-tmux='$SCRIPT_DIR/djua_tmux.sh'
alias dev='$SCRIPT_DIR/dev.sh'
EOF
    echo "Aliases ajoutés dans $BASHRC."
fi

# 3. Installation dans ~/.local/bin si présent dans le PATH
LOCAL_BIN="$HOME/.local/bin"
if [[ -d "$LOCAL_BIN" && -w "$LOCAL_BIN" ]]; then
    ln -sf "$SCRIPT_DIR/djua_tmux.sh" "$LOCAL_BIN/djua-tmux"
    ln -sf "$SCRIPT_DIR/dev.sh" "$LOCAL_BIN/dev"
    echo "Liens créés dans $LOCAL_BIN."
fi

echo "Installation terminée !"
echo "Pour recharger immédiatement votre terminal actuel :"
echo "  source ~/.bashrc"
echo "Ensuite, vous pouvez taper simplement :"
echo "  dev"
echo "  djua-tmux"
