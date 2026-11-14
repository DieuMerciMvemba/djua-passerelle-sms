"""Analyseur syntaxique strict pour le format SMS positionnel DJUA D1."""

from __future__ import annotations

import re

from .errors import D1ParseError
from .models import SmsTelemetry

# Nombre exact de champs attendus dans une trame CSV D1
FIELD_COUNT = 23
# Expressions régulières de validation de format
BASE36_RE = re.compile(r"^[0-9A-Z]+$")
DJUA_PROTOCOL_RE = re.compile(r"^D[0-9]+$")
FLAGS_RE = re.compile(r"^[0-9A-F]{2}$")


def decode_base36(value: str, field: str) -> int:
    """Décode un entier compacté en base 36 majuscule (ex: uptime, séquence)."""
    if not value or BASE36_RE.fullmatch(value) is None:
        raise D1ParseError("INVALID_BASE36", "expected uppercase base36", field)
    return int(value, 36)


def _parse_required_int(value: str, field: str) -> int:
    """Valide et convertit un entier décimal obligatoire."""
    if re.fullmatch(r"[+-]?\d+", value) is None:
        raise D1ParseError("INVALID_INTEGER", "expected decimal integer", field)
    return int(value, 10)


def _parse_optional_int(value: str, field: str) -> int | None:
    """Valide et convertit un entier décimal optionnel ('-' si absent)."""
    if value == "-":
        return None
    return _parse_required_int(value, field)


def _parse_optional_float(value: str, field: str) -> float | None:
    """Valide et convertit un nombre flottant optionnel ('-' si absent)."""
    if value == "-":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise D1ParseError(
            "INVALID_FLOAT",
            "expected decimal number or '-'",
            field,
        ) from exc


def parse_d1(raw_message: str) -> SmsTelemetry:
    """Analyse une chaîne SMS brute au format positionnel D1 et instancie SmsTelemetry.
    
    Effectue les vérifications initiales (non-vide, ASCII pur, absence d'espaces blancs),
    découpe les 23 champs séparés par des virgules et applique les masques binaires de validité.
    """
    if not raw_message:
        raise D1ParseError("EMPTY_MESSAGE", "message is empty")
    if not raw_message.isascii():
        raise D1ParseError("NON_ASCII", "D1 must use ASCII characters only")
    if any(char.isspace() for char in raw_message):
        raise D1ParseError("UNEXPECTED_WHITESPACE", "whitespace is not allowed in D1")

    # Découpage strict des champs CSV
    fields = raw_message.split(",")
    if len(fields) != FIELD_COUNT:
        raise D1ParseError(
            "FIELD_COUNT",
            f"expected {FIELD_COUNT} fields, got {len(fields)}",
        )

    (
        protocol,
        device_id,
        sequence_raw,
        rtc_raw,
        timezone_raw,
        uptime_raw,
        interval_raw,
        latitude_raw,
        longitude_raw,
        battery_voltage_raw,
        battery_current_raw,
        battery_power_raw,
        solar_voltage_raw,
        solar_current_raw,
        solar_power_raw,
        solar_energy_raw,
        ac_voltage_raw,
        ac_current_raw,
        ac_active_power_raw,
        ac_apparent_power_raw,
        ac_energy_raw,
        flags_raw,
        auth,
    ) = fields

    # Validation du marqueur de protocole (doit commencer par 'D')
    if DJUA_PROTOCOL_RE.fullmatch(protocol) is None:
        raise D1ParseError(
            "NOT_DJUA",
            "protocol marker must start with D and a version",
            "protocol",
        )
    if not device_id:
        raise D1ParseError("EMPTY_DEVICE_ID", "device_id is required", "device_id")
    if not auth:
        raise D1ParseError("EMPTY_AUTH", "auth field must be '-' or a token", "auth")
    if FLAGS_RE.fullmatch(flags_raw) is None:
        raise D1ParseError(
            "INVALID_FLAGS",
            "expected two uppercase hexadecimal digits",
            "flags",
        )

    # Conversion de l'octet de drapeaux hexadécimal (ex: '1F' -> 0x1F)
    flags = int(flags_raw, 16)
    rtc = None if rtc_raw == "-" else rtc_raw

    # Extraction des drapeaux binaires de validité des capteurs
    return SmsTelemetry(
        protocol_version=protocol,
        device_id=device_id,
        sequence=decode_base36(sequence_raw, "sequence"),
        rtc=rtc,
        timezone_minutes=_parse_optional_int(timezone_raw, "tz_min"),
        uptime_ms=decode_base36(uptime_raw, "uptime36"),
        interval_seconds=_parse_required_int(interval_raw, "interval"),
        latitude=_parse_optional_float(latitude_raw, "lat"),
        longitude=_parse_optional_float(longitude_raw, "lon"),
        battery_voltage=_parse_optional_float(battery_voltage_raw, "batt_v"),
        battery_current=_parse_optional_float(battery_current_raw, "batt_a"),
        battery_power=_parse_optional_float(battery_power_raw, "batt_w"),
        solar_voltage=_parse_optional_float(solar_voltage_raw, "solar_v"),
        solar_current=_parse_optional_float(solar_current_raw, "solar_a"),
        solar_power=_parse_optional_float(solar_power_raw, "solar_w"),
        solar_energy_interval_wh=_parse_optional_float(solar_energy_raw, "solar_wh"),
        ac_voltage=_parse_optional_float(ac_voltage_raw, "ac_v"),
        ac_current=_parse_optional_float(ac_current_raw, "ac_a"),
        ac_active_power=_parse_optional_float(ac_active_power_raw, "ac_w"),
        ac_apparent_power=_parse_optional_float(ac_apparent_power_raw, "ac_va"),
        ac_energy_interval_wh=_parse_optional_float(ac_energy_raw, "ac_wh"),
        flags=flags,
        auth=auth,
        rtc_valid=bool(flags & 0x01),
        gps_valid=bool(flags & 0x02),
        battery_valid=bool(flags & 0x04),
        solar_valid=bool(flags & 0x08),
        ac_valid=bool(flags & 0x10),
        raw_message=raw_message,
    )
