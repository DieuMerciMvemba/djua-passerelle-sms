#!/usr/bin/env bash
# ==============================================================================
# switch_env.sh - Bascule d'environnement DJUA_SMS (PROD vs LOCAL)
# ==============================================================================
set -euo pipefail

SCRIPT_SOURCE="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd -- "$(dirname -- "$SCRIPT_SOURCE")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

CONFIG_DIR="$PROJECT_ROOT/config"
TARGET_CONFIG="$CONFIG_DIR/gateway.env"
PROD_CONFIG="$CONFIG_DIR/gateway.prod.env"
LOCAL_CONFIG="$CONFIG_DIR/gateway.local.env"

PYTHON_BIN="python3"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
fi

get_current_env() {
    if [[ ! -f "$TARGET_CONFIG" ]]; then
        echo "INCONNU (gateway.env absent)"
        return
    fi
    local url
    url=$(grep -E "^HTTP_BACKEND_URL=" "$TARGET_CONFIG" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" || true)
    if [[ "$url" =~ onrender\.com ]]; then
        echo "PROD (Cloud Render)"
    elif [[ "$url" =~ (10\.|192\.168\.|localhost|127\.0\.0\.1|5000) ]]; then
        echo "LOCAL (Labo / Dev: $url)"
    elif [[ -n "$url" ]]; then
        echo "PERSONNALISÉ ($url)"
    else
        echo "NON CONFIGURÉ"
    fi
}

get_gateway_pid() {
    pgrep -f "scripts/run_gateway.py" || true
}

show_status() {
    echo "==========================================================================="
    echo "🌐 ENVIRONNEMENT ACTUEL DJUA_SMS"
    echo "==========================================================================="
    local current_env
    current_env=$(get_current_env)
    echo "👉 Profil actif      : $current_env"

    if [[ -f "$TARGET_CONFIG" ]]; then
        local backend_url
        backend_url=$(grep -E "^HTTP_BACKEND_URL=" "$TARGET_CONFIG" 2>/dev/null | cut -d'=' -f2- || echo "(non défini)")
        local transport
        transport=$(grep -E "^BACKEND_TRANSPORT=" "$TARGET_CONFIG" 2>/dev/null | cut -d'=' -f2- || echo "mqtt")
        local d2_mode
        d2_mode=$(grep -E "^D2_AUTH_MODE=" "$TARGET_CONFIG" 2>/dev/null | cut -d'=' -f2- || echo "development")
        local port
        port=$(grep -E "^SERIAL_PORT=" "$TARGET_CONFIG" 2>/dev/null | cut -d'=' -f2- || echo "(non défini)")

        echo "📡 Transport         : $transport"
        echo "🎯 URL Télémétrie    : $backend_url"
        echo "🔒 Sécurité D2       : $d2_mode"
        echo "🔌 Port Série        : $port"
    else
        echo "⚠️  Fichier de configuration config/gateway.env inexistant."
    fi

    echo "---------------------------------------------------------------------------"
    local pid
    pid=$(get_gateway_pid)
    if [[ -n "$pid" ]]; then
        echo "🟢 Passerelle en cours d'exécution (PID: $pid)"
    else
        echo "⚪ Passerelle arrêtée"
    fi
    echo "==========================================================================="
    echo "Utilisation :"
    echo "  ./switch_env.sh prod    -> Bascule vers le backend CLOUD PRODUCTION (Render)"
    echo "  ./switch_env.sh local   -> Bascule vers le backend LOCAL (Labo LAN 10.252.252.52:5000)"
    echo "  ./switch_env.sh status  -> Affiche l'état actuel"
    echo "==========================================================================="
}

restart_gateway_if_running() {
    local pid
    pid=$(get_gateway_pid)
    if [[ -n "$pid" ]]; then
        echo "🔄 Redémarrage de la passerelle pour appliquer la nouvelle configuration..."
        if [[ -x "$PROJECT_ROOT/scripts/djua_tmux.sh" ]] && tmux has-session -t "djua-gateway" 2>/dev/null; then
            "$PROJECT_ROOT/scripts/djua_tmux.sh" restart
        else
            echo "   Arrêt de l'ancien processus (PID: $pid)..."
            kill "$pid" 2>/dev/null || true
            sleep 1
            if [[ -x "$PROJECT_ROOT/scripts/djua_tmux.sh" ]]; then
                "$PROJECT_ROOT/scripts/djua_tmux.sh" start
            fi
        fi
        echo "✅ Passerelle redémarrée avec la nouvelle configuration."
    else
        echo "ℹ️  La passerelle n'est pas lancée. Démarrez-la quand vous voulez avec : ./scripts/djua_tmux.sh start ou dev"
    fi
}

switch_to() {
    local target="$1"
    local src_file=""
    local label=""

    if [[ "$target" == "prod" ]]; then
        src_file="$PROD_CONFIG"
        label="PRODUCTION CLOUD (Render)"
    elif [[ "$target" == "local" ]]; then
        src_file="$LOCAL_CONFIG"
        label="LOCAL / LABO LAN (10.252.252.52:5000)"
    else
        echo "❌ Choix invalide : '$target'. Utilisez 'prod' ou 'local'." >&2
        exit 1
    fi

    if [[ ! -f "$src_file" ]]; then
        if [[ -f "${src_file}.example" ]]; then
            cp "${src_file}.example" "$src_file"
        else
            echo "❌ Fichier source introuvable : $src_file" >&2
            exit 1
        fi
    fi

    echo "==========================================================================="
    echo "🔄 Bascule vers l'environnement : $label"
    echo "==========================================================================="

    # Sauvegarde de précaution si config existante personnalisée
    if [[ -f "$TARGET_CONFIG" ]]; then
        cp "$TARGET_CONFIG" "$CONFIG_DIR/gateway.env.bak"
    fi

    cp "$src_file" "$TARGET_CONFIG"
    echo "✅ Fichier config/gateway.env mis à jour depuis $(basename "$src_file")."

    # Vérification de configuration
    echo "🔍 Vérification de la configuration..."
    if PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT" "$PYTHON_BIN" "$PROJECT_ROOT/scripts/run_gateway.py" --config "$TARGET_CONFIG" --check-config >/dev/null 2>&1; then
        echo "✅ Configuration validée avec succès (CONFIG_OK)."
    else
        echo "⚠️  Attention : la validation de configuration a signalé une anomalie."
        PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT" "$PYTHON_BIN" "$PROJECT_ROOT/scripts/run_gateway.py" --config "$TARGET_CONFIG" --check-config || true
    fi

    show_status
    restart_gateway_if_running
}

ACTION="${1:-status}"
case "$ACTION" in
    prod|production)
        switch_to "prod"
        ;;
    local|dev)
        switch_to "local"
        ;;
    status)
        show_status
        ;;
    -h|--help|help)
        show_status
        ;;
    *)
        echo "Option inconnue : $ACTION"
        show_status
        exit 1
        ;;
esac
