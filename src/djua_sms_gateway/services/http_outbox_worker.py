"""Travailleur synchrone réexpédiant les messages de la file outbox persistante vers l'API REST HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging

from djua_sms_gateway.config import HttpConfig
from djua_sms_gateway.http.client import HttpClientProtocol
from djua_sms_gateway.mqtt.publisher import compute_backoff_seconds
from djua_sms_gateway.storage.models import OutboxRecord
from djua_sms_gateway.storage.repository import SmsRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpWorkerRunResult:
    """Rapport d'exécution d'un passage du travailleur HTTP outbox."""
    due: int = 0
    published: int = 0
    failed: int = 0


class HttpOutboxWorker:
    """Travailleur dépilant les enregistrements outbox en attente de publication HTTP vers le backend."""

    def __init__(
        self,
        repository: SmsRepository,
        client: HttpClientProtocol,
        config: HttpConfig,
        *,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.repository = repository
        self.client = client
        self.config = config
        self._clock = clock

    def run_once(self, limit: int | None = None) -> HttpWorkerRunResult:
        """Exécute un lot de requêtes HTTP POST avec gestion des erreurs 4xx/5xx et backoff."""
        batch_limit = self.config.batch_limit
        if limit is not None:
            batch_limit = min(limit, batch_limit)
        now = self._clock()
        pending = self.repository.list_pending_http_outbox(
            limit=batch_limit,
            due_before=now.isoformat(),
        )
        if not pending:
            return HttpWorkerRunResult()

        published = failed = 0
        for outbox in pending:
            try:
                response = self.client.post_json(
                    self._url_for(outbox),
                    outbox.payload_json,
                    self._headers_for(outbox),
                )
            except Exception as exc:
                self._record_failure(
                    outbox,
                    f"HTTP request failed ({type(exc).__name__})",
                    permanent_client_error=False,
                )
                logger.warning(
                    "HTTP_OUTBOX_REQUEST_FAILED outbox_id=%s error_type=%s",
                    outbox.id,
                    type(exc).__name__,
                )
                failed += 1
                continue

            # Statut HTTP 2xx : publication réussie
            if 200 <= response.status_code < 300:
                self.repository.mark_http_published(outbox.id)
                ack = response.body.strip() if response.body else "(vide)"
                logger.info(
                    "HTTP_OUTBOX_PUBLISHED outbox_id=%s status=%s ack=%s",
                    outbox.id,
                    response.status_code,
                    ack[:200],
                )
                published += 1
                continue

            # Erreur client 4xx (hors 408/429) : temporisation maximale
            permanent_client_error = (
                400 <= response.status_code < 500
                and response.status_code not in {408, 429}
            )
            error = f"HTTP status {response.status_code}"
            ack = response.body.strip() if response.body else "(vide)"
            self._record_failure(
                outbox,
                error,
                permanent_client_error=permanent_client_error,
            )
            if permanent_client_error:
                logger.error(
                    "HTTP_OUTBOX_CLIENT_ERROR outbox_id=%s status=%s ack=%s retry_after_seconds=%s",
                    outbox.id,
                    response.status_code,
                    ack[:200],
                    self.config.retry_max_seconds,
                )
            else:
                logger.warning(
                    "HTTP_OUTBOX_RETRY outbox_id=%s status=%s ack=%s",
                    outbox.id,
                    response.status_code,
                    ack[:200],
                )
            failed += 1

        return HttpWorkerRunResult(
            due=len(pending),
            published=published,
            failed=failed,
        )

    @staticmethod
    def _extract_device_id(outbox: OutboxRecord) -> str:
        try:
            data = json.loads(outbox.payload_json)
            if isinstance(data, dict):
                dev = data.get("kit_id") or data.get("device_id")
                if dev:
                    return str(dev).strip()
        except Exception:
            pass

        parts = [p for p in outbox.topic.split("/") if p]
        if len(parts) >= 2 and parts[-1] in {"telemetry", "events"}:
            return parts[-2]

        if outbox.message_id and ":" in outbox.message_id:
            msg_parts = outbox.message_id.split(":")
            if len(msg_parts) >= 2:
                return msg_parts[1]

        return ""

    def _url_for(self, outbox: OutboxRecord) -> str:
        """Route l'événement vers l'URL dédiée aux alertes ou la télémétrie, avec substitution dynamique du device_id."""
        base_url = (
            self.config.events_url or self.config.backend_url
            if outbox.topic.endswith("/geofence/events")
            else self.config.backend_url
        )
        device_id = self._extract_device_id(outbox)
        if not device_id:
            return base_url

        for placeholder in ("{device_id}", "{deviceId}", "{kit_id}", ":deviceId"):
            if placeholder in base_url:
                return base_url.replace(placeholder, device_id)

        if base_url.endswith("/api/iot/telemetry"):
            prefix = base_url[:-len("/api/iot/telemetry")]
            return f"{prefix}/api/iot/{device_id}/telemetry"

        if base_url.endswith("/api/iot/alerts"):
            prefix = base_url[:-len("/api/iot/alerts")]
            return f"{prefix}/api/iot/{device_id}/alerts"

        return base_url

    def _headers_for(self, outbox: OutboxRecord) -> dict[str, str]:
        """Génère les en-têtes HTTP (Content-Type, X-DJUA-Topic, Idempotency-Key et Bearer token)."""
        headers = dict(self.config.extra_headers)
        headers.update({
            "Content-Type": "application/json",
            "X-DJUA-Topic": outbox.topic,
            "Idempotency-Key": outbox.message_id or f"outbox-{outbox.id}",
        })
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"
        return headers

    def _record_failure(
        self,
        outbox: OutboxRecord,
        error: str,
        *,
        permanent_client_error: bool,
    ) -> None:
        """Enregistre l'échec et planifie la prochaine tentative d'envoi."""
        delay = (
            self.config.retry_max_seconds
            if permanent_client_error
            else compute_backoff_seconds(
                outbox.http_attempt_count,
                base_seconds=self.config.retry_base_seconds,
                max_seconds=self.config.retry_max_seconds,
            )
        )
        next_attempt = self._clock() + timedelta(seconds=delay)
        self.repository.record_http_failure(
            outbox.id,
            error=error,
            next_attempt_at=next_attempt.isoformat(),
        )
