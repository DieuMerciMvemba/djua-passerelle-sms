"""Configuration applicative de la passerelle DJUA_SMS basée sur les variables d'environnement."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from urllib.parse import urlsplit


def _env_bool(name: str, default: bool) -> bool:
    """Lit un booléen depuis l'environnement (1, true, yes, on / 0, false, no, off)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true/false")


def _env_int(name: str, default: int) -> int:
    """Lit un entier depuis l'environnement avec valeur par défaut."""
    raw = os.getenv(name)
    return default if raw is None or not raw.strip() else int(raw)


def _env_float(name: str, default: float) -> float:
    """Lit un nombre flottant depuis l'environnement avec valeur par défaut."""
    raw = os.getenv(name)
    return default if raw is None or not raw.strip() else float(raw)


@dataclass(frozen=True)
class GsmConfig:
    """Paramètres de communication série avec le modem GSM (ex: SIM868 ou SIM800)."""
    serial_port: str
    baud_rate: int = 9600
    serial_timeout_seconds: float = 0.5
    serial_write_timeout_seconds: float = 2.0
    init_retries: int = 3
    command_timeout_seconds: float = 5.0
    reconnect_seconds: float = 5.0
    sms_storage: str | None = None
    cnmi: str = "2,1,0,0,0"

    def validate(self) -> "GsmConfig":
        """Valide la cohérence des paramètres du port série et des commandes AT."""
        if not self.serial_port.strip():
            raise ValueError("SERIAL_PORT must not be empty")
        if self.baud_rate <= 0:
            raise ValueError("SERIAL_BAUD_RATE must be > 0")
        if self.serial_timeout_seconds <= 0:
            raise ValueError("SERIAL_TIMEOUT_SECONDS must be > 0")
        if self.serial_write_timeout_seconds <= 0:
            raise ValueError("SERIAL_WRITE_TIMEOUT_SECONDS must be > 0")
        if self.init_retries <= 0:
            raise ValueError("GSM_INIT_RETRIES must be > 0")
        if self.command_timeout_seconds <= 0:
            raise ValueError("GSM_COMMAND_TIMEOUT_SECONDS must be > 0")
        if self.reconnect_seconds <= 0:
            raise ValueError("GSM_RECONNECT_SECONDS must be > 0")
        if (
            self.sms_storage
            and re.fullmatch(r"[A-Za-z0-9]{1,8}", self.sms_storage)
            is None
        ):
            raise ValueError("GSM_SMS_STORAGE contains invalid characters")
        if re.fullmatch(r"\d+(?:,\d+){4}", self.cnmi) is None:
            raise ValueError(
                "GSM_CNMI must contain five comma-separated integers"
            )
        return self

    @classmethod
    def from_env(cls) -> "GsmConfig":
        """Charge la configuration GSM depuis les variables d'environnement."""
        config = cls(
            serial_port=os.getenv("SERIAL_PORT", ""),
            baud_rate=_env_int("SERIAL_BAUD_RATE", 9600),
            serial_timeout_seconds=_env_float(
                "SERIAL_TIMEOUT_SECONDS",
                0.5,
            ),
            serial_write_timeout_seconds=_env_float(
                "SERIAL_WRITE_TIMEOUT_SECONDS",
                2.0,
            ),
            init_retries=_env_int("GSM_INIT_RETRIES", 3),
            command_timeout_seconds=_env_float(
                "GSM_COMMAND_TIMEOUT_SECONDS",
                5.0,
            ),
            reconnect_seconds=_env_float(
                "GSM_RECONNECT_SECONDS",
                5.0,
            ),
            sms_storage=os.getenv("GSM_SMS_STORAGE") or None,
            cnmi=os.getenv("GSM_CNMI", "2,1,0,0,0"),
        )
        return config.validate()


@dataclass(frozen=True)
class D2SecurityConfig:
    """Politique de sécurité et clés secrètes HMAC pour les protocoles D2."""
    mode: str = "development"
    hmac_keys: dict[str, bytes] = field(default_factory=dict)
    sender_bindings: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )

    def validate(self) -> "D2SecurityConfig":
        """Vérifie la validité des clés hexadécimales de 32 octets et des numéros E.164."""
        if self.mode not in {"development", "production"}:
            raise ValueError(
                "D2_AUTH_MODE must be development or production"
            )

        device_re = re.compile(r"^[A-Z0-9-]{1,32}$")
        e164_re = re.compile(r"^\+[1-9][0-9]{7,14}$")

        for device_id, key in self.hmac_keys.items():
            if device_re.fullmatch(device_id) is None:
                raise ValueError(
                    f"invalid D2 key device_id: {device_id!r}"
                )
            if len(key) != 32:
                raise ValueError(
                    f"D2 HMAC key for {device_id} must be 32 bytes"
                )

        for device_id, senders in self.sender_bindings.items():
            if device_re.fullmatch(device_id) is None:
                raise ValueError(
                    f"invalid D2 sender device_id: {device_id!r}"
                )
            if not senders:
                raise ValueError(
                    f"D2 sender binding for {device_id} is empty"
                )
            for sender in senders:
                if e164_re.fullmatch(sender) is None:
                    raise ValueError(
                        f"D2 sender for {device_id} must be E.164"
                    )
        return self

    def key_for(self, device_id: str) -> bytes | None:
        """Retourne la clé secrète de 32 octets pour un kit donné, ou None."""
        return self.hmac_keys.get(device_id)

    def senders_for(self, device_id: str) -> tuple[str, ...]:
        """Retourne les numéros de téléphone autorisés pour un kit donné."""
        return self.sender_bindings.get(device_id, ())

    @classmethod
    def from_env(cls) -> "D2SecurityConfig":
        """Instancie la sécurité D2 depuis D2_AUTH_MODE, D2_HMAC_KEYS_JSON et D2_SENDER_BINDINGS_JSON."""
        mode = os.getenv("D2_AUTH_MODE", "development").strip().lower()

        try:
            raw_keys = json.loads(
                os.getenv("D2_HMAC_KEYS_JSON", "{}")
            )
            raw_bindings = json.loads(
                os.getenv("D2_SENDER_BINDINGS_JSON", "{}")
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                "D2 security JSON environment variable is invalid"
            ) from exc

        if not isinstance(raw_keys, dict):
            raise ValueError("D2_HMAC_KEYS_JSON must be a JSON object")
        if not isinstance(raw_bindings, dict):
            raise ValueError(
                "D2_SENDER_BINDINGS_JSON must be a JSON object"
            )

        keys: dict[str, bytes] = {}
        for device_id, value in raw_keys.items():
            if not isinstance(value, str):
                raise ValueError(
                    "D2_HMAC_KEYS_JSON values must be hex strings"
                )
            try:
                keys[str(device_id)] = bytes.fromhex(value)
            except ValueError as exc:
                raise ValueError(
                    f"D2 HMAC key for {device_id} is not valid hex"
                ) from exc

        bindings: dict[str, tuple[str, ...]] = {}
        for device_id, value in raw_bindings.items():
            if isinstance(value, str):
                senders = (value,)
            elif (
                isinstance(value, list)
                and all(isinstance(item, str) for item in value)
            ):
                senders = tuple(value)
            else:
                raise ValueError(
                    "D2_SENDER_BINDINGS_JSON values must be strings "
                    "or arrays of strings"
                )
            bindings[str(device_id)] = senders

        return cls(
            mode=mode,
            hmac_keys=keys,
            sender_bindings=bindings,
        ).validate()


@dataclass(frozen=True)
class MqttConfig:
    """Paramètres de connexion et de publication MQTT pour le backend."""
    host: str
    port: int = 1883
    client_id: str = "djua-sms-gateway-001"
    username: str | None = None
    password: str | None = None
    topic_prefix: str = "djua/test"
    qos: int = 1
    retain: bool = False
    keepalive_seconds: int = 60
    connect_timeout_seconds: float = 10.0
    publish_timeout_seconds: float = 10.0
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 300.0
    tls: bool = False

    def validate(self, *, require_host: bool = True) -> "MqttConfig":
        """Valide l'hôte, le port, le client_id et la structure du préfixe de topic."""
        host = self.host.strip()
        client_id = self.client_id.strip()
        prefix = self.topic_prefix.strip().strip("/")
        if require_host and not host:
            raise ValueError("MQTT_HOST must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("MQTT_PORT must be between 1 and 65535")
        if not client_id:
            raise ValueError("MQTT_CLIENT_ID must not be empty")
        if client_id.startswith("djua-DJUA-"):
            raise ValueError(
                "MQTT_CLIENT_ID must be a gateway ID, not an ESP32 device client ID"
            )
        if any(ch.isspace() for ch in client_id):
            raise ValueError(
                "MQTT_CLIENT_ID must not contain whitespace"
            )
        if not prefix or "+" in prefix or "#" in prefix:
            raise ValueError(
                "MQTT_TOPIC_PREFIX must be non-empty and contain no MQTT wildcards"
            )
        if self.qos not in (0, 1, 2):
            raise ValueError("MQTT_QOS must be 0, 1 or 2")
        if self.keepalive_seconds <= 0:
            raise ValueError("MQTT_KEEPALIVE_SECONDS must be > 0")
        if self.connect_timeout_seconds <= 0:
            raise ValueError(
                "MQTT_CONNECT_TIMEOUT_SECONDS must be > 0"
            )
        if self.publish_timeout_seconds <= 0:
            raise ValueError(
                "MQTT_PUBLISH_TIMEOUT_SECONDS must be > 0"
            )
        if self.retry_base_seconds <= 0:
            raise ValueError("MQTT_RETRY_BASE_SECONDS must be > 0")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError(
                "MQTT_RETRY_MAX_SECONDS must be >= MQTT_RETRY_BASE_SECONDS"
            )
        if self.password and not self.username:
            raise ValueError(
                "MQTT_USERNAME is required when MQTT_PASSWORD is set"
            )
        return self

    @property
    def normalized_topic_prefix(self) -> str:
        """Retourne le préfixe de topic nettoyé des slashes extrêmes."""
        return self.topic_prefix.strip().strip("/")

    @classmethod
    def from_env(cls, *, require_host: bool = True) -> "MqttConfig":
        """Charge la configuration MQTT depuis l'environnement."""
        username = os.getenv("MQTT_USERNAME") or None
        password = os.getenv("MQTT_PASSWORD") or None
        config = cls(
            host=os.getenv("MQTT_HOST", ""),
            port=_env_int("MQTT_PORT", 1883),
            client_id=os.getenv(
                "MQTT_CLIENT_ID",
                "djua-sms-gateway-001",
            ),
            username=username,
            password=password,
            topic_prefix=os.getenv(
                "MQTT_TOPIC_PREFIX",
                "djua/test",
            ),
            qos=_env_int("MQTT_QOS", 1),
            retain=_env_bool("MQTT_RETAIN", False),
            keepalive_seconds=_env_int(
                "MQTT_KEEPALIVE_SECONDS",
                60,
            ),
            connect_timeout_seconds=_env_float(
                "MQTT_CONNECT_TIMEOUT_SECONDS",
                10.0,
            ),
            publish_timeout_seconds=_env_float(
                "MQTT_PUBLISH_TIMEOUT_SECONDS",
                10.0,
            ),
            retry_base_seconds=_env_float(
                "MQTT_RETRY_BASE_SECONDS",
                2.0,
            ),
            retry_max_seconds=_env_float(
                "MQTT_RETRY_MAX_SECONDS",
                300.0,
            ),
            tls=_env_bool("MQTT_TLS", False),
        )
        return config.validate(require_host=require_host)


@dataclass(frozen=True)
class HttpConfig:
    """Paramètres du client d'ingestion REST HTTP (POST /api/v1/telemetry)."""
    backend_url: str
    events_url: str | None = None
    auth_token: str | None = field(default=None, repr=False)
    extra_headers: dict[str, str] = field(default_factory=dict, repr=False)
    timeout_seconds: float = 5.0
    verify_tls: bool = True
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 300.0
    batch_limit: int = 10

    @staticmethod
    def _validate_url(name: str, value: str) -> str:
        """Valide qu'une URL commence bien par http:// ou https:// sans informations d'authentification."""
        try:
            parsed = urlsplit(value.strip())
            parsed.port
        except ValueError as exc:
            raise ValueError(
                f"{name} must be a complete http:// or https:// URL"
            ) from exc
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError(
                f"{name} must be a complete http:// or https:// URL"
            )
        return value.strip()

    def validate(self) -> "HttpConfig":
        """Valide les URLs, les timeouts et les en-têtes HTTP personnalisés."""
        self._validate_url("HTTP_BACKEND_URL", self.backend_url)
        if self.events_url:
            self._validate_url("HTTP_EVENTS_URL", self.events_url)
        if self.timeout_seconds <= 0:
            raise ValueError("HTTP_TIMEOUT_SECONDS must be > 0")
        if self.retry_base_seconds <= 0:
            raise ValueError("HTTP_RETRY_BASE_SECONDS must be > 0")
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError(
                "HTTP_RETRY_MAX_SECONDS must be >= HTTP_RETRY_BASE_SECONDS"
            )
        if self.batch_limit <= 0:
            raise ValueError("HTTP_BATCH_LIMIT must be > 0")
        for name, value in self.extra_headers.items():
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(value, str)
                or any(char in name + value for char in "\r\n")
            ):
                raise ValueError(
                    "HTTP_EXTRA_HEADERS_JSON must map header names to string values"
                )
        return self

    @classmethod
    def from_env(cls) -> "HttpConfig":
        """Charge la configuration HTTP depuis HTTP_BACKEND_URL et les variables associées."""
        backend_url = os.getenv("HTTP_BACKEND_URL", "").strip()
        if not backend_url:
            raise ValueError(
                "HTTP_BACKEND_URL is required when BACKEND_TRANSPORT includes http"
            )
        raw_headers = os.getenv("HTTP_EXTRA_HEADERS_JSON", "{}").strip() or "{}"
        try:
            headers = json.loads(raw_headers)
        except json.JSONDecodeError as exc:
            raise ValueError("HTTP_EXTRA_HEADERS_JSON must be a JSON object") from exc
        if not isinstance(headers, dict) or not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in headers.items()
        ):
            raise ValueError(
                "HTTP_EXTRA_HEADERS_JSON must be a JSON object of string values"
            )
        iot_api_key = os.getenv("IOT_API_KEY", "").strip()
        if iot_api_key and "x-device-token" not in headers:
            headers["x-device-token"] = iot_api_key
        return cls(
            backend_url=backend_url,
            events_url=os.getenv("HTTP_EVENTS_URL", "").strip() or None,
            auth_token=os.getenv("HTTP_AUTH_TOKEN", "") or None,
            extra_headers=headers,
            timeout_seconds=_env_float("HTTP_TIMEOUT_SECONDS", 5.0),
            verify_tls=_env_bool("HTTP_VERIFY_TLS", True),
            retry_base_seconds=_env_float("HTTP_RETRY_BASE_SECONDS", 2.0),
            retry_max_seconds=_env_float("HTTP_RETRY_MAX_SECONDS", 300.0),
            batch_limit=_env_int("HTTP_BATCH_LIMIT", 10),
        ).validate()


@dataclass(frozen=True)
class AppConfig:
    """Configuration générale de l'application : persistance SQLite et choix du transport."""
    database_path: str = "data/djua_sms_gateway.db"
    backend_transport: str = "mqtt"
    http: HttpConfig | None = None

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Charge la configuration globale et instancie la configuration HTTP si activée."""
        transport = os.getenv("BACKEND_TRANSPORT", "mqtt").strip().lower()
        if transport not in {"mqtt", "http", "both"}:
            raise ValueError(
                "BACKEND_TRANSPORT must be mqtt, http or both "
                f"(got {transport!r})"
            )
        http = HttpConfig.from_env() if transport in {"http", "both"} else None
        return cls(
            database_path=os.getenv(
                "DATABASE_PATH",
                "data/djua_sms_gateway.db",
            ),
            backend_transport=transport,
            http=http,
        )
