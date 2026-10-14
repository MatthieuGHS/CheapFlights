import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

Headers = tuple[tuple[str, str], ...]


def _header(headers: Headers, name: str) -> str | None:
    name = name.lower()
    return next((v for k, v in headers if k.lower() == name), None)


@dataclass(frozen=True)
class HttpRequest:
    """Requête neutre vis-à-vis du rung : chaque transport la traduit pour sa bibliothèque."""

    method: str
    url: str
    headers: Headers
    body: bytes | None

    @classmethod
    def build(
        cls,
        method: str,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
        json_body: Any = None,
    ) -> "HttpRequest":
        hdrs = {k.lower(): v for k, v in (headers or {}).items()}
        body = None
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":"), sort_keys=True).encode()
            hdrs.setdefault("content-type", "application/json")
        full = httpx.URL(url).copy_merge_params(dict(params)) if params else httpx.URL(url)
        return cls(method.upper(), str(full), tuple(hdrs.items()), body)

    def header(self, name: str) -> str | None:
        return _header(self.headers, name)


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    headers: Headers  # paires brutes : casse et headers multiples (Set-Cookie) préservés
    text: str
    rung: int
    from_cache: bool = False

    def header(self, name: str) -> str | None:
        return _header(self.headers, name)

    def json(self) -> Any:
        return json.loads(self.text)


class TransportError(Exception):
    """Échec réseau (connexion, timeout, navigateur) : aucune réponse HTTP exploitable."""


class Transport(Protocol):
    follows_redirects: bool  # False : la coquille suit les redirections et vérifie chaque saut

    async def send(self, req: HttpRequest) -> FetchResult: ...
    async def aclose(self) -> None: ...

    def take_browser_requests(self) -> int:
        """Requêtes lancées par le navigateur lui-même depuis le dernier appel (0 hors 3-4)."""
        ...
