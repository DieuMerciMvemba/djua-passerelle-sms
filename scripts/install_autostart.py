#!/usr/bin/env python3
"""Solution professionnelle de démarrage automatique (Autostart Daemon)
pour la passerelle DJUA_SMS sous Linux (systemd / cron natif) et Windows (Task Scheduler).

Ne dépend d'aucun multiplexeur de terminal (ni tmux, ni screen).
Exécute directement le moteur de la passerelle en arrière-plan avec supervision et redémarrage automatique.

Usage :
    python3 scripts/install_autostart.py [--action install|status|uninstall] [--platform auto|linux|windows]
"""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVICE_NAME = "djua-sms-gateway"
WINDOWS_TASK_NAME = "DJUA SMS Gateway"


def get_python_bin() -> str:
    """Retourne le binaire python à utiliser (.venv en priorité, sinon binaire système)."""
    venv_py = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


# ==============================================================================
# LINUX : SYSTEMD (Standard Industriel) & CRON NATIF (Sans tmux)
# ==============================================================================

SYSTEMD_TEMPLATE = """[Unit]
Description=DJUA SMS Gateway Service (Production Daemon)
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={root}
SupplementaryGroups=dialout
ExecStart={python_bin} scripts/run_gateway.py --config config/gateway.env
Environment=PYTHONPATH={root}/src:{root}
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=20
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""


def install_linux() -> int:
    print("\n" + "=" * 75)
    print("🐧 [Linux] Installation Professionnelle du Service DJUA_SMS")
    print("=" * 75)

    user = getpass.getuser()
    python_bin = get_python_bin()
    system_service_path = Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"

    # 1. Génération du fichier unit systemd propre
    service_content = SYSTEMD_TEMPLATE.format(
        user=user,
        root=str(ROOT),
        python_bin=python_bin,
    )
    generated_service_file = ROOT / "deploy" / "pi5" / f"{SERVICE_NAME}.service"
    generated_service_file.parent.mkdir(parents=True, exist_ok=True)
    generated_service_file.write_text(service_content, encoding="utf-8")
    print(f"📄 Fichier systemd généré : {generated_service_file}")

    # 2. Vérification des droits root / sudo pour systemd
    is_root = (os.geteuid() == 0) if hasattr(os, "geteuid") else False
    can_sudo = False
    if not is_root and shutil.which("sudo"):
        res = subprocess.run(["sudo", "-n", "true"], capture_output=True)
        can_sudo = (res.returncode == 0)

    systemd_installed = False
    if is_root or can_sudo:
        try:
            install_cmd = (
                ["install", "-m", "0644", str(generated_service_file), str(system_service_path)]
                if is_root
                else ["sudo", "install", "-m", "0644", str(generated_service_file), str(system_service_path)]
            )
            subprocess.run(install_cmd, check=True)
            cmd_prefix = [] if is_root else ["sudo"]
            subprocess.run(cmd_prefix + ["systemctl", "daemon-reload"], check=True)
            subprocess.run(cmd_prefix + ["systemctl", "enable", f"{SERVICE_NAME}.service"], check=True)
            systemd_installed = True
            print(f"✅ Service systemd système installé et activé au boot : {system_service_path}")
        except Exception as exc:
            print(f"⚠️ Impossible d'activer systemd automatiquement : {exc}")

    # 3. Méthode universelle de démarrage natif (Cron @reboot sans tmux)
    # Lance directement le process Python en tâche de fond avec redirection vers les logs
    cron_installed = False
    try:
        cron_res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing_cron = cron_res.stdout if cron_res.returncode == 0 else ""
        cron_marker = f"# DJUA_SMS_DAEMON ({ROOT})"
        native_cron_cmd = (
            f"@reboot cd {ROOT} && PYTHONPATH={ROOT}/src:{ROOT} "
            f"{python_bin} scripts/run_gateway.py --config config/gateway.env >> logs/gateway.log 2>&1 & "
            f"{cron_marker}"
        )

        lines = [l for l in existing_cron.splitlines() if l.strip() and "DJUA_SMS" not in l]
        lines.append(native_cron_cmd)
        new_cron = "\n".join(lines) + "\n"
        proc = subprocess.run(["crontab", "-"], input=new_cron, text=True, capture_output=True)
        if proc.returncode == 0:
            cron_installed = True
            print("✅ Tâche de démarrage direct (Cron @reboot natif sans tmux) configurée.")
    except Exception as exc:
        print(f"⚠️ Erreur configuration crontab : {exc}")

    print("\n" + "=" * 75)
    if systemd_installed:
        print("🚀 Le service systemd est actif et supervisera la passerelle au démarrage.")
        print(f"   Commandes utiles :")
        print(f"     sudo systemctl status {SERVICE_NAME}")
        print(f"     sudo systemctl restart {SERVICE_NAME}")
        print(f"     journalctl -u {SERVICE_NAME} -f")
    elif cron_installed:
        print("🚀 La tâche native @reboot démarrera la passerelle à chaque boot de la machine.")
        print("   Pour passer en service systemd système standard, lancez une fois :")
        print(f"     sudo cp {generated_service_file} /etc/systemd/system/")
        print("     sudo systemctl daemon-reload")
        print(f"     sudo systemctl enable --now {SERVICE_NAME}")
    print("=" * 75)
    return 0


def uninstall_linux() -> int:
    print("\n🐧 [Linux] Désactivation du démarrage automatique...")
    is_root = (os.geteuid() == 0) if hasattr(os, "geteuid") else False
    can_sudo = False
    if not is_root and shutil.which("sudo"):
        res = subprocess.run(["sudo", "-n", "true"], capture_output=True)
        can_sudo = (res.returncode == 0)

    if is_root or can_sudo:
        cmd_prefix = [] if is_root else ["sudo"]
        subprocess.run(cmd_prefix + ["systemctl", "stop", f"{SERVICE_NAME}.service"], capture_output=True)
        subprocess.run(cmd_prefix + ["systemctl", "disable", f"{SERVICE_NAME}.service"], capture_output=True)
        system_service = Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"
        if system_service.exists():
            subprocess.run(cmd_prefix + ["rm", "-f", str(system_service)], capture_output=True)
            subprocess.run(cmd_prefix + ["systemctl", "daemon-reload"], capture_output=True)
            print("   -> ✅ Service systemd système supprimé.")

    try:
        cron_res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if cron_res.returncode == 0:
            lines = [l for l in cron_res.stdout.splitlines() if "DJUA_SMS" not in l]
            new_cron = "\n".join(lines).strip()
            if new_cron:
                subprocess.run(["crontab", "-"], input=new_cron + "\n", text=True, capture_output=True)
            else:
                subprocess.run(["crontab", "-r"], capture_output=True)
            print("   -> ✅ Tâche Cron @reboot retirée.")
    except Exception as exc:
        print(f"   ⚠️ Erreur nettoyage cron : {exc}")

    print("✅ Autostart Linux désactivé.")
    return 0


def status_linux() -> int:
    print("\n🐧 [Linux] Statut du démarrage automatique :")
    system_service = Path("/etc/systemd/system") / f"{SERVICE_NAME}.service"
    if system_service.exists():
        print(f"   - Service systemd installé : {system_service}")
        res = subprocess.run(["systemctl", "is-enabled", f"{SERVICE_NAME}.service"], capture_output=True, text=True)
        print(f"   - Statut enable : {res.stdout.strip() or 'inconnu'}")
        res_active = subprocess.run(["systemctl", "is-active", f"{SERVICE_NAME}.service"], capture_output=True, text=True)
        print(f"   - Statut exécution : {res_active.stdout.strip() or 'inconnu'}")
    else:
        print("   - Aucun service systemd système installé.")

    try:
        cron_res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if cron_res.returncode == 0 and "DJUA_SMS" in cron_res.stdout:
            print("   - Tâche Cron @reboot native : ACTIVE")
        else:
            print("   - Tâche Cron @reboot        : Non configurée")
    except Exception:
        pass
    return 0


# ==============================================================================
# WINDOWS : TASK SCHEDULER (Planificateur de Tâches Professionnel)
# ==============================================================================

def install_windows() -> int:
    print(f"\n" + "=" * 75)
    print(f"🪟 [Windows] Installation du Service en Tâche Planifiée ('{WINDOWS_TASK_NAME}')")
    print("=" * 75)

    launcher = ROOT / "start_djua_gateway_hidden.vbs"
    if not launcher.is_file():
        launcher = ROOT / "start_djua_gateway.bat"
    if not launcher.is_file():
        print(f"❌ Lanceur introuvable : {launcher}")
        return 1

    ps_script = ROOT / "scripts" / "install_windows_test_task.ps1"
    if ps_script.is_file():
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps_script),
            "-Root",
            str(ROOT),
        ]
        res = subprocess.run(cmd)
        if res.returncode == 0:
            print("✅ Tâche planifiée enregistrée (démarrage automatique à l'ouverture de session).")
            print("   Exécution en arrière-plan sans fenêtre CMD bloquante.")
        return res.returncode
    else:
        sch_cmd = [
            "schtasks",
            "/create",
            "/tn",
            WINDOWS_TASK_NAME,
            "/tr",
            f'wscript.exe "{launcher}"',
            "/sc",
            "ONLOGON",
            "/rl",
            "HIGHEST",
            "/f",
        ]
        res = subprocess.run(sch_cmd)
        if res.returncode == 0:
            print(f"✅ Tâche '{WINDOWS_TASK_NAME}' enregistrée avec succès.")
        return res.returncode


def uninstall_windows() -> int:
    print(f"\n🪟 [Windows] Suppression de la tâche planifiée '{WINDOWS_TASK_NAME}'...")
    subprocess.run(["schtasks", "/delete", "/tn", WINDOWS_TASK_NAME, "/f"], capture_output=True)
    subprocess.run(["schtasks", "/delete", "/tn", "DJUA SMS Gateway Test", "/f"], capture_output=True)
    print("✅ Tâche planifiée Windows supprimée.")
    return 0


def status_windows() -> int:
    print(f"\n🪟 [Windows] Statut de la tâche planifiée :")
    sch_cmd = ["schtasks", "/query", "/tn", WINDOWS_TASK_NAME]
    res = subprocess.run(sch_cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"   - Tâche '{WINDOWS_TASK_NAME}' : ACTIVE")
    else:
        res_alt = subprocess.run(["schtasks", "/query", "/tn", "DJUA SMS Gateway Test"], capture_output=True, text=True)
        if res_alt.returncode == 0:
            print("   - Tâche 'DJUA SMS Gateway Test' : ACTIVE")
        else:
            print("   - Aucune tâche planifiée active.")
    return 0


# ==============================================================================
# POINT D'ENTRÉE
# ==============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gestionnaire professionnel d'autodémarrage DJUA_SMS (sans dépendance tmux)."
    )
    parser.add_argument(
        "--action",
        choices=["install", "uninstall", "status"],
        default="install",
        help="Action à exécuter (défaut: install)",
    )
    parser.add_argument(
        "--platform",
        choices=["auto", "linux", "windows"],
        default="auto",
        help="Plateforme cible (défaut: auto)",
    )
    args = parser.parse_args()

    platform = args.platform
    if platform == "auto":
        platform = "windows" if sys.platform.startswith("win") else "linux"

    if platform == "linux":
        if args.action == "install":
            return install_linux()
        elif args.action == "uninstall":
            return uninstall_linux()
        elif args.action == "status":
            return status_linux()
    elif platform == "windows":
        if args.action == "install":
            return install_windows()
        elif args.action == "uninstall":
            return uninstall_windows()
        elif args.action == "status":
            return status_windows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
