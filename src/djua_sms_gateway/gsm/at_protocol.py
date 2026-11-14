"""Gestionnaire de protocole de commandes AT synchrones avec file d'attente URC."""

from __future__ import annotations

from collections import deque
import time

from .models import AtResponse
from .serial_transport import SerialTransportProtocol

# Préfixes d'erreur reconnus par le modem
_ERROR_PREFIXES = ("+CME ERROR", "+CMS ERROR")
# Réponses non sollicitées (URC : Unsolicited Result Codes) classiques
_ALWAYS_URC_PREFIXES = ("+CMTI:", "+CDS:", "+CUSD:", "+CGEV:")
_ALWAYS_URC_LINES = {
    "RDY",
    "Call Ready",
    "SMS Ready",
    "NORMAL POWER DOWN",
}


class AtProtocol:
    """Gestionnaire d'exécution des commandes AT sur le transport série.
    
    Traite les réponses synchrones (OK / ERROR) tout en interceptant et mettant en mémoire
    tampon les notifications spontanées (URC comme +CMTI lors de l'arrivée d'un SMS).
    """

    def __init__(
        self,
        transport: SerialTransportProtocol,
        *,
        command_timeout_seconds: float = 5.0,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be > 0")
        self.transport = transport
        self.command_timeout_seconds = command_timeout_seconds
        self._monotonic = monotonic
        self._sleep = sleep
        self._urcs: deque[str] = deque()

    def _is_urc(self, line: str, command: str) -> bool:
        """Détermine si la ligne lue est une notification non sollicitée (URC)."""
        if line in _ALWAYS_URC_LINES or line.startswith(_ALWAYS_URC_PREFIXES):
            return True
        if line.startswith("+CREG:") and command != "AT+CREG?":
            return True
        if line.startswith("+CGREG:") and command != "AT+CGREG?":
            return True
        return False

    def execute(self, command: str, *, timeout_seconds: float | None = None) -> AtResponse:
        """Envoie une commande AT et attend la réponse terminale (OK ou ERROR) jusqu'au délai imparti."""
        timeout = self.command_timeout_seconds if timeout_seconds is None else timeout_seconds
        if timeout <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self.transport.write_line(command)
        deadline = self._monotonic() + timeout
        lines: list[str] = []

        while self._monotonic() < deadline:
            line = self.transport.read_line()
            if line is None:
                self._sleep(min(0.01, max(0.0, deadline - self._monotonic())))
                continue

            line = line.strip("\r\n")
            if not line:
                continue
            if line == command:
                continue
            if self._is_urc(line, command):
                self._urcs.append(line)
                continue
            if line == "OK":
                return AtResponse(command=command, lines=tuple(lines), ok=True)
            if line == "ERROR" or line.startswith(_ERROR_PREFIXES):
                return AtResponse(
                    command=command,
                    lines=tuple(lines),
                    ok=False,
                    error=line,
                )
            lines.append(line)

        return AtResponse(
            command=command,
            lines=tuple(lines),
            ok=False,
            error="TIMEOUT",
            timed_out=True,
        )

    def pop_urc(self) -> str | None:
        """Récupère et retire la prochaine notification URC en attente dans la file."""
        return self._urcs.popleft() if self._urcs else None

    def drain_urcs(self) -> tuple[str, ...]:
        """Vide et renvoie l'ensemble des notifications URC accumulées."""
        items = tuple(self._urcs)
        self._urcs.clear()
        return items

    def poll_urc(self, *, timeout_seconds: float = 0.0) -> str | None:
        """Attend ou scrute l'arrivée d'une notification URC sur la liaison série."""
        queued = self.pop_urc()
        if queued is not None:
            return queued

        deadline = self._monotonic() + max(0.0, timeout_seconds)
        first = True
        while first or self._monotonic() < deadline:
            first = False
            line = self.transport.read_line()
            if line is not None:
                stripped = line.strip("\r\n")
                if stripped:
                    return stripped
            if timeout_seconds <= 0:
                break
            self._sleep(min(0.01, max(0.0, deadline - self._monotonic())))
        return None
