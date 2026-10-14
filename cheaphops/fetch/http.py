import asyncio
import hashlib
import json
import random
import sqlite3
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from cheaphops.core.config import HttpConfig
from cheaphops.core.models import Manifest, RateLimit

# shortcut: httpx seul (rung 1), la fetch ladder rungs 2-4 arrive en phase 1
RUNG = 1


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    headers: dict[str, str]
    text: str
    from_cache: bool


class DomainNotAllowed(Exception):
    pass


def allowed_domain(url: str, domains: list[str]) -> str | None:
    """Entrée de l'allowlist qui couvre `url` (hôte égal ou sous-domaine, https seulement)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        return None
    return next((d for d in domains if host == d or host.endswith("." + d)), None)


class Throttle:
    """Espace les requêtes par domaine. Une instance par process, partagée entre sources."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._clock, self._sleep, self._jitter = clock, sleep, jitter
        self._locks: dict[str, asyncio.Lock] = {}
        self._next: dict[str, float] = {}

    async def wait(self, domain: str, rate: RateLimit) -> None:
        async with self._locks.setdefault(domain, asyncio.Lock()):
            delay = self._next.get(domain, 0.0) - self._clock()
            if delay > 0:
                await self._sleep(delay)
            self._next[domain] = (
                self._clock() + rate.min_interval_s + self._jitter(0, rate.jitter_s)
            )


class CtxHttp:
    """Seul accès réseau d'une recette : allowlist du manifeste, rate limit, cache, stats."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        manifest: Manifest,
        config: HttpConfig,
        throttle: Throttle,
        transport: httpx.AsyncBaseTransport | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._conn, self._manifest, self._throttle, self._now = conn, manifest, throttle, now
        self._vary = [h.lower() for h in config.vary_headers]
        self._client = httpx.AsyncClient(
            timeout=config.timeout_s,
            follow_redirects=True,
            transport=transport,
            event_hooks={"request": [self._guard_redirect]},
        )

    async def __aenter__(self) -> "CtxHttp":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def get(
        self, url: str, *, ttl_s: int, params: Any = None, headers: Any = None
    ) -> FetchResult:
        return await self.request("GET", url, ttl_s=ttl_s, params=params, headers=headers)

    async def post(
        self, url: str, *, ttl_s: int, json: Any = None, headers: Any = None
    ) -> FetchResult:
        return await self.request("POST", url, ttl_s=ttl_s, json=json, headers=headers)

    async def request(self, method: str, url: str, *, ttl_s: int, **kwargs: Any) -> FetchResult:
        req = self._client.build_request(method, url, **kwargs)
        domain = self._domain(str(req.url))
        key = self._cache_key(req)
        if ttl_s > 0 and (hit := self._cached(key)):
            return hit
        await self._throttle.wait(domain, self._manifest.rate_limit)
        start = time.monotonic()
        try:
            resp = await self._client.send(req)
        except httpx.HTTPError as e:
            self._record(time.monotonic() - start, type(e).__name__)
            raise
        failure = None if resp.is_success else f"HTTP {resp.status_code}"
        self._record(time.monotonic() - start, failure)
        result = FetchResult(str(resp.url), resp.status_code, dict(resp.headers), resp.text, False)
        if resp.is_success and ttl_s > 0:
            self._store(key, result, ttl_s)
        return result

    def _domain(self, url: str) -> str:
        domain = allowed_domain(url, self._manifest.allowed_domains)
        if domain is None:
            raise DomainNotAllowed(f"{self._manifest.source}: {url}")
        return domain

    async def _guard_redirect(self, request: httpx.Request) -> None:
        self._domain(str(request.url))

    def _cache_key(self, req: httpx.Request) -> str:
        h = hashlib.sha256()
        vary = (f"{v}:{req.headers.get(v, '')}" for v in self._vary)
        for part in (req.method, str(req.url), *vary):
            h.update(part.encode() + b"\0")
        h.update(req.content)
        return h.hexdigest()

    # shortcut: sqlite synchrone dans l'event loop, ok pour un utilisateur ; passer par
    # asyncio.to_thread si la latence SSE de la phase 2 en souffre
    def _cached(self, key: str) -> FetchResult | None:
        row = self._conn.execute(
            "SELECT url, status, headers, body FROM http_cache WHERE key = ? AND expires_at > ?",
            (key, self._now()),
        ).fetchone()
        if row is None:
            return None
        return FetchResult(row["url"], row["status"], json.loads(row["headers"]), row["body"], True)

    def _store(self, key: str, r: FetchResult, ttl_s: int) -> None:
        now = self._now()
        self._conn.execute("DELETE FROM http_cache WHERE expires_at <= ?", (now,))
        self._conn.execute(
            "INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
            (key, r.url, r.status, json.dumps(r.headers), r.text, now, now + ttl_s),
        )

    def _record(self, latency_s: float, failure: str | None) -> None:
        self._conn.execute(
            """
            INSERT INTO fetch_stats VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, rung) DO UPDATE SET
                successes = successes + excluded.successes,
                failures = failures + excluded.failures,
                total_latency_s = total_latency_s + excluded.total_latency_s,
                last_failure = coalesce(excluded.last_failure, last_failure),
                last_failure_at = coalesce(excluded.last_failure_at, last_failure_at)
            """,
            (
                self._manifest.source,
                RUNG,
                failure is None,
                failure is not None,
                latency_s,
                failure,
                self._now() if failure else None,
            ),
        )
