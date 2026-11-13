from datetime import datetime, timezone
import logging
import tempfile
import unittest
from pathlib import Path

from djua_sms_gateway.config import HttpConfig
from djua_sms_gateway.http.client import HttpResult
from djua_sms_gateway.services.http_outbox_worker import HttpOutboxWorker
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import InboundStatus, OutboxStatus
from tests.unit.http.fakes import FakeHttpClient
from tests.unit.mqtt.fakes import seed_outbox


class HttpOutboxWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = SmsRepository(
            Database(Path(self.tempdir.name) / "gateway.db"),
            backend_transport="http",
        )
        self.now = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def tearDown(self):
        self.tempdir.cleanup()

    def config(self, **changes):
        values = {
            "backend_url": "https://backend.invalid/full/route",
            "events_url": "https://backend.invalid/events",
            "retry_base_seconds": 2,
            "retry_max_seconds": 30,
            "batch_limit": 10,
        }
        values.update(changes)
        return HttpConfig(**values)

    def worker(self, client, config=None):
        return HttpOutboxWorker(
            self.repository,
            client,
            config or self.config(),
            clock=lambda: self.now,
        )

    def test_success_sends_exact_payload_and_auth_headers_then_publishes(self):
        row = seed_outbox(self.repository, key="1", payload='{"x":0}')
        client = FakeHttpClient()
        worker = self.worker(
            client,
            self.config(
                auth_token="secret-token",
                extra_headers={"X-Api-Key": "api-key"},
            ),
        )

        result = worker.run_once()

        self.assertEqual((result.due, result.published, result.failed), (1, 1, 0))
        url, body, headers = client.calls[0]
        self.assertEqual(url, "https://backend.invalid/full/route")
        self.assertEqual(body, row.payload_json)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["X-DJUA-Topic"], row.topic)
        self.assertEqual(headers["Idempotency-Key"], f"outbox-{row.id}")
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertEqual(headers["X-Api-Key"], "api-key")
        updated = self.repository.get_outbox(row.id)
        self.assertEqual(updated.status, OutboxStatus.PUBLISHED)
        self.assertTrue(updated.http_done)
        self.assertTrue(updated.mqtt_done)
        self.assertEqual(
            self.repository.get_inbound(row.sms_id).status,
            InboundStatus.PUBLISHED,
        )

    def test_http_d2_message_id_is_used_as_idempotency_key(self):
        row = seed_outbox(self.repository, key="2")
        with self.repository.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE inbound_sms SET message_id = ? WHERE id = ?",
                ("D2:DJUA-KIN-000002:ABC", row.sms_id),
            )
        client = FakeHttpClient()

        self.worker(client).run_once()

        self.assertEqual(
            client.calls[0][2]["Idempotency-Key"],
            "D2:DJUA-KIN-000002:ABC",
        )

    def test_5xx_and_timeout_retry_with_backoff_without_terminal_failure(self):
        row = seed_outbox(self.repository, key="3")
        client = FakeHttpClient([HttpResult(503), TimeoutError("offline")])
        worker = self.worker(client)

        first = worker.run_once()
        failed = self.repository.get_outbox(row.id)
        self.assertEqual(first.failed, 1)
        self.assertEqual(failed.http_attempt_count, 1)
        self.assertEqual(failed.http_last_error, "HTTP status 503")
        self.assertEqual(
            failed.http_next_attempt_at,
            "2026-10-01T00:00:02+00:00",
        )
        self.assertEqual(failed.status, OutboxStatus.PENDING)

        self.now = datetime(2026, 10, 1, 0, 0, 3, tzinfo=timezone.utc)
        second = worker.run_once()
        failed = self.repository.get_outbox(row.id)
        self.assertEqual(second.failed, 1)
        self.assertEqual(failed.http_attempt_count, 2)
        self.assertIn("TimeoutError", failed.http_last_error)
        self.assertEqual(failed.status, OutboxStatus.PENDING)
        self.assertEqual(
            self.repository.get_inbound(row.sms_id).status,
            InboundStatus.QUEUED,
        )

    def test_other_4xx_logs_error_and_retries_at_maximum_backoff(self):
        row = seed_outbox(self.repository, key="4")
        client = FakeHttpClient([HttpResult(400)])
        worker = self.worker(client, self.config(retry_max_seconds=45))
        with self.assertLogs("djua_sms_gateway.services.http_outbox_worker", level="ERROR") as logs:
            result = worker.run_once()

        updated = self.repository.get_outbox(row.id)
        self.assertEqual(result.failed, 1)
        self.assertEqual(updated.status, OutboxStatus.PENDING)
        self.assertEqual(updated.http_attempt_count, 1)
        self.assertEqual(updated.http_next_attempt_at, "2026-10-01T00:00:45+00:00")
        self.assertEqual(updated.http_last_error, "HTTP status 400")
        self.assertIn("status=400", "\n".join(logs.output))
        self.assertNotEqual(
            self.repository.get_inbound(row.sms_id).status,
            InboundStatus.FAILED,
        )

    def test_token_is_never_logged_and_auth_header_is_optional(self):
        token = "do-not-log-this-token"
        row = seed_outbox(self.repository, key="5")
        client = FakeHttpClient([RuntimeError(f"rejected {token}")])
        worker = self.worker(client, self.config(auth_token=token))
        with self.assertLogs("djua_sms_gateway.services.http_outbox_worker") as logs:
            worker.run_once()
        self.assertNotIn(token, "\n".join(logs.output))
        self.assertNotIn(token, self.repository.get_outbox(row.id).http_last_error)

        second = seed_outbox(self.repository, key="6")
        no_auth = FakeHttpClient()
        self.worker(no_auth, self.config()).run_once()
        self.assertNotIn("Authorization", no_auth.calls[0][2])
        self.assertEqual(no_auth.calls[0][2]["Idempotency-Key"], f"outbox-{second.id}")

    def test_run_once_respects_configured_batch_limit(self):
        seed_outbox(self.repository, key="7")
        seed_outbox(self.repository, key="8")
        client = FakeHttpClient()

        result = self.worker(client, self.config(batch_limit=1)).run_once(limit=10)

        self.assertEqual(result.due, 1)
        self.assertEqual(len(client.calls), 1)


if __name__ == "__main__":
    unittest.main()
