#!/usr/bin/env python3
"""Script de diagnostic et de test de connexion du module SIM (SIM800L / SIM868).

Fonctionnalités :
1. Détection automatique des ports série disponibles (USB, UART, GPIO).
2. Scan automatique des débits (9600, 115200, 19200, 38400, 57600 bauds).
3. Test de réponse AT et réveil du modem.
4. Diagnostic matériel complet :
   - Modèle du modem & version firmware (ATI)
   - Numéro IMEI (AT+GSN)
   - Présence et statut de la carte SIM (AT+CPIN?)
   - Qualité du signal GSM en dBm et pourcentage (AT+CSQ)
   - Enregistrement au réseau cellulaire (AT+CREG?)
   - Nom de l'opérateur mobile (AT+COPS?)
   - Mode SMS texte et stockage mémoire (AT+CPMS?)
5. Conseils et diagnostic interactif si le modem est éteint (PWRKEY).
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Ajouter src/ au PYTHONPATH pour réutiliser les modules de la passerelle
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

try:
    import serial
except ImportError:
    print("❌ Erreur : le paquet 'pyserial' n'est pas installé.")
    print("   Installez-le avec : pip install pyserial")
    sys.exit(1)


def find_candidate_ports() -> list[str]:
    """Recherche tous les ports série potentiels sur Linux / Raspberry Pi / Windows."""
    candidates: list[str] = []

    # 1. Liens stables Linux /dev/serial/by-id/*
    by_id = glob.glob("/dev/serial/by-id/*")
    candidates.extend(sorted(by_id))

    # 2. Ports USB classiques Linux
    usb_ports = glob.glob("/dev/ttyUSB*")
    candidates.extend(sorted(usb_ports))

    # 3. Ports ACM (USB CDC)
    acm_ports = glob.glob("/dev/ttyACM*")
    candidates.extend(sorted(acm_ports))

    # 4. UART matériel Raspberry Pi
    if os.path.exists("/dev/serial0"):
        candidates.append("/dev/serial0")
    if os.path.exists("/dev/ttyAMA0"):
        candidates.append("/dev/ttyAMA0")

    # 5. Détection sous Windows si applicable
    if sys.platform.startswith("win"):
        for i in range(1, 33):
            candidates.append(f"COM{i}")

    # Déduplication tout en conservant l'ordre
    unique: list[str] = []
    for c in candidates:
        if c not in unique:
            unique.append(c)
    return unique


def send_at_command(
    ser: serial.Serial,
    command: str,
    timeout: float = 3.0,
    expected_response: str = "OK",
) -> tuple[bool, list[str]]:
    """Envoie une commande AT et retourne le succès et les lignes de réponse."""
    ser.reset_input_buffer()
    cmd_bytes = f"{command}\r\n".encode("latin1")
    ser.write(cmd_bytes)

    lines: list[str] = []
    deadline = time.monotonic() + timeout
    matched = False

    while time.monotonic() < deadline:
        line_bytes = ser.readline()
        if not line_bytes:
            continue
        line = line_bytes.decode("latin1", errors="replace").strip()
        if not line or line == command:
            continue
        lines.append(line)
        if expected_response in line or "OK" in line:
            matched = True
            break
        if "ERROR" in line or "+CME ERROR" in line or "+CMS ERROR" in line:
            matched = False
            break

    return matched, lines


def probe_port(
    port: str,
    baud_rates: list[int],
) -> tuple[int | None, serial.Serial | None]:
    """Tente d'établir le dialogue AT sur un port à différents débits."""
    for baud in baud_rates:
        try:
            ser = serial.Serial(
                port=port,
                baudrate=baud,
                timeout=1.0,
                write_timeout=2.0,
            )
        except Exception:
            continue

        try:
            # Séquence de réveil autobauding SIM800/SIM868
            for _ in range(3):
                ser.write(b"AT\r\n")
                time.sleep(0.15)
            ser.reset_input_buffer()

            # Test AT franc
            ok, _ = send_at_command(ser, "AT", timeout=1.5)
            if ok:
                # Désactiver l'écho pour les commandes suivantes
                send_at_command(ser, "ATE0", timeout=1.0)
                return baud, ser
            ser.close()
        except Exception:
            try:
                ser.close()
            except Exception:
                pass

    return None, None


def pulse_pwrkey_gpio(pin: int = 4) -> bool:
    """Tente une impulsion de démarrage PWRKEY via pinctrl sur Raspberry Pi."""
    print(f"⚡ Tentative d'impulsion PWRKEY sur GPIO {pin} via pinctrl...")
    try:
        # Mettre GPIO en sortie haut (ou bas selon montage) pendant 1.5s
        subprocess.run(["pinctrl", "set", str(pin), "op", "dh"], check=True)
        time.sleep(1.5)
        subprocess.run(["pinctrl", "set", str(pin), "op", "dl"], check=True)
        print("   -> Impulsion PWRKEY envoyée ! Attente du démarrage (3s)...")
        time.sleep(3.0)
        return True
    except Exception as exc:
        print(f"   ⚠️ Impossible de contrôler le GPIO {pin} : {exc}")
        return False


def parse_signal(rssi: int) -> tuple[str, str]:
    """Convertit la valeur RSSI (0-31) en dBm et qualité textuelle."""
    if rssi == 99 or rssi < 0:
        return "Inconnu / Pas de signal", "❌"
    if rssi <= 9:
        dbm = -113 + (rssi * 2)
        return f"{dbm} dBm (Signal Très Faible)", "⚠️"
    if rssi <= 14:
        dbm = -113 + (rssi * 2)
        return f"{dbm} dBm (Signal Faible/Moyen)", "🟡"
    if rssi <= 19:
        dbm = -113 + (rssi * 2)
        return f"{dbm} dBm (Bon signal)", "🟢"
    dbm = -113 + (rssi * 2)
    return f"{dbm} dBm (Excellent signal)", "🌟"


def run_diagnostics(ser: serial.Serial, port: str, baud: int) -> None:
    """Exécute et affiche l'ensemble des diagnostics modem et réseau."""
    print("\n" + "=" * 75)
    print(f"📶 DIAGNOSTIC COMPLET DU MODULE SIM ({port} @ {baud} bauds)")
    print("=" * 75)

    # 1. Modèle & Firmware
    _, ati_lines = send_at_command(ser, "ATI")
    model_str = " ".join(ati_lines) if ati_lines else "SIMCOM (Non précisé)"
    print(f"\n1. 📟 MODULE MODEM :")
    print(f"   - Identification : {model_str}")

    _, imei_lines = send_at_command(ser, "AT+GSN")
    imei = imei_lines[0] if imei_lines else "Non disponible"
    print(f"   - Numéro IMEI    : {imei}")

    # 2. Statut Carte SIM
    print(f"\n2. 💳 CARTE SIM :")
    ok, cpin_lines = send_at_command(ser, "AT+CPIN?")
    cpin_text = " ".join(cpin_lines)
    if "READY" in cpin_text:
        print("   - Statut CPIN    : ✅ READY (Carte présente et déverrouillée)")
    elif "SIM PIN" in cpin_text:
        print("   - Statut CPIN    : ⚠️ PIN REQUIS (La carte nécessite un code PIN)")
    elif "SIM PUK" in cpin_text:
        print("   - Statut CPIN    : ❌ PUK REQUIS (Carte bloquée)")
    else:
        print(f"   - Statut CPIN    : ❓ Non détectée ({cpin_text or 'TIMEOUT'})")

    _, ccid_lines = send_at_command(ser, "AT+CCID")
    if ccid_lines:
        print(f"   - Numéro CCID    : {ccid_lines[0]}")

    # 3. Qualité du Signal
    print(f"\n3. 📡 SIGNAL CELLULAIRE :")
    ok, csq_lines = send_at_command(ser, "AT+CSQ")
    csq_match = None
    for line in csq_lines:
        m = re.search(r"\+CSQ:\s*(\d+)\s*,\s*(\d+)", line)
        if m:
            csq_match = m
            break

    if csq_match:
        rssi_val = int(csq_match.group(1))
        ber_val = int(csq_match.group(2))
        sig_desc, sig_icon = parse_signal(rssi_val)
        print(f"   - RSSI           : {rssi_val}/31 {sig_icon} -> {sig_desc}")
        print(f"   - Taux d'erreur  : BER={ber_val}")
    else:
        print("   - RSSI           : Non disponible")

    # 4. Enregistrement Réseau
    print(f"\n4. 🌐 ENREGISTREMENT RÉSEAU (CREG) :")
    ok, creg_lines = send_at_command(ser, "AT+CREG?")
    creg_match = None
    for line in creg_lines:
        m = re.search(r"\+CREG:\s*(?:\d+,)?(\d+)", line)
        if m:
            creg_match = m
            break

    if creg_match:
        stat = int(creg_match.group(1))
        status_map = {
            0: "Non enregistré, recherche inactive",
            1: "✅ Enregistré sur le réseau national (HOME)",
            2: "🔄 En cours de recherche du réseau...",
            3: "❌ Enregistrement refusé",
            4: "❓ Inconnu",
            5: "✅ Enregistré en itinérance (ROAMING)",
        }
        print(f"   - Statut CREG    : {status_map.get(stat, str(stat))}")
    else:
        print("   - Statut CREG    : Non disponible")

    # Opérateur
    _, cops_lines = send_at_command(ser, "AT+COPS?")
    cops_str = "Non détecté"
    for line in cops_lines:
        if '+COPS:' in line:
            cops_str = line.replace('+COPS:', '').strip()
            break
    print(f"   - Opérateur      : {cops_str}")

    # 5. Service SMS
    print(f"\n5. ✉️ SERVICE SMS :")
    ok_cmgf, _ = send_at_command(ser, "AT+CMGF=1")
    print(f"   - Mode Texte     : {'✅ Activé (CMGF=1 OK)' if ok_cmgf else '❌ Échec'}")

    _, cpms_lines = send_at_command(ser, "AT+CPMS?")
    storage_info = " ".join(cpms_lines) if cpms_lines else "Non disponible"
    print(f"   - Mémoire SMS    : {storage_info}")

    # 6. Conclusion et configuration passerelle
    print("\n" + "=" * 75)
    print("🚀 CONCLUSION POUR LA PASSERELLE DJUA_SMS :")
    print("=" * 75)
    print("Le module SIM répond parfaitement aux commandes AT !")
    print("Pour l'utiliser avec DJUA_SMS, reportez ces valeurs dans 'config/gateway.env' :")
    print(f"\n   SERIAL_PORT={port}")
    print(f"   SERIAL_BAUD_RATE={baud}")
    print(f"   GSM_SMS_STORAGE=SM\n")
    print("=" * 75)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Outil de test et diagnostic de connexion pour module SIM800 / SIM868."
    )
    parser.add_argument(
        "--port",
        default=None,
        help="Port série explicite (/dev/ttyUSB0, COM16, etc.). Si omis, auto-détection.",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=None,
        help="Débit en bauds explicite (9600, 115200, etc.). Si omis, scan automatique.",
    )
    parser.add_argument(
        "--pulse-pwrkey",
        type=int,
        nargs="?",
        const=4,
        default=None,
        help="Envoie une impulsion sur le GPIO de démarrage (par défaut GPIO 4 sur Raspberry Pi).",
    )
    args = parser.parse_args()

    print("=" * 75)
    print("🔍 TEST DE CONNEXION DU MODULE SIM (DJUA_SMS)")
    print("=" * 75)

    if args.pulse_pwrkey is not None:
        pulse_pwrkey_gpio(args.pulse_pwrkey)

    # 1. Sélection ou recherche des ports
    if args.port:
        candidate_ports = [args.port]
    else:
        print("🔎 Recherche automatique des ports série disponibles...")
        candidate_ports = find_candidate_ports()

    if not candidate_ports:
        print("❌ Aucun port série (USB ou UART) n'a été détecté sur la machine !")
        print("   Vérifiez que le câble USB du SIM868 est bien branché sur la Raspberry Pi.")
        return 1

    print(f"📋 Ports candidats trouvés : {', '.join(candidate_ports)}")

    # 2. Débits à tester
    if args.baud:
        baud_list = [args.baud]
    else:
        baud_list = [9600, 115200, 19200, 57600, 38400]

    # 3. Test de dialogue AT sur chaque port
    active_port: str | None = None
    active_baud: int | None = None
    active_ser: serial.Serial | None = None

    for port in candidate_ports:
        print(f"\n🔌 Test du port {port}...")
        baud, ser = probe_port(port, baud_list)
        if ser and baud:
            active_port = port
            active_baud = baud
            active_ser = ser
            print(f"   -> ✅ Modem SIM détecté et réactif sur {port} à {baud} bauds !")
            break
        else:
            print(f"   -> ⚠️ Aucune réponse AT sur {port}")

    if not active_ser or not active_port or not active_baud:
        print("\n" + "!" * 75)
        print("❌ LE MODULE SIM N'A RÉPONDU SUR AUCUN PORT.")
        print("!" * 75)
        print("Diagnostic des causes les plus fréquentes :")
        print(" 1. Le module SIM868 est éteint :")
        print("    -> Le câble USB alimente seulement le convertisseur CP2102.")
        print("    -> Appuyez pendant 1 à 2 secondes sur le bouton poussoir PWRKEY.")
        print("    -> Vérifiez que la LED 'PWR' et la LED 'NET' (ou 'STATUS') clignotent.")
        print(" 2. Vous pouvez tenter de l'allumer via GPIO avec :")
        print("    python3 scripts/test_sim_connection.py --pulse-pwrkey 4")
        print(" 3. Cavaliers / Jumpers UART :")
        print("    -> Si c'est une carte HAT, vérifiez que les jumpers RX/TX sont sur 'USB'.")
        print("!" * 75)
        return 2

    try:
        run_diagnostics(active_ser, active_port, active_baud)
        return 0
    finally:
        active_ser.close()


if __name__ == "__main__":
    sys.exit(main())
