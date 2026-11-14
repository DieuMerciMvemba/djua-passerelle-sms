"""Gestionnaire de base de données sqlite3 avec migrations de schéma automatiques."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

# Version courante du schéma de base de données
SCHEMA_VERSION = 3


class ClosingConnection(sqlite3.Connection):
    """Connexion sqlite3 qui se ferme automatiquement à la sortie du bloc de contexte."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS inbound_sms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender TEXT NOT NULL,
    modem_timestamp TEXT NULL,
    gateway_received_at TEXT NOT NULL,
    raw_body TEXT NOT NULL,
    raw_dedupe_key TEXT NOT NULL UNIQUE,
    logical_dedupe_key TEXT NULL UNIQUE,
    protocol_version TEXT NULL,
    device_id TEXT NULL,
    sequence INTEGER NULL,
    message_id TEXT NULL,
    d2_content_hash TEXT NULL,
    auth_status TEXT NULL,
    security_status TEXT NULL,
    conflict_with_sms_id INTEGER NULL,
    status TEXT NOT NULL CHECK (
        status IN ('RECEIVED','INVALID','VALIDATED','QUEUED','PUBLISHED','FAILED')
    ),
    validation_status TEXT NULL,
    validation_warning TEXT NULL,
    validation_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mqtt_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sms_id INTEGER NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    qos INTEGER NOT NULL CHECK (qos IN (0,1,2)),
    retain INTEGER NOT NULL CHECK (retain IN (0,1)),
    status TEXT NOT NULL CHECK (status IN ('PENDING','PUBLISHED','FAILED')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TEXT NULL,
    last_error TEXT NULL,
    mqtt_done INTEGER NOT NULL DEFAULT 0 CHECK (mqtt_done IN (0,1)),
    http_done INTEGER NOT NULL DEFAULT 0 CHECK (http_done IN (0,1)),
    http_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (http_attempt_count >= 0),
    http_next_attempt_at TEXT NULL,
    http_last_error TEXT NULL,
    http_published_at TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT NULL,
    FOREIGN KEY (sms_id) REFERENCES inbound_sms(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_inbound_sms_status
    ON inbound_sms(status);
CREATE INDEX IF NOT EXISTS idx_inbound_sms_message_id
    ON inbound_sms(message_id);
CREATE INDEX IF NOT EXISTS idx_outbox_status_next_attempt
    ON mqtt_outbox(status, next_attempt_at, id);
CREATE INDEX IF NOT EXISTS idx_http_outbox_due
    ON mqtt_outbox(http_done, http_next_attempt_at, id);
"""

_MIGRATION_V1_TO_V2 = (
    "ALTER TABLE inbound_sms ADD COLUMN message_id TEXT NULL",
    "ALTER TABLE inbound_sms ADD COLUMN d2_content_hash TEXT NULL",
    "ALTER TABLE inbound_sms ADD COLUMN auth_status TEXT NULL",
    "ALTER TABLE inbound_sms ADD COLUMN security_status TEXT NULL",
    "ALTER TABLE inbound_sms ADD COLUMN conflict_with_sms_id INTEGER NULL",
    "CREATE INDEX IF NOT EXISTS idx_inbound_sms_message_id ON inbound_sms(message_id)",
)

_MIGRATION_V2_TO_V3 = (
    "ALTER TABLE mqtt_outbox ADD COLUMN mqtt_done INTEGER NOT NULL DEFAULT 0 CHECK (mqtt_done IN (0,1))",
    "ALTER TABLE mqtt_outbox ADD COLUMN http_done INTEGER NOT NULL DEFAULT 0 CHECK (http_done IN (0,1))",
    "ALTER TABLE mqtt_outbox ADD COLUMN http_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (http_attempt_count >= 0)",
    "ALTER TABLE mqtt_outbox ADD COLUMN http_next_attempt_at TEXT NULL",
    "ALTER TABLE mqtt_outbox ADD COLUMN http_last_error TEXT NULL",
    "ALTER TABLE mqtt_outbox ADD COLUMN http_published_at TEXT NULL",
    "UPDATE mqtt_outbox SET mqtt_done = CASE WHEN status = 'PUBLISHED' THEN 1 ELSE 0 END",
    "UPDATE mqtt_outbox SET http_done = CASE WHEN status = 'PUBLISHED' THEN 1 ELSE 0 END",
)


class Database:
    """Gestionnaire de persistance SQLite : création du schéma, migrations et transactions."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        """Ouvre une connexion SQLite avec support des clés étrangères et d'un timeout de verrou."""
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        """Initialise le dossier, les tables SQLite et applique les migrations selon user_version."""
        parent = Path(self.path).expanduser().parent
        if self.path != ":memory:":
            parent.mkdir(parents=True, exist_ok=True)

        with self.connect() as connection:
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"database schema version {current_version} is newer than supported "
                    f"version {SCHEMA_VERSION}"
                )

            if current_version == 0:
                connection.executescript(_SCHEMA)
                connection.execute(
                    f"PRAGMA user_version = {SCHEMA_VERSION}"
                )
                return

            if current_version == 1:
                for statement in _MIGRATION_V1_TO_V2:
                    connection.execute(statement)
                current_version = 2

            if current_version == 2:
                for statement in _MIGRATION_V2_TO_V3:
                    connection.execute(statement)
                connection.execute(
                    f"PRAGMA user_version = {SCHEMA_VERSION}"
                )

            connection.executescript(_SCHEMA)

    @contextmanager
    def transaction(
        self,
        *,
        immediate: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        """Fournit un contexte transactionnel avec commit automatique ou rollback sur exception."""
        connection = self.connect()
        try:
            connection.execute(
                "BEGIN IMMEDIATE" if immediate else "BEGIN"
            )
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
