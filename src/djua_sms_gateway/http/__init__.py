"""HTTP transport for the persistent backend outbox."""

from .client import HttpClientProtocol, HttpResult, UrllibHttpClient

__all__ = ["HttpClientProtocol", "HttpResult", "UrllibHttpClient"]
