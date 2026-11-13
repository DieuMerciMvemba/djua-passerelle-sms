# Validation Matérielle Réelle — Raspberry Pi 5 & SIM868

**Statut du document :** CONFIRMÉ PAR MATÉRIEL RÉEL & TESTÉ SUR POSTE PHYSIQUE  
**Date de validation :** 13 Novembre 2026  
**Environnement d'exécution :** Raspberry Pi 5 (Debian GNU/Linux 13 trixie, kernel `6.18.50+rpt-rpi-2712 aarch64`)

---

## 1. Contexte et Objectif

Le projet **DJUA_SMS** sert de passerelle légère entre les boîtiers solaires IoT (ESP32 + SIM800C) et le backend de gestion de l'énergie.
Ce document consigne la validation matérielle réelle effectuée sur le récepteur **SIM868** connecté en USB à la **Raspberry Pi 5**, ainsi que la transmission effective des télémétries vers le backend local et le backend cloud.

---

## 2. Synthèse Matérielle Confirmée

| Composant | Identification Réelle | Statut |
| :--- | :--- | :--- |
| **Hôte passerelle** | Raspberry Pi 5 (BCM2712 aarch64) | ✅ Opérationnel |
| **Pont USB/Série** | Silicon Labs CP2102 USB to UART Bridge (`/dev/ttyUSB0`) | ✅ Détecté (`driver cp210x`) |
| **Lien matériel fixe** | `/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0` | ✅ Recommandé |
| **Module GSM/GNSS** | SIMCOM SIM868 (Firmware `R14.18`) | ✅ Dialoguant AT |
| **Numéro IMEI** | `868298062931614` | ✅ Vérifié |
| **Carte SIM** | CCID `89243841182472111102` (RDC +243) | ✅ Déverrouillée (`READY`) |
| **Opérateur GSM** | **Orange RDC** (MCC/MNC `63086`) | ✅ Connecté |
| **Enregistrement réseau**| Statut CREG `HOME` (Réseau national) | ✅ Enregistré |
| **Qualité du signal** | RSSI `13-15/31` (~ -85 dBm, BER 0) | ✅ Bon signal stable |
| **Mémoire SMS** | Mémoire SIM `SM` (capacité 10 messages) | ✅ `AT+CMGF=1` OK |

---

## 3. Architecture et Flux Validés

```text
Boîtier Solaire DJUA (ESP32)
       │ (SMS D2T2 / D2E GSM-7)
       ▼
Antenne GSM -> Module SIM868 (Orange RDC)
       │ (Liaison UART / USB CP2102 @ 9600 bauds)
       ▼
Raspberry Pi 5 (/dev/ttyUSB0)
       │
       ├─► AtProtocol (Interception URC +CMTI: "SM", <index>)
       │
       ├─► SmsReceiver (Lecture CMGR <index>)
       │
       ├─► SmsIngestionService (Validation syntaxe + décodage D2T2 compact)
       │
       ├─► SQLite inbound_sms (COMMIT durable)
       │
       ├─► Suppression sécurisée SIM (CMGD=<index> autorisé UNIQUEMENT après COMMIT)
       │
       ├─► SQLite outbox (Statut PENDING)
       │
       └─► HttpOutboxWorker (Expédition HTTP REST POST)
              │
              ├─► Backend Local (Labo) : http://10.20.20.251:5000/api/iot/telemetry
              │
              └─► Backend Cloud : https://djua-energy-backend.onrender.com/api/iot/telemetry
```

---

## 4. Règle Critique de Non-Perte SMS

La passerelle applique strictement l'invariant de persistance :
1. `+CMTI` notifie un nouveau SMS en mémoire `SM`.
2. Le SMS brut est lu par `CMGR`.
3. Il est persisté avec succès dans la table `inbound_sms` de SQLite (`COMMIT`).
4. **Seulement ensuite**, la commande `AT+CMGD=<index>` est transmise au modem pour libérer l'emplacement SIM.
5. Si l'enregistrement SQLite échoue, le SMS reste intact sur la SIM.
6. La commande `AT+CMGD=1,4` est **formellement proscrite**.

---

## 5. Scripts et Outils de Diagnostic Développés

### 5.1 Diagnostic du Module SIM (`scripts/test_sim_connection.py`)

Outil d'inspection automatique multi-bauds et multi-ports :
- Détecte automatiquement les ports `/dev/ttyUSB*`, `/dev/serial/by-id/*` ou `/dev/serial0`.
- Scanne les vitesses (`9600`, `115200`, `19200`, etc.).
- Affiche le rapport complet (IMEI, SIM, Signal, Réseau, Opérateur, SMS).

```bash
python3 scripts/test_sim_connection.py
```

### 5.2 Test Bout-en-Bout Backend Local (`scripts/test_local_backend.py`)

Injecte un payload D2T2 conforme avec mesures solaires, batterie et charges, puis vérifie la mise à jour via l'API REST :

```bash
python3 scripts/test_local_backend.py
```

Résultat vérifié :
- Code réponse HTTP : `200 OK`
- Statut du boîtier côté backend : `active`

### 5.3 Gestionnaire de Session d'Arrière-Plan (`scripts/djua_tmux.sh` / `dev`)

Permet d'exécuter la passerelle dans une session `tmux` indépendante du terminal SSH :
- Démarrer : `bash scripts/djua_tmux.sh start`
- S'attacher à la console en direct : `dev` ou `bash scripts/djua_tmux.sh attach`
- Vérifier le statut : `bash scripts/djua_tmux.sh status`
- Consulter les logs : `bash scripts/djua_tmux.sh logs`
- Arrêter proprement : `bash scripts/djua_tmux.sh stop`

---

## 6. Configuration Active (`config/gateway.env`)

```ini
DATABASE_PATH=data/djua_sms_gateway.db
GATEWAY_LOG_PATH=logs/gateway.log
GATEWAY_LOG_LEVEL=INFO
GATEWAY_STOP_FILE=data/gateway.stop
GATEWAY_PLATFORM=linux

# Port série USB CP2102
SERIAL_PORT=/dev/serial/by-id/usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0
SERIAL_BAUD_RATE=9600
GSM_SMS_STORAGE=SM
GSM_CNMI=2,1,0,0,0

# Mode de sécurité D2
D2_AUTH_MODE=development
D2_HMAC_KEYS_JSON={}
D2_SENDER_BINDINGS_JSON={}

# Transport HTTP vers Backend Local
BACKEND_TRANSPORT=http
HTTP_BACKEND_URL=http://10.20.20.251:5000/api/iot/telemetry
HTTP_EVENTS_URL=http://10.20.20.251:5000/api/iot/alerts
HTTP_EXTRA_HEADERS_JSON={"x-device-token": "djua"}
HTTP_TIMEOUT_SECONDS=10
```

---

## 7. Démarrage Automatique (Autostart)

Pour que la passerelle redémarre toute seule au démarrage de la machine (après une coupure de courant ou un reboot) :
- **Sur Linux / Raspberry Pi** : via `systemd` (`djua-sms-gateway.service`) et/ou tâche cron `@reboot`.
- **Sur Windows** : via le Planificateur de Tâches Windows (`DJUA SMS Gateway Test`).
- Script unifié : `python3 scripts/install_autostart.py`.
