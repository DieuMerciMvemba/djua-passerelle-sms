import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from djua_sms_gateway.config import HttpConfig
from djua_sms_gateway.http.client import HttpResult
from djua_sms_gateway.mqtt.publisher import MqttPublisher
from djua_sms_gateway.services.http_outbox_worker import HttpOutboxWorker
from djua_sms_gateway.services.ingestion import SmsIngestionService
from djua_sms_gateway.services.outbox_worker import MqttOutboxWorker
from djua_sms_gateway.storage import Database, SmsRepository
from djua_sms_gateway.storage.models import InboundStatus, OutboxStatus, RawSmsInput
from tests.fixtures.d1_messages import D1_VALID_ALL, replace_field
from tests.unit.http.fakes import FakeHttpClient
from tests.unit.mqtt.fakes import FakeTransport


class HttpOutboxFlowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "gateway.db"
        self.now = datetime(2026, 10, 2, tzinfo=timezone.utc)

    def tearDown(self):
        self.tempdir.cleanup()

    def repository(self, mode):
        return SmsRepository(Database(self.path), backend_transport=mode)

    def ingest(self, repository, index=1):
        body = replace_field(D1_VALID_ALL, 1, f"DJUA-KIN-{index:06d}")
        return SmsIngestionService(repository).ingest(
            RawSmsInput(
                sender=f"+243810000{index:03d}",
                modem_timestamp=f"t{index}",
                raw_body=body,
            )
        )

    def http_worker(self, repository, client, *, events_url=None, limit=10):
        return HttpOutboxWorker(
            repository,
            client,
            HttpConfig(
                backend_url="https://backend.invalid/telemetry-route",
                events_url=events_url,
                batch_limit=limit,
                retry_base_seconds=2,
                retry_max_seconds=30,
            ),
            clock=lambda: self.now,
        )

    def test_mqtt_only_mode_keeps_existing_ack_flow(self):
        repository = self.repository("mqtt")
        queued = self.ingest(repository)
        mqtt = FakeTransport(mids=[31])
        worker = MqttOutboxWorker(
            repository,
            mqtt,
            MqttPublisher(mqtt, repository),
        )

        self.assertEqual(worker.run_once().started, 1)
        mqtt.ack(31)

        outbox = repository.get_outbox(queued.outbox_id)
        self.assertEqual(outbox.status, OutboxStatus.PUBLISHED)
        self.assertTrue(outbox.mqtt_done)
        self.assertTrue(outbox.http_done)

    def test_http_only_mode_publishes_without_mqtt(self):
        repository = self.repository("http")
        queued = self.ingest(repository)
        client = FakeHttpClient()

        result = self.http_worker(repository, client).run_once()

        outbox = repository.get_outbox(queued.outbox_id)
        self.assertEqual(result.published, 1)
        self.assertEqual(outbox.status, OutboxStatus.PUBLISHED)
        self.assertTrue(outbox.mqtt_done)
        self.assertTrue(outbox.http_done)
        self.assertEqual(repository.get_inbound(queued.sms_id).status, InboundStatus.PUBLISHED)

    def test_both_mode_http_failure_does_not_republish_acknowledged_mqtt(self):
        repository = self.repository("both")
        queued = self.ingest(repository)
        mqtt = FakeTransport(mids=[41])
        mqtt_worker = MqttOutboxWorker(
            repository,
            mqtt,
            MqttPublisher(mqtt, repository),
        )
        self.assertEqual(mqtt_worker.run_once().started, 1)
        mqtt.ack(41)
        self.assertEqual(repository.get_outbox(queued.outbox_id).status, OutboxStatus.PENDING)
        self.assertEqual(repository.list_pending_outbox(), [])

        http = FakeHttpClient([HttpResult(503), HttpResult(204)])
        http_worker = self.http_worker(repository, http)
        self.assertEqual(http_worker.run_once().failed, 1)
        self.assertEqual(repository.get_outbox(queued.outbox_id).status, OutboxStatus.PENDING)
        self.assertEqual(repository.get_inbound(queued.sms_id).status, InboundStatus.QUEUED)
        self.assertEqual(repository.list_pending_outbox(), [])
        self.assertEqual(len(mqtt.calls), 1)

        self.now += timedelta(seconds=3)
        self.assertEqual(http_worker.run_once().published, 1)
        self.assertEqual(repository.get_outbox(queued.outbox_id).status, OutboxStatus.PUBLISHED)
        self.assertEqual(repository.get_inbound(queued.sms_id).status, InboundStatus.PUBLISHED)
        self.assertEqual(len(mqtt.calls), 1)

    def test_urgent_event_precedes_20_telemetry_rows_and_uses_events_url(self):
        repository = self.repository("http")
        for index in range(1, 22):
            queued = self.ingest(repository, index)
            if index == 21:
                event_id = queued.outbox_id
                event_sms_id = queued.sms_id
        with repository.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE mqtt_outbox SET topic = ? WHERE id = ?",
                ("djua/test/DJUA-KIN-000021/geofence/events", event_id),
            )
            connection.execute(
                "UPDATE inbound_sms SET message_id = ? WHERE id = ?",
                ("D2:DJUA-KIN-000021:ABC", event_sms_id),
            )
        original = repository.get_outbox(event_id).payload_json
        client = FakeHttpClient()
        worker = self.http_worker(
            repository,
            client,
            events_url="https://backend.invalid/urgent-events",
            limit=10,
        )

        result = worker.run_once()

        self.assertEqual(result.due, 10)
        self.assertEqual(client.calls[0][0], "https://backend.invalid/urgent-events")
        self.assertEqual(client.calls[0][1], original)
        self.assertEqual(
            client.calls[0][2]["Idempotency-Key"],
            "D2:DJUA-KIN-000021:ABC",
        )
        self.assertTrue(client.calls[0][2]["X-DJUA-Topic"].endswith("/geofence/events"))
        self.assertEqual(len(client.calls), 10)

    def test_urgent_event_falls_back_to_backend_url(self):
        repository = self.repository("http")
        queued = self.ingest(repository)
        with repository.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE mqtt_outbox SET topic = ? WHERE id = ?",
                ("djua/test/DJUA-KIN-000001/geofence/events", queued.outbox_id),
            )
        client = FakeHttpClient()

        self.http_worker(repository, client).run_once()

        self.assertEqual(client.calls[0][0], "https://backend.invalid/telemetry-route")


if __name__ == "__main__":
    unittest.main()
