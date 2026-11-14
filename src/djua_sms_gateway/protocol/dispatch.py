"""Aiguillage explicite du protocole (D1, D2T, D2T2, D2E) à partir de l'en-tête du message SMS."""

from __future__ import annotations

from .d2 import D2ProtocolError


def detect_protocol(raw_message: str) -> str:
    """Détecte le protocole utilisé en fonction du préfixe du SMS.
    
    Retourne 'D1', 'D2T', 'D2T2' ou 'D2E'. Lève une exception D2ProtocolError si le format n'est pas reconnu.
    """
    if raw_message.startswith("D1,"):
        return "D1"
    if raw_message.startswith("D2T,"):
        return "D2T"
    if raw_message.startswith("D2T2,"):
        return "D2T2"
    if raw_message.startswith("D2E,"):
        return "D2E"
    raise D2ProtocolError(
        "UNSUPPORTED_PROTOCOL",
        "Protocole attendu : D1, D2T, D2T2 ou D2E",
        "protocol",
    )
