"""Script de test pour simuler l'injection d'un SMS dans la passerelle
et verifier son envoi HTTP vers le Backend Render sans boitier physique ni modem.
"""

import sys
import time
from pathlib import Path

# Ajouter src au PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from djua_sms_gateway.config import AppConfig, D2SecurityConfig
from djua_sms_gateway.http.client import UrllibHttpClient
from djua_sms_gateway.services.http_outbox_worker import HttpOutboxWorker
from djua_sms_gateway.services.ingestion import IngestionConfig, RawSmsInput, SmsIngestionService
from djua_sms_gateway.storage import Database, SmsRepository
from scripts.run_gateway import load_env_file


def main():
    print("=" * 70)
    print("🚀 TEST D'ENVOI PASSERELLE -> BACKEND (HTTP)")
    print("=" * 70)

    # 1. Charger la configuration
    env_file = ROOT / "config" / "gateway.env"
    if not env_file.exists():
        env_file = ROOT / ".env"
    load_env_file(env_file, override=True)

    app_cfg = AppConfig.from_env()
    sec_cfg = D2SecurityConfig.from_env()

    print(f"📡 Transport sélectionné : {app_cfg.backend_transport}")
    print(f"🎯 Backend URL            : {app_cfg.http.backend_url}")
    print(f"🎯 Events URL             : {app_cfg.http.events_url}")
    print("-" * 70)

    # 2. Initialiser une base SQLite de test
    db_test_path = ROOT / "data" / "simulated_gateway_test.db"
    db_test_path.parent.mkdir(parents=True, exist_ok=True)
    if db_test_path.exists():
        db_test_path.unlink()

    db = Database(str(db_test_path))
    db.initialize()
    repo = SmsRepository(db, backend_transport=app_cfg.backend_transport)

    # 3. Préparer le service d'ingestion et le client HTTP
    ingestion = SmsIngestionService(repo, IngestionConfig(), d2_security=sec_cfg)
    http_client = UrllibHttpClient(timeout_seconds=app_cfg.http.timeout_seconds)
    http_worker = HttpOutboxWorker(repo, http_client, app_cfg.http)

    # 4. SMS simulé D2T2 (télémétrie valide avec mesures réelles)
    # Payload d2t2 officiel avec sequence unique horodatée
    seq = int(time.time()) % 1000000
    simulated_sms = (
        "D2T2,DJUA-KIN-000001,"
        "AAAwOWq5NngHW80VA4R-WaCBdhPGDgAH0AB8RxgBM4AOAAARgj9B9AmNBZ4ABfgjA-AyAAGLAAHuAH_Q,-"
    )

    print("📥 1. Simulation de réception SMS par la passerelle...")
    print(f"   Texte brut : {simulated_sms}")
    raw_input = RawSmsInput(sender="+243810000001", raw_body=simulated_sms)
    ingestion_res = ingestion.ingest(raw_input)

    print(f"   -> Disposition : {ingestion_res.disposition.value}")
    print(f"   -> SMS ID      : {ingestion_res.sms_id}")
    print(f"   -> Outbox ID   : {ingestion_res.outbox_id}")

    if not ingestion_res.outbox_id:
        print("❌ Échec de mise en file outbox !")
        return

    # 5. Déclencher le worker HTTP pour l'envoi vers le backend
    print("\n🌐 2. Expédition HTTP du message vers le Backend...")
    worker_res = http_worker.run_once()
    print(f"   -> Messages traités : {worker_res.due}")
    print(f"   -> Succès (2xx)     : {worker_res.published}")
    print(f"   -> Échecs           : {worker_res.failed}")

    if worker_res.published > 0:
        print("\n✅ SUCCÈS TOTAL : La passerelle a normalisé le SMS et l'a transmis au Backend !")
    else:
        print("\n⚠️ L'envoi n'a pas pu être acquitté par le backend. Vérifier logs/gateway.log")

    print("=" * 70)


if __name__ == "__main__":
    main()
