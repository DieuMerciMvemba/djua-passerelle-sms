#!/usr/bin/env bash
# ==============================================================================
# djua_tmux.sh - Gestionnaire de session tmux pour la passerelle DJUA_SMS
# Permet de démarrer, attacher, inspecter et arrêter DJUA_SMS depuis n'importe où.
# ==============================================================================
set -euo pipefail

# Résolution absolue du répertoire racine du projet, quel que soit le PWD ou le lien symbolique
SCRIPT_DIR="$(cd -- "$(dirname -- "$(realpath "${BASH_SOURCE[0]}")")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

SESSION_NAME="djua-gateway"
CONFIG_FILE="$PROJECT_ROOT/config/gateway.env"
LOG_FILE="$PROJECT_ROOT/logs/gateway.log"

# Sécurisation de TMUX_TMPDIR pour éviter les erreurs de permissions sur /tmp
DEFAULT_TMUX_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/tmux"
if [[ -z "${TMUX_TMPDIR:-}" ]]; then
    mkdir -p "$DEFAULT_TMUX_DIR" 2>/dev/null || true
    chmod 700 "$DEFAULT_TMUX_DIR" 2>/dev/null || true
    if [[ -d "$DEFAULT_TMUX_DIR" ]]; then
        export TMUX_TMPDIR="$DEFAULT_TMUX_DIR"
    fi
fi

# Résolution de l'interpréteur Python (.venv du projet ou système)
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
elif [[ -x "$PROJECT_ROOT/.venv/bin/python3" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "ERREUR: Aucun interpréteur Python 3 trouvé." >&2
    exit 1
fi

is_running() {
    tmux has-session -t "$SESSION_NAME" 2>/dev/null
}

cmd_status() {
    if is_running; then
        echo "DJUA_SMS [tmux]: session '$SESSION_NAME' active."
        tmux list-sessions -F "#{session_name}: #{session_windows} fenêtres (créée le #{session_created_string})" 2>/dev/null | grep "^$SESSION_NAME" || true
        return 0
    else
        echo "DJUA_SMS [tmux]: aucune session '$SESSION_NAME' en cours."
        return 1
    fi
}

cmd_start() {
    if is_running; then
        echo "DJUA_SMS [tmux]: la session '$SESSION_NAME' est déjà en cours d'exécution."
        echo "Pour s'y connecter : $0 attach"
        return 0
    fi

    if [[ ! -f "$CONFIG_FILE" ]]; then
        echo "AVERTISSEMENT: $CONFIG_FILE introuvable."
        if [[ -f "$PROJECT_ROOT/config/gateway.pi5.env.example" ]]; then
            echo "Indication: Copiez config/gateway.pi5.env.example vers config/gateway.env pour configurer le modem et MQTT."
        fi
    fi

    mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/data"

    echo "Démarrage de DJUA_SMS dans la session tmux '$SESSION_NAME'..."
    tmux new-session -d -s "$SESSION_NAME" -c "$PROJECT_ROOT" \
        "PYTHONPATH=\"$PROJECT_ROOT/src:$PROJECT_ROOT\${PYTHONPATH:+:\$PYTHONPATH}\" \"$PYTHON_BIN\" \"$PROJECT_ROOT/scripts/run_gateway.py\" --config \"$CONFIG_FILE\"; echo ''; echo 'Processus terminé. Appuyez sur Entrée pour fermer.'; read"

    sleep 0.5
    if is_running; then
        echo "Session démarrée avec succès."
        echo "Commandes utiles :"
        echo "  - Attacher la console : $0 attach"
        echo "  - Voir les logs       : $0 logs"
        echo "  - Arrêter             : $0 stop"
    else
        echo "ERREUR: Échec du démarrage de la session tmux." >&2
        exit 1
    fi
}

cmd_attach() {
    if ! is_running; then
        echo "DJUA_SMS [tmux]: aucune session '$SESSION_NAME' n'est active."
        echo "Lancement automatique via 'start'..."
        cmd_start
    fi
    echo "Connexion à la session '$SESSION_NAME' (Détachement: Ctrl+B puis D)..."
    exec tmux attach-session -t "$SESSION_NAME"
}

cmd_stop() {
    if ! is_running; then
        echo "DJUA_SMS [tmux]: la session '$SESSION_NAME' n'est pas active."
        return 0
    fi

    echo "Arrêt ordonné de DJUA_SMS dans la session '$SESSION_NAME'..."
    # Envoi de SIGINT (Ctrl+C) au process dans tmux pour permettre l'arrêt propre
    tmux send-keys -t "$SESSION_NAME" C-c 2>/dev/null || true

    # Attente brève que le process quitte proprement
    local waited=0
    while is_running && [[ $waited -lt 5 ]]; do
        sleep 1
        waited=$((waited + 1))
    done

    # Si la fenêtre est toujours là (ex: script en attente de 'read'), on ferme la session
    if is_running; then
        tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
    fi

    echo "Session '$SESSION_NAME' arrêtée."
}

cmd_restart() {
    echo "Redémarrage de DJUA_SMS..."
    if is_running; then
        cmd_stop
        sleep 1
    fi
    cmd_start
}

cmd_logs() {
    if [[ -f "$LOG_FILE" ]]; then
        tail -n 50 -f "$LOG_FILE"
    else
        echo "Aucun fichier de log trouvé à l'emplacement : $LOG_FILE"
    fi
}

usage() {
    cat <<EOF
Usage: $(basename "$0") {start|attach|stop|restart|status|logs}

Commandes :
  start    Démarrer la passerelle DJUA_SMS en arrière-plan dans tmux
  attach   S'attacher à la session tmux interactive (détachement: Ctrl+B, puis D)
  stop     Arrêter proprement la session et le processus de passerelle
  restart  Redémarrer la session
  status   Vérifier si la session est active
  logs     Suivre en direct les logs (tail -f logs/gateway.log)

Note : Ce script peut être exécuté depuis n'importe quel répertoire.
EOF
}

case "${1:-}" in
    start)
        cmd_start
        ;;
    attach)
        cmd_attach
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        if [[ -z "${1:-}" ]]; then
            # Par défaut sans argument : si la session existe on l'attache, sinon on affiche le statut et l'aide
            if is_running; then
                cmd_attach
            else
                usage
                exit 1
            fi
        else
            echo "Commande inconnue : $1" >&2
            usage
            exit 2
        fi
        ;;
esac
