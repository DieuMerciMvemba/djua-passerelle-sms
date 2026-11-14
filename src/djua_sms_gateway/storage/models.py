"""Modèles de persistance pour les SMS entrants et les files d'attente d'outbox (MQTT / HTTP)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InboundStatus(str, Enum):
    """Cycle de vie d'un SMS entrant dans la table inbound_sms."""
    RECEIVED = "RECEIVED"
    INVALID = "INVALID"
    VALIDATED = "VALIDATED"
    QUEUED = "QUEUED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class OutboxStatus(str, Enum):
    """Statut de livraison d'un message dans la table outbox."""
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class StoreDisposition(str, Enum):
    """Statut d'insertion brute du SMS (nouveau ou doublon exact)."""
    STORED = "STORED"
    DUPLICATE = "DUPLICATE"


class QueueDisposition(str, Enum):
    """Statut de mise en file d'attente outbox (nouveau, doublon logique ou conflit d'ID)."""
    QUEUED = "QUEUED"
    DUPLICATE_LOGICAL = "DUPLICATE_LOGICAL"
    MESSAGE_ID_CONFLICT = "MESSAGE_ID_CONFLICT"


@dataclass(frozen=True)
class RawSmsInput:
    """Données brutes issues de la réception modem d'un SMS."""
    sender: str
    raw_body: str
    modem_timestamp: str | None = None
    gateway_received_at: str | None = None


@dataclass(frozen=True)
class InboundSmsRecord:
    """Enregistrement persisté d'un SMS dans la table `inbound_sms`."""
    id: int
    sender: str
    modem_timestamp: str | None
    gateway_received_at: str
    raw_body: str
    raw_dedupe_key: str
    logical_dedupe_key: str | None
    protocol_version: str | None
    device_id: str | None
    sequence: int | None
    message_id: str | None
    d2_content_hash: str | None
    auth_status: str | None
    security_status: str | None
    conflict_with_sms_id: int | None
    status: InboundStatus
    validation_status: str | None
    validation_warning: str | None
    validation_error: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class OutboxRecord:
    """Message en attente d'expédition backend dans la table `outbox`."""
    id: int
    sms_id: int
    topic: str
    payload_json: str
    qos: int
    retain: bool
    status: OutboxStatus
    attempt_count: int
    next_attempt_at: str | None
    last_error: str | None
    created_at: str
    updated_at: str
    published_at: str | None
    message_id: str | None = None
    mqtt_done: bool = False
    http_done: bool = False
    http_attempt_count: int = 0
    http_next_attempt_at: str | None = None
    http_last_error: str | None = None
    http_published_at: str | None = None


@dataclass(frozen=True)
class StoreRawSmsResult:
    """Résultat du stockage initial du SMS brut."""
    disposition: StoreDisposition
    record: InboundSmsRecord

    @property
    def durably_stored(self) -> bool:
        """Garantit que le message est écrit de façon pérenne sur le disque SQLite."""
        return True


@dataclass(frozen=True)
class QueueResult:
    """Résultat de la tentative d'ajout d'une charge utile dans la table outbox."""
    disposition: QueueDisposition
    sms_id: int
    outbox: OutboxRecord | None
    duplicate_of_sms_id: int | None = None
