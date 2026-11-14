"""Configuration minimale des logs ; les clés secrètes et SMS bruts ne sont jamais journalisés."""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Initialise le formatage standardisé des logs (date, niveau, logger, message)."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
