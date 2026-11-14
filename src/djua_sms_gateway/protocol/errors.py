"""Exceptions spécifiques au protocole SMS et au décodage télémétrique."""


class ProtocolError(ValueError):
    """Classe de base pour toutes les erreurs protocolaires déterministes."""


class D1ParseError(ProtocolError):
    """Levée lorsqu'un SMS brut ne peut pas être analysé ou décodé (syntaxe ou champs invalides)."""

    def __init__(self, code: str, message: str, field: str | None = None) -> None:
        self.code = code
        self.field = field
        prefix = f"{field}: " if field else ""
        super().__init__(f"{code}: {prefix}{message}")


class NormalizationError(ProtocolError):
    """Levée lorsqu'une mesure ou télémétrie invalide ne peut pas être normalisée en toute sécurité."""
