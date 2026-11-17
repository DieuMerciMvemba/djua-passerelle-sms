"""Script de test autonome pour verifier l'envoi HTTP de la passerelle SMS
vers le serveur backend local a l'adresse http://10.20.20.251:5000 (sans modem ni boitier physique).
"""

import json
import sys
import time
import urllib.request
from pathlib import Path

# Ajouter src au PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from djua_sms_gateway.config import D2SecurityConfig, HttpConfig
from djua_sms_gateway.http.client import UrllibHttpClient
from djua_sms_gateway.services.http_outbox_worker import HttpOutboxWorker
from djua_sms_gateway.services.ingestion import IngestionConfig, RawSmsInput, SmsIngestionService
from djua_sms_gateway.storage import Database, SmsRepository


def main():
    print("=" * 75)
    print("🚀 TEST PASSERELLE -> BACKEND LOCAL (10.20.20.251:5000)")
    print("=" * 75)

    # Adresse locale (10.252.252.52:5000 par défaut ou lue dans config/gateway.env)
    base_url = "http://10.252.252.52:5000"
    config_file = ROOT / "config" / "gateway.env"
    if config_file.exists():
        for line in config_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("HTTP_BACKEND_URL="):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if "/api/iot/telemetry" in val:
                    base_url = val.replace("/api/iot/telemetry", "")
                break

    device_id = "DJUA-KIN-000001"
    telemetry_url = f"{base_url}/api/iot/{device_id}/telemetry"
    alerts_url = f"{base_url}/api/iot/{device_id}/alerts"

    print(f"🎯 Backend cible : {telemetry_url}")
    print(f"🎯 Alerts cible  : {alerts_url}")
    print("-" * 75)

    # 1. Verification prealable de l'accessibilite du serveur
    print("🔍 1. Test de connectivite reseau vers le backend...")
    try:
        req = urllib.request.Request(f"{base_url}/api/devices", headers={"User-Agent": "DjuaSmsTest/1.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            print(f"   -> Serveur accessible ! (HTTP {res.getcode()})")
    except Exception as exc:
        print(f"   ❌ Impossible de joindre {base_url} : {exc}")
        print(f"   Verifiez que le serveur Express/Node.js tourne bien sur {base_url}.")
        return

    # 2. Preparation de la base de donnees de test temporaire
    db_path = ROOT / "data" / "test_local_backend.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    db = Database(str(db_path))
    db.initialize()
    repo = SmsRepository(db, backend_transport="http")

    # 3. Initialisation du pipeline passerelle
    sec_cfg = D2SecurityConfig()
    ingestion = SmsIngestionService(repo, IngestionConfig(), d2_security=sec_cfg)

    http_cfg = HttpConfig(
        backend_url=telemetry_url,
        events_url=alerts_url,
        extra_headers={"x-device-token": "djua"},
        timeout_seconds=10.0,
    )
    http_client = UrllibHttpClient(timeout_seconds=10.0)
    http_worker = HttpOutboxWorker(repo, http_client, http_cfg)

    # 4. SMS simule D2T2 avec mesures reelles (Batterie, Solaire, DC, AC, GPS)
    simulated_sms = (
        f"D2T2,{device_id},"
        "AAAwOWq5NngHW80VA4R-WaCBdhPGDgAH0AB8RxgBM4AOAAARgj9B9AmNBZ4ABfgjA-AyAAGLAAHuAH_Q,-"
    )

    print("\n📥 2. Ingestion du SMS dans la passerelle...")
    print(f"   SMS brut : {simulated_sms}")
    raw_input = RawSmsInput(sender="+243810000001", raw_body=simulated_sms)
    ingestion_res = ingestion.ingest(raw_input)

    print(f"   -> Disposition : {ingestion_res.disposition.value}")
    print(f"   -> Outbox ID   : {ingestion_res.outbox_id}")

    if not ingestion_res.outbox_id:
        print("❌ Echec d'ingestion !")
        return

    # 5. Expedition HTTP par le worker
    print("\n🌐 3. Envoi HTTP POST vers le backend local...")
    worker_res = http_worker.run_once()
    print(f"   -> Messages traites : {worker_res.due}")
    print(f"   -> Succes (2xx)     : {worker_res.published}")
    print(f"   -> Echecs           : {worker_res.failed}")

    # 6. Verification de la donnee cote serveur
    if worker_res.published > 0:
        print("\n✅ 4. Verification de la mise a jour sur le serveur local...")
        try:
            device_req = urllib.request.Request(f"{base_url}/api/devices/{device_id}")
            with urllib.request.urlopen(device_req, timeout=5) as res:
                body = json.loads(res.read().decode("utf-8"))
                telemetry = body.get("data", {}).get("telemetry", {})
                updated_at = body.get("data", {}).get("updatedAt")
                print(f"   -> Statut kit    : {body.get('data', {}).get('status')}")
                print(f"   -> Mis a jour a  : {updated_at}")
                print(f"   -> Telemetrie    : {json.dumps(telemetry)}")
                print("\n🎉 TEST VALIDE AVEC SUCCES : La passerelle communique parfaitement avec 10.20.20.251:5000 !")
        except Exception as exc:
            print(f"   ⚠️ Le POST a reussi mais la verification GET a echoue : {exc}")
    else:
        print("\n❌ ECHEC DE LIVRAISON HTTP vers le serveur local.")

    print("=" * 75)


if __name__ == "__main__":
    main()
