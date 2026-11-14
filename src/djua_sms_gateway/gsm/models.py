"""Modèles de données pour la couche de transport AT et le modem GSM (SIM800L / SIM868)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class AtResponse:
    """Réponse d'une commande AT (lignes de texte reçues, statut OK/ERROR, timeout)."""
    command: str
    lines: tuple[str, ...] = ()
    ok: bool = False
    error: str | None = None
    timed_out: bool = False


@dataclass(frozen=True)
class CmtiNotification:
    """Notification non sollicitée +CMTI indiquant la réception d'un nouveau SMS en mémoire."""
    storage: str
    index: int


@dataclass(frozen=True)
class ModemSms:
    """Message SMS extrait de la mémoire du modem (expéditeur, timestamp, corps brut)."""
    storage: str
    index: int
    status: str
    sender: str
    modem_timestamp: str | None
    raw_body: str


class SimStatus(str, Enum):
    """État de détection et de déverrouillage de la carte SIM (CPIN)."""
    READY = "READY"
    PIN_REQUIRED = "SIM PIN"
    PUK_REQUIRED = "SIM PUK"
    UNKNOWN = "UNKNOWN"


class NetworkRegistration(str, Enum):
    """Statut d'enregistrement sur le réseau cellulaire GSM (CREG)."""
    NOT_REGISTERED = "NOT_REGISTERED"
    HOME = "HOME"
    SEARCHING = "SEARCHING"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"
    ROAMING = "ROAMING"

    @property
    def registered(self) -> bool:
        """Vrai si enregistré sur le réseau local ou en itinérance."""
        return self in {NetworkRegistration.HOME, NetworkRegistration.ROAMING}


@dataclass(frozen=True)
class SignalQuality:
    """Indicateurs de qualité du signal radio cellulaire (CSQ : RSSI et BER)."""
    rssi: int
    ber: int

    @property
    def known(self) -> bool:
        """Vrai si le niveau de signal est mesurable (RSSI != 99)."""
        return self.rssi != 99


@dataclass(frozen=True)
class SmsStorage:
    """État de remplissage de la mémoire SMS du modem (ex: SM ou ME)."""
    name: str
    used: int
    total: int


@dataclass(frozen=True)
class ModemInitializationReport:
    """Rapport d'autodiagnostic complet lors de l'initialisation du modem GSM."""
    modem_present: bool
    sim_status: SimStatus
    network_registration: NetworkRegistration
    signal: SignalQuality | None
    sms_text_mode: bool
    storage: SmsStorage | None
    cnmi_configured: bool

    @property
    def sim_ready(self) -> bool:
        """Indique si la carte SIM est insérée et prête."""
        return self.sim_status is SimStatus.READY

    @property
    def network_registered(self) -> bool:
        """Indique si le modem est connecté au réseau cellulaire."""
        return self.network_registration.registered

    @property
    def sms_ready(self) -> bool:
        """Indique si le modem est configuré et prêt à recevoir des SMS."""
        return self.sim_ready and self.sms_text_mode and self.cnmi_configured
