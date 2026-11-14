# DJUA_SMS — Passerelle de Télémétrie SMS (GSM -> SQLite -> HTTP / MQTT)

Passerelle légère de télémétrie développée pour le projet **DJUA ENERGY** (Orange Énergie RDC).
Elle assure la réception des SMS émis par les boîtiers solaires IoT, leur persistance locale sans perte, leur normalisation conforme aux contrats d'interface, et leur transmission automatique vers le Backend Cloud (**HTTP REST** et/ou **MQTT**).

## Règle absolue

Le dépôt `DJUA` reste **READ ONLY**.  
Toutes les implémentations de la gateway et de la chaîne de transport sont réalisées dans `DJUA_SMS`.

## Architecture du flux

```text
Boîtier IoT Solaire (ESP32 + SIM800C)
      |
      | SMS GSM-7 (D2T2 / D2E)
      v
SIM868 récepteur (sur Raspberry Pi 5 ou PC Windows)
      |
      v
PySerialTransport / Commandes AT (+CMTI -> CMGR)
      |
      v
SmsIngestionService
      |
      +--> SQLite inbound_sms (COMMIT durable)
      +--> Déduplication et anti-rejeu (sequence / message_id)
      +--> Validation & vérification HMAC-SHA256
      +--> Normalisation JSON (contrat D2T2 / D2E)
      +--> Insertion dans mqtt_outbox (statut PENDING)
      |
      v (seulement après persistance SQLite)
Suppression sécurisée du SMS sur SIM (CMGD=<index>)
      |
      +-------------------------------------------+
      |                                           |
      v                                           v
[HTTP Outbox Worker]                     [MQTT Outbox Worker]
      |                                           |
      v (POST JSON 2xx)                           v (QoS 1 / PUBACK)
Backend Render (DJUA Cloud)               Broker MQTT
https://djua-energy-backend.onrender.com
```

## Règle critique de non-perte

```text
CMGR
 -> SQLite COMMIT durable
 -> seulement ensuite CMGD=<index>
```

Le SMS n'est **jamais** supprimé de la mémoire SIM tant que son écriture brute sur disque (SQLite) n'est pas acquittée.

## Modes de Transport Backend (`BACKEND_TRANSPORT`)

Le transport est sélectionné par la variable `BACKEND_TRANSPORT` dans le `.env` :

1. **`http`** (Recommandé pour déploiement direct Cloud sans broker) :
   - Exécute des requêtes `POST` directes vers l'API Backend.
   - Endpoint télémétrie : `POST /api/iot/telemetry`.
   - Endpoint alertes urgentes geofence : `POST /api/iot/alerts`.
   - En-têtes : `Content-Type: application/json`, `x-device-token: djua`, `X-DJUA-Topic`, `Idempotency-Key`.
   - Retries automatiques avec backoff exponentiel en cas d'erreur réseau / serveur (codes 5xx ou 429).
2. **`mqtt`** (Transport historique) :
   - Publication QoS 1 avec écoute du `PUBACK` vers le broker MQTT.
3. **`both`** :
   - Double diffusion simultanée HTTP + MQTT avec suivi d'état indépendant pour chaque protocole.

## Format Télémétrique JSON final émis vers le Backend

Lorsqu'un SMS D2T2 est reçu et normalisé, le corps JSON suivant est transmis au Backend :

```json
{
  "kit_id": "DJUA-KIN-000001",
  "protocol": "D2T2",
  "sequence": 12345,
  "message_id": "D2:DJUA-KIN-000001:9IX",
  "uptime_ms": 123456789,
  "timestamp_ms": 123456789,
  "interval_seconds": 1800,
  "timestamp": "2026-09-27T16:30:00+01:00",
  "timezone": "GMT+1",
  "gateway_received_at": "2026-11-13T14:33:39.678995+00:00",
  "auth_status": "VERIFIED",

  "latitude": -4.3251,
  "longitude": 15.3222,

  "battery": {
    "voltage_v": 12.4,
    "current_a": 0.5,
    "power_w": 6.2
  },

  "solar": {
    "voltage_v": 18.2,
    "current_a": 1.23,
    "power_w": 22.4,
    "energy_interval_wh": 11.2
  },

  "dc_load": {
    "voltage_v": 12.35,
    "current_a": 6.4,
    "power_w": 79.0,
    "energy_interval_wh": 19.76,
    "measured_count": 2
  },

  "ac_load": {
    "voltage_v": 230.1,
    "current_a": 1.25,
    "active_power_w": 244.5,
    "apparent_power_va": 287.6,
    "energy_interval_wh": 122.25
  },

  "validity": {
    "rtc": true,
    "gps": true,
    "battery": true,
    "solar": true,
    "solar_energy": true,
    "dc_load": true,
    "dc_load_energy": true,
    "ac": true,
    "ac_energy": true
  }
}
```

## Démarrage et Tests

### 1. Installation

```bash
python -m pip install -r requirements.txt
```

### 2. Configuration d'environnement

Copier `.env` ou `config/gateway.env` et renseigner les paramètres du modem et du backend :
- `SERIAL_PORT` (`COM16` sous Windows, `/dev/ttyUSB0` sous Linux / Pi 5)
- `BACKEND_TRANSPORT=http`
- `HTTP_BACKEND_URL=https://djua-energy-backend.onrender.com/api/iot/telemetry`
- `HTTP_EVENTS_URL=https://djua-energy-backend.onrender.com/api/iot/alerts`
- `HTTP_EXTRA_HEADERS_JSON={"x-device-token": "djua"}`

### 3. Test d'envoi Passerelle -> Backend (sans modem physique)

Un script d'intégration de bout en bout est disponible pour tester la chaîne complète :
```bash
python scripts/test_gateway_to_backend.py
```

### 4. Lancement de la Passerelle en continu

- **Sous Windows** :
  ```bash
  start_djua_gateway.bat
  ```
- **Sous Raspberry Pi 5** :
  ```bash
  sudo systemctl start djua-sms-gateway.service
  ```

### 5. Suite de Tests Automatisés

```bash
python -m unittest discover -s tests -p "test_*.py"
```
Couvre 269 tests unitaires et d'intégration (conformité D1/D2/D2T2, cryptographie HMAC, migrations SQLite, workers HTTP et MQTT).

## Documentation

- [Exemples concrets de SMS de test (D2T2, D2E, D1)](docs/exemples_sms_test.md)
- [Règles du projet](AGENTS.md)
- [Architecture](docs/architecture.md)
- [Protocole SMS D1](docs/sms_protocol.md)
- [Protocole SMS D2](docs/sms_protocol_v2.md)
- [Protocole SMS D2T2 compact + charge DC](docs/sms_protocol_d2t2.md)
- [Contrat de données backend](docs/backend_data_contract.md)
- [Transport GSM/SMS](docs/gsm_transport.md)
- [Stockage SQLite](docs/storage.md)
- [Fiabilité et reprise](docs/reliability.md)
- [Contrat MQTT](docs/mqtt_contract.md)
- [Transport MQTT](docs/mqtt_transport.md)

## Composants implémentés

1. **D1**
   - parser ;
   - validator ;
   - normalizer.

2. **Persistance**
   - SQLite `sqlite3` ;
   - `inbound_sms` ;
   - déduplication brute et logique ;
   - `mqtt_outbox` persistante ;
   - recovery.

3. **MQTT**
   - `paho-mqtt==2.1.0` ;
   - QoS 1 ;
   - mapping `mid -> outbox_id` ;
   - PUBACK ;
   - retry/backoff ;
   - reconnexion.

4. **GSM/SMS récepteur**
   - `pyserial==3.5` ;
   - transport série portable ;
   - commandes AT ;
   - CPIN / CREG / CSQ / CMGF / CPMS / CNMI ;
   - `+CMTI` ;
   - CMGR / CMGL / CMGD précis ;
   - startup recovery ;
   - reconnexion série ;
   - suppression seulement après persistance durable.

## Installation

```bash
python -m pip install -r requirements.txt
```

La configuration de référence est dans `.env.example`.

Aucun port COM ni secret n'est codé en dur.

## Tests

Le dépôt possède un workflow GitHub Actions qui exécute :

```text
python -m compileall -q src tests scripts
PYTHONPATH=src:. python -m unittest discover -s tests -p 'test_*.py'
```

La suite couvre D1/GSM/MQTT ainsi que D2T/D2T2/D2E, HMAC, GSM-7, migration SQLite, déduplication/conflits et flux GSM/MQTT simulés. Le résultat exact du dernier run CI doit être utilisé comme preuve, plutôt qu'un compteur statique dans ce fichier.

## Diagnostics matériels

Probe série :

```bash
PYTHONPATH=src python scripts/serial_probe.py --port <PORT> --baud 9600
```

Diagnostic modem :

```bash
PYTHONPATH=src python scripts/modem_test.py --port <PORT> --baud 9600
```

Réception SMS interactive et sûre :

```bash
PYTHONPATH=src python scripts/sms_receive_test.py --port <PORT> --baud 9600
```

Le dernier script ne supprime un SMS qu'après confirmation durable par SQLite.

## Validation matérielle

```text
TEST MOCK / SÉRIE SIMULÉ D2 : EFFECTUÉ
RÉCEPTEUR MATÉRIEL            : SIM868 CONFIRMÉ PAR LE PROJET
AT/SMS PILOTE HISTORIQUE      : A DÉJÀ FONCTIONNÉ AVEC SIM868
VRAI SMS D2                   : NON TESTÉ DANS CETTE PHASE
BACKEND RÉEL D2               : NON VALIDÉ
```

Les scripts sont prêts pour le poste physique, mais l'environnement GitHub/ChatGPT n'a pas accès à son port COM.

## Hors périmètre après cette phase

Ne pas commencer automatiquement :

- modification du firmware `DJUA` ;
- émetteur SMS ESP32 ;
- modification D1 ;
- service Windows ;
- Docker.

Attendre une autorisation explicite pour l'étape suivante.

## D2T / D2T2 / D2E

D2 étend la gateway existante ; il ne crée pas une deuxième chaîne de réception.

```text
D1,   -> comportement historique
D2T,  -> télémétrie périodique legacy
D2T2, -> télémétrie compacte + charge DC
D2E,  -> événement urgent GX/GE
```

D2T contient exactement 22 champs et son maximum authentifié est 160 septets GSM-7. D2T2 conserve les mesures D2T, ajoute tension/courant/puissance/énergie de charge DC dans un payload compact de 60 octets, et son maximum authentifié est 130 septets. D2E contient 11 champs et son maximum est 97 septets.

Le `message_id` est dérivé côté gateway sous la forme `D2:<device_id>:<sequence_base36>`. Un même message_id avec le même contenu signé est un replay ; avec un contenu signé différent, il devient `MESSAGE_ID_CONFLICT` et aucune seconde outbox n'est créée.

La configuration D2 utilise `D2_AUTH_MODE`, `D2_HMAC_KEYS_JSON` et `D2_SENDER_BINDINGS_JSON`. Aucun secret réel ne doit être committé.

Le script `sms_receive_test.py` charge cette configuration depuis l'environnement.


## Automatisation Windows temporaire

Pour la phase de test, DJUA_SMS peut fonctionner sans commande quotidienne et sans service Windows.

Double-cliquer une seule fois sur :

\`\`\`text
setup_windows_test.bat
\`\`\`

Le script :

1. crée \`.venv\` si nécessaire ;
2. installe/vérifie les dépendances ;
3. crée \`config/gateway.env\` à partir du modèle local ;
4. ouvre ce fichier dans le Bloc-notes si une configuration est nécessaire ;
5. vérifie la configuration sans ouvrir le modem ni MQTT ;
6. installe la tâche Windows \`DJUA SMS Gateway Test\` ;
7. démarre immédiatement la gateway en arrière-plan.

Au prochain logon Windows, la tâche relance automatiquement DJUA_SMS.

Le lanceur permanent est \`scripts/run_gateway.py\` et réutilise directement :

\`\`\`text
SIM868 -> SmsReceiver -> SQLite -> D1/D2T/D2T2/D2E -> mqtt_outbox -> MQTT
\`\`\`

La console est masquée par \`start_djua_gateway_hidden.vbs\`. Le lanceur batch redémarre le processus après une erreur fatale avec un délai de 10 secondes.

La configuration locale est \`config/gateway.env\`. Le modèle propose déjà \`COM16\`, 9600 bauds et \`D2_AUTH_MODE=development\`. \`MQTT_HOST\` doit être renseigné avec le broker utilisé pour les essais.

Les logs sont écrits dans \`logs/gateway.log\`, avec rotation à 5 MiB et cinq sauvegardes.

Pour arrêter proprement la gateway sans CMD, double-cliquer sur \`stop_djua_gateway.bat\`.

Pour arrêter et retirer le démarrage automatique, double-cliquer sur \`disable_windows_test_autostart.bat\`.

Les vrais secrets D2/MQTT restent uniquement dans \`config/gateway.env\`, qui est ignoré par Git.

## Raspberry Pi 5

Installation : `bash scripts/setup_pi5.sh`. Le script crée `.venv`, installe `requirements.txt`, prépare `config/`, `data/` et `logs/`, puis vérifie la configuration.

Le modèle utilise `MQTT_HOST=CHANGE_ME` : renseignez l'hôte et les credentials dans `config/gateway.env`, puis relancez le script pour valider la configuration.

Choisissez le port avec `SERIAL_PORT=/dev/ttyUSB0`, `/dev/serial/by-id/...` ou `/dev/serial0` pour l'UART GPIO ; `GATEWAY_PLATFORM=linux` active la validation Linux.

Ajoutez l'utilisateur au groupe série si n?cessaire : `sudo usermod -aG dialout "$USER"`.

```bash
bash scripts/setup_pi5.sh --install-service
sudo systemctl status djua-sms-gateway
sudo systemctl restart djua-sms-gateway
sudo systemctl stop djua-sms-gateway
sudo journalctl -u djua-sms-gateway -f
```

Pour basculer entre Windows et Pi, copiez le bon exemple vers `config/gateway.env`, ou lancez `scripts/run_gateway.py --config <fichier-env>`.
