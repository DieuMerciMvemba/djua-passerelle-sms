"""Normalisation des télémétries D1 validées vers le contrat de charge utile MQTT DJUA."""

from __future__ import annotations

from .errors import NormalizationError
from .models import DjuaMqttPayload, SmsTelemetry, ValidationStatus
from .validator import validate_telemetry


def _timestamp_iso8601(rtc: str) -> str:
    """Convertit l'horodatage compact 'YYYYMMDDhhmmss' en chaîne ISO 8601 GMT+1."""
    return (
        f"{rtc[0:4]}-{rtc[4:6]}-{rtc[6:8]}"
        f"T{rtc[8:10]}:{rtc[10:12]}:{rtc[12:14]}+01:00"
    )


def normalize_to_mqtt(telemetry: SmsTelemetry) -> DjuaMqttPayload:
    """Transforme une trame D1 validée en objet DjuaMqttPayload prêt pour publication MQTT.
    
    Applique les valeurs par défaut et neutralisations selon les drapeaux de validité :
    - Coordonnées GPS : (0.0, 0.0) si le GPS est invalide.
    - Batterie / AC : 0.0 si le capteur est invalide.
    - Solaire : None si le capteur solaire est invalide.
    - Horodatage : format ISO 8601 en GMT+1 si RTC valide, sinon None.
    """
    validation = validate_telemetry(telemetry)
    if validation.status is ValidationStatus.INVALID_FORMAT:
        raise NormalizationError("; ".join(validation.errors))

    # Bloc GPS (repli sur 0.0, 0.0 si capteur invalide ou non verrouillé)
    if telemetry.gps_valid:
        latitude = float(telemetry.latitude)
        longitude = float(telemetry.longitude)
    else:
        latitude = 0.0
        longitude = 0.0

    # Bloc Batterie (tension, courant, puissance)
    if telemetry.battery_valid:
        battery_voltage = float(telemetry.battery_voltage)
        battery_current = float(telemetry.battery_current)
        battery_power = float(telemetry.battery_power)
    else:
        battery_voltage = 0.0
        battery_current = 0.0
        battery_power = 0.0

    # Bloc Solaire (production PV instantanée et énergie cumulée)
    if telemetry.solar_valid:
        solar_voltage = float(telemetry.solar_voltage)
        solar_current = float(telemetry.solar_current)
        solar_power = float(telemetry.solar_power)
        solar_energy_interval_wh = float(telemetry.solar_energy_interval_wh)
    else:
        solar_voltage = None
        solar_current = None
        solar_power = None
        solar_energy_interval_wh = None

    # Bloc Onduleur AC (charge consommée en courant alternatif)
    if telemetry.ac_valid:
        ac_voltage = float(telemetry.ac_voltage)
        ac_current = float(telemetry.ac_current)
        ac_active_power = float(telemetry.ac_active_power)
        ac_apparent_power = float(telemetry.ac_apparent_power)
        ac_energy_interval_wh = float(telemetry.ac_energy_interval_wh)
    else:
        ac_voltage = 0.0
        ac_current = 0.0
        ac_active_power = 0.0
        ac_apparent_power = 0.0
        ac_energy_interval_wh = 0.0

    # Bloc Horodatage RTC
    timestamp = None
    timezone = None
    if telemetry.rtc_valid:
        timestamp = _timestamp_iso8601(telemetry.rtc)
        timezone = "GMT+1"

    return DjuaMqttPayload(
        kit_id=telemetry.device_id,
        timestamp_ms=telemetry.uptime_ms,
        interval_seconds=telemetry.interval_seconds,
        latitude=latitude,
        longitude=longitude,
        battery_voltage=battery_voltage,
        battery_current=battery_current,
        battery_power=battery_power,
        solar_voltage=solar_voltage,
        solar_current=solar_current,
        solar_power=solar_power,
        solar_energy_interval_wh=solar_energy_interval_wh,
        ac_voltage=ac_voltage,
        ac_current=ac_current,
        ac_active_power=ac_active_power,
        ac_apparent_power=ac_apparent_power,
        ac_energy_interval_wh=ac_energy_interval_wh,
        timestamp=timestamp,
        timezone=timezone,
    )
