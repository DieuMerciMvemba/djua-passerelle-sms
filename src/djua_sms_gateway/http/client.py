"""Client HTTP synchrone léger pour requêtes JSON POST, basé uniquement sur la bibliothèque standard urllib."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
import ssl
from urllib.parse import urlsplit


@dataclass(frozen=True)
class HttpResult:
    """Résultat immuable d'une requête HTTP (code de statut et corps de réponse)."""
    status_code: int
    body: str = ""

    @property
    def status(self) -> int:
        return self.status_code


class HttpClientProtocol(Protocol):
    """Contrat d'interface pour le client HTTP."""
    def post_json(self, url: str, body: str, headers: dict[str, str]) -> HttpResult:
        """Envoie une requête POST avec le corps JSON et retourne le statut HTTP."""


class _NoRedirectHandler(HTTPRedirectHandler):
    """Gestionnaire qui refuse les redirections automatiques pour préserver la méthode POST et les en-têtes."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibHttpClient:
    """Implémentation du client HTTP reposant sur urllib standard, sans dépendance externe."""
    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        verify_tls: bool = True,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls

    def post_json(self, url: str, body: str, headers: dict[str, str]) -> HttpResult:
        """Exécute un appel HTTP POST synchrone avec encodage UTF-8 et gestion des erreurs de transport."""
        request = Request(
            url,
            data=body.encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        handlers = [_NoRedirectHandler()]
        if not self.verify_tls and urlsplit(url).scheme.lower() == "https":
            handlers.append(
                HTTPSHandler(context=ssl._create_unverified_context())
            )
        opener = build_opener(*handlers)

        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                return HttpResult(
                    status_code=int(response.getcode()),
                    body=response.read().decode("utf-8", errors="replace"),
                )
        except HTTPError as response:
            try:
                return HttpResult(
                    status_code=int(response.code),
                    body=response.read().decode("utf-8", errors="replace"),
                )
            finally:
                response.close()
