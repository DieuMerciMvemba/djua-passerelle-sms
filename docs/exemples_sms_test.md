# Exemples Concrets de SMS pour Tester la Passerelle

Ce guide rassemble des exemples réels de SMS que tu peux envoyer directement au numéro de la carte SIM insérée dans le modem récepteur de la passerelle (SIM868), ou injecter localement dans les scripts de test.

---

## 1. Télémétrie Périodique Complète (Protocole D2T2)

C'est le message principal envoyé par le boîtier solaire toutes les 30 minutes (ou intervalle configuré).

### SMS brut à copier/coller :
```text
D2T2,DJUA-KIN-000001,AAAwOWq5NngHW80VA4R-WaCBdhPGDgAH0AB8RxgBM4AOAAARgj9B9AmNBZ4ABfgjA-AyAAGLAAHuAH_Q,-
```

> **Note sur le tiret final (`-`)** : En mode développement (`D2_AUTH_MODE=development`), le tiret `-` remplace la signature HMAC pour permettre de tester sans clé de provisionnement.

### Ce que ce SMS contient concrètement :
- **Identifiant du kit** : `DJUA-KIN-000001`
- **Batterie** : 12.4 V / 0.5 A / 6.2 W
- **Panneau solaire** : 18.2 V / 1.23 A / 22.4 W / 11.2 Wh
- **Charge DC** : 12.35 V / 6.4 A (avec 2 équipements DC comptabilisés) / 79.0 W / 19.76 Wh
- **Charge AC** : 230.1 V / 1.25 A / 244.5 W / 122.25 Wh
- **Localisation GPS** : Latitude `-4.3251`, Longitude `15.3222`
- **Horodatage RTC** : 27 septembre 2026 à 16:30:00 (GMT+1)

---

## 2. Alerte Urgente Anti-Vol / Geofence (Protocole D2E)

Ce SMS est généré immédiatement par l'ESP32 dès que le kit est déplacé au-delà de son périmètre de sécurité (cercle de 90 mètres).

### SMS brut à copier/coller :
```text
D2E,DJUA-KIN-000001,10,GX,-432510,1532220,105,06,-
```

### Ce que ce SMS contient concrètement :
- **Identifiant du kit** : `DJUA-KIN-000001`
- **Numéro de séquence** : `10`
- **Type d'événement** : `GX` (Geofence Exit / Sortie de zone autorisée)
- **Position d'infraction** : Latitude `-4.32510`, Longitude `15.32220`
- **Distance d'éloignement constatée** : `105 mètres`
- **Traitement par la passerelle** : Traité en priorité absolue avant la télémétrie ordinaire, routé vers `/api/iot/alerts`.

---

## 3. Télémétrie Minimale (Kit en Démarrage ou Capteurs Absents)

Ce SMS simule un boîtier dont aucun capteur n'est encore raccordé ou dont les mesures sont invalides (flags à zéro).

### SMS brut à copier/coller :
```text
D2T2,DJUA-KIN-000001,AAAACgAAAAAAAAAAAAUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,-
```

### Ce que ce SMS contient concrètement :
- Toutes les grandeurs physiques électriques et de géolocalisation sont décodées à `null`.
- Tous les drapeaux du bloc `validity` sont positionnés à `false`.
- Aucun faux zéro n'est envoyé au backend.

---

## 4. Télémétrie avec Signature Réelle (Mode Production)

Exemple d'un SMS signé avec une clé HMAC-SHA256 officielle de test (`000102030405060708090A0B0C0D0E0F101112131415161718191A1B1C1D1E1F`) :

### SMS brut :
```text
D2T2,DJUA-KIN-000001,AAAwOWq5NngHW80VA4R-WaCBdhPGDgAH0AB8RxgBM4AOAAARgj9B9AmNBZ4ABfgjA-AyAAGLAAHuAH_Q,SR_lzzjS64w
```

### Règle d'envoi par téléphone :
1. Envoyer le texte brut en un seul SMS sans espaces ni retours à la ligne au début ou à la fin.
2. Le réseau GSM le transmet au modem SIM868 de la passerelle.
3. La passerelle l'ingère, persiste sa copie brute dans SQLite, et l'expédie au backend configuré dans `.env`.
