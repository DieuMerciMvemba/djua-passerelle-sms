import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.protocol.parser import parse_d1
from djua_sms_gateway.protocol.validator import validate_telemetry
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import RawSmsInput
from tests.fixtures.d1_messages import D1_VALID_ALL


class HttpOutboxStorageTests(unittest.TestCase):
    def queue_one(self, repository, sender):
        stored = repository.store_raw_sms(
            RawSmsInput(sender=sender, raw_body=D1_VALID_ALL)
        )
        telemetry = parse_d1(D1_VALID_ALL)
        result = repository.queue_valid_sms(
            stored.record.id,
            telemetry,
            validate_telemetry(telemetry),
            topic="djua/test/device/telemetry",
            payload_json=json.dumps({"v": 1}),
        )
        return result.outbox

    def test_queue_flags_follow_selected_transport_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mode, expected in (
                ("mqtt", (False, True)),
                ("http", (True, False)),
                ("both", (False, False)),
            ):
                with self.subTest(mode=mode):
                    repo = SmsRepository(
                        Database(Path(tmp) / f"{mode}.db"),
                        backend_transport=mode,
                    )
                    outbox = self.queue_one(repo, f"+24381000000{len(mode)}")
                    self.assertEqual(
                        (outbox.mqtt_done, outbox.http_done),
                        expected,
                    )
                    self.assertEqual(outbox.http_attempt_count, 0)
                    self.assertIsNone(outbox.http_next_attempt_at)

    def test_v2_to_v3_migration_preserves_delivery_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.db"
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE inbound_sms (
                        id INTEGER PRIMARY KEY, sender TEXT NOT NULL,
                        modem_timestamp TEXT, gateway_received_at TEXT NOT NULL,
                        raw_body TEXT NOT NULL, raw_dedupe_key TEXT NOT NULL UNIQUE,
                        logical_dedupe_key TEXT, protocol_version TEXT,
                        device_id TEXT, sequence INTEGER, message_id TEXT,
                        d2_content_hash TEXT, auth_status TEXT, security_status TEXT,
                        conflict_with_sms_id INTEGER, status TEXT NOT NULL,
                        validation_status TEXT, validation_warning TEXT,
                        validation_error TEXT, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE mqtt_outbox (
                        id INTEGER PRIMARY KEY, sms_id INTEGER NOT NULL,
                        topic TEXT NOT NULL, payload_json TEXT NOT NULL,
                        qos INTEGER NOT NULL, retain INTEGER NOT NULL,
                        status TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
                        next_attempt_at TEXT, last_error TEXT, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL, published_at TEXT
                    );
                    INSERT INTO inbound_sms
                        (id, sender, gateway_received_at, raw_body, raw_dedupe_key,
                         status, created_at, updated_at)
                    VALUES (1, '+2431', 'now', 'pending', 'raw-1', 'QUEUED', 'now', 'now'),
                           (2, '+2432', 'now', 'published', 'raw-2', 'PUBLISHED', 'now', 'now');
                    INSERT INTO mqtt_outbox
                        (id, sms_id, topic, payload_json, qos, retain, status,
                         created_at, updated_at)
                    VALUES (1, 1, 'a/telemetry', '{}', 1, 0, 'PENDING', 'now', 'now'),
                           (2, 2, 'a/telemetry', '{}', 1, 0, 'PUBLISHED', 'now', 'now');
                    PRAGMA user_version = 2;
                    """
                )
            connection.close()

            Database(path).initialize()
            with Database(path).connect() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                rows = connection.execute(
                    "SELECT status, mqtt_done, http_done, http_attempt_count, "
                    "http_next_attempt_at, http_last_error, http_published_at "
                    "FROM mqtt_outbox ORDER BY id"
                ).fetchall()

            self.assertEqual(version, 3)
            self.assertEqual(tuple(rows[0][:4]), ("PENDING", 0, 0, 0))
            self.assertEqual(tuple(rows[1][:4]), ("PUBLISHED", 1, 1, 0))
            self.assertEqual(tuple(rows[1][4:]), (None, None, None))


if __name__ == "__main__":
    unittest.main()
