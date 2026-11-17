# Guide des Formats SMS D2E (Alertes & Geofencing)

Ce document récapitule la syntaxe exacte et tous les formats valides de messages d'alerte **D2E** acceptés sans rejet par la passerelle `DJUA_SMS` et transmis au backend (en local ou sur le Cloud).

---

## 1. La Règle d'or : 11 champs obligatoires (10 virgules)

Le format strict défini par le protocole D2E est :

```text
D2E,DEV,SEQ,RTC,UP,EV,LAT,LON,DIST,F,AUTH
```

| N° | Champ | Description | Valeurs acceptées |
|:---|:---|:---|:---|
| 1 | `D2E` | En-tête de protocole | Fixe `D2E` |
| 2 | `DEV` | Identifiant de l'équipement | Ex: `DJUA-KIN-000001` ou `ESP32-001` |
| 3 | `SEQ` | Numéro de séquence (compteur) | Entier en base36 (`1`..`1Z141Z3`). **Doit être incrémenté à chaque SMS pour éviter le rejet anti-doublon**. |
| 4 | `RTC` | Horodatage RTC (secondes Epoch) | Secondes en base36, ou `-` si absent/non synchronisé |
| 5 | `UP` | Uptime (durée de fonctionnement) | Millisecondes en base36 (`0`..`1Z141Z3`), ex: `0`, `100`, `21I6CG` |
| 6 | `EV` | Type d'événement geofence | `GX` (Geofence Exit / Sortie) ou `GE` (Geofence Enter / Entrée) |
| 7 | `LAT` | Latitude GPS (dix-millièmes de degré) | Valeur en base36 (ex: `-99Q6` pour -4.3251°), ou `-` |
| 8 | `LON` | Longitude GPS (dix-millièmes de degré)| Valeur en base36 (ex: `WU9O` pour 15.3222°), ou `-` |
| 9 | `DIST` | Distance au centre (mètres) | Entier en base36 (`0`..`LFLS` soit 0 à 1 000 000 m), ou `-` |
| 10 | `F` | Drapeaux de validité (2 caractères) | `00` (aucun), `01` (RTC seul), `02` (GPS seul), `06` (GPS+Dist), `07` (RTC+GPS+Dist) |
| 11 | `AUTH` | Signature d'authentification | `-` en mode développement, ou HMAC-SHA256 (11 car.) en production |

---

## 2. Table des correspondances pour les drapeaux `F`

Le champ `F` doit correspondre exactement aux données fournies :
- **`00`** : Pas de RTC (`-`), pas de GPS (`-`), pas de distance (`-`).
- **`01`** : RTC valide renseigné, pas de GPS ni distance.
- **`02`** : Coordonnées GPS valides renseignées, pas de distance ni RTC.
- **`06`** : Coordonnées GPS ET Distance renseignées, pas de RTC.
- **`07`** : RTC, GPS ET Distance tous renseignés.

---

## 3. Table des séquences utiles (Base36)

> [!IMPORTANT]
> Pour déclencher une **nouvelle transmission vers le backend**, la séquence `SEQ` doit être nouvelle (différente des SMS déjà reçus).

| Décimal | Base36 | Remarque |
|:---:|:---:|:---|
| 10 | `A` | *(Déjà utilisé lors des essais précédents)* |
| 11 | `B` | **Prêt à l'emploi** |
| 12 | `C` | **Prêt à l'emploi** |
| 13 | `D` | **Prêt à l'emploi** |
| 14 | `E` | **Prêt à l'emploi** |
| 15 | `F` | **Prêt à l'emploi** |
| 20 | `K` | **Prêt à l'emploi** |
| 36 | `10` | **Prêt à l'emploi** |

---

## 4. SMS prêts à copier-coller et envoyer

### Format 1 : Événement GX (Sortie de zone) Minimal - Sans GPS
*Idéal pour un test rapide au clavier : simple, court et valide à 100%.*
```text
D2E,DJUA-KIN-000001,B,-,0,GX,-,-,-,00,-
```
- Séquence : `B` (11)
- Événement : `GX` (Geofence Exit)
- Pas de GPS ni distance (`-,-,-`) avec drapeaux `00`
- Auth : `-`

---

### Format 2 : Événement GE (Entrée de zone) Minimal - Sans GPS
```text
D2E,DJUA-KIN-000001,C,-,100,GE,-,-,-,00,-
```
- Séquence : `C` (12)
- Événement : `GE` (Geofence Enter)
- Uptime : `100` (1296 ms)
- Auth : `-`

---

### Format 3 : Sortie de zone avec Coordonnées GPS et Distance
*Exemple avec position réelle à Kinshasa (-4.3251°, 15.3222°) et 95 m de distance :*
```text
D2E,DJUA-KIN-000001,D,-,21I6CG,GX,-99Q6,WU9O,2N,06,-
```
- Séquence : `D` (13)
- Latitude : `-99Q6`
- Longitude : `WU9O`
- Distance : `2N` (95 mètres)
- Drapeaux : `06` (GPS + Distance valides)

---

### Format 4 : Complet (Horodatage RTC + GPS + Distance)
```text
D2E,DJUA-KIN-000001,E,TM14E0,21I6CG,GX,-99Q6,WU9O,2N,07,-
```
- Séquence : `E` (14)
- RTC : `TM14E0`
- Drapeaux : `07` (RTC + GPS + Distance tous valides)

---

## 5. Ce qui se passe à la réception par la passerelle

1. **Ingestion et validation** :
   - Le message est enregistré de manière permanente dans la table SQLite `inbound_sms`.
   - La passerelle vérifie la conformité des 11 champs et l'absence de rejeu.
   - Le SMS est acquitté et supprimé de la carte SIM (`SMS_DELETE_OK`).

2. **Création du paquet sortant (Outbox)** :
   - Topic : `djua/test/DJUA-KIN-000001/geofence/events`
   - Clé d'idempotence : `D2:DJUA-KIN-000001:<SEQ>`

3. **Expédition HTTP immédiate vers le Backend** :
   - URL appelée : `POST /api/iot/<device_id>/alerts`
   - Headers :
     - `Content-Type: application/json`
     - `x-device-token: djua`
   - Payload JSON normalisé :
     ```json
     {
       "protocol": "D2E",
       "kit_id": "DJUA-KIN-000001",
       "sequence": 11,
       "message_id": "D2:DJUA-KIN-000001:B",
       "event": "GEOFENCE_EXIT",
       "state": "OUTSIDE",
       "uptime_ms": 0,
       "position_usable": false,
       "latitude": null,
       "longitude": null,
       "distance_m": null,
       "validity": {
         "rtc": false,
         "gps": false,
         "distance": false
       },
       "auth_status": "NOT_VERIFIED",
       "gateway_received_at": "2026-11-17T18:44:34Z"
     }
     ```
   - Accusé de réception retourné par le backend consigné dans les logs.
