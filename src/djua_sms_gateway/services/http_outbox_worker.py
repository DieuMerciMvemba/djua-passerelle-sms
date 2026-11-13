"""Synchronous worker that retries due persistent HTTP outbox rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging

from djua_sms_gateway.config import HttpConfig
from djua_sms_gateway.http.client import HttpClientProtocol
from djua_sms_gateway.mqtt.publisher import compute_backoff_seconds
from djua_sms_gateway.storage.models import OutboxRecord
from djua_sms_gateway.storage.repository import SmsRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HttpWorkerRunResult:
    due: int = 0
    published: int = 0
    failed: int = 0


class HttpOutboxWorker:
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

            if 200 <= response.status_code < 300:
                self.repository.mark_http_published(outbox.id)
                logger.info(
                    "HTTP_OUTBOX_PUBLISHED outbox_id=%s status=%s",
                    outbox.id,
                    response.status_code,
                )
                published += 1
                continue

            permanent_client_error = (
                400 <= response.status_code < 500
                and response.status_code not in {408, 429}
            )
            error = f"HTTP status {response.status_code}"
            self._record_failure(
                outbox,
                error,
                permanent_client_error=permanent_client_error,
            )
            if permanent_client_error:
                logger.error(
                    "HTTP_OUTBOX_CLIENT_ERROR outbox_id=%s status=%s retry_after_seconds=%s",
                    outbox.id,
                    response.status_code,
                    self.config.retry_max_seconds,
                )
            else:
                logger.warning(
                    "HTTP_OUTBOX_RETRY outbox_id=%s status=%s",
                    outbox.id,
                    response.status_code,
                )
            failed += 1

        return HttpWorkerRunResult(
            due=len(pending),
            published=published,
            failed=failed,
        )

    def _url_for(self, outbox: OutboxRecord) -> str:
        if outbox.topic.endswith("/geofence/events"):
            return self.config.events_url or self.config.backend_url
        return self.config.backend_url

    def _headers_for(self, outbox: OutboxRecord) -> dict[str, str]:
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
