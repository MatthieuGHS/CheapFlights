import asyncio
import hashlib
import json
import random
import sqlite3
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
import tldextract

from cheaphops.core.config import HttpConfig
from cheaphops.core.models import Manifest, RateLimit
from cheaphops.fetch.ladder import RUNGS, Outcome, classify, start_rung
from cheaphops.fetch.transports import default_transports
from cheaphops.fetch.types import FetchResult, HttpRequest, Transport, TransportError

Freshness = Literal["explore", "verify", "none"]
MAX_REDIRECTS = 5
_PSL = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)  # liste embarquée, hors ligne


class DomainNotAllowed(Exception):
    pass


class SourceBlocked(Exception):
    pass


class FetchFailed(Exception):
    def __init__(self, source: str, outcome: str, result: FetchResult | None) -> None:
        status = result.status if result else "-"
        super().__init__(f"{source}: {outcome} (HTTP {status})")
        self.outcome, self.result = outcome, result


def allowed_domain(url: str, domains: list[str]) -> str | None:
    """Entrée de l'allowlist qui couvre `url` (hôte égal ou sous-domaine, https seulement)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        return None
    return next((d for d in domains if host == d or host.endswith("." + d)), None)


def registrable_domain(url: str) -> str:
    """`api.ryanair.com` -> `ryanair.com` : clé du rate limit, toutes sources confondues."""
    ext = _PSL(url)
    return ext.top_domain_under_public_suffix or ext.fqdn


class Throttle:
    """Espace les requêtes par domaine enregistrable. Une instance par process, partagée entre
    sources : deux sources qui visent le même domaine sont freinées ensemble."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._clock, self._sleep, self._jitter = clock, sleep, jitter
        self._locks: dict[str, asyncio.Lock] = {}
        self._next: dict[str, float] = {}

    async def wait(self, url: str, rate: RateLimit) -> None:
        domain = registrable_domain(url)
        async with self._locks.setdefault(domain, asyncio.Lock()):
            delay = self._next.get(domain, 0.0) - self._clock()
            if delay > 0:
                await self._sleep(delay)
            self._next[domain] = (
                self._clock() + rate.min_interval_s + self._jitter(0, rate.jitter_s)
            )


class CtxHttp:
    """Seul accès réseau d'une recette. La coquille porte tout ce qui ne dépend pas du rung :
    allowlist, cache, rate limit, stats, état bloqué, montée de rung. Un transport ne fait
    qu'envoyer."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        manifest: Manifest,
        config: HttpConfig,
        throttle: Throttle,
        transports: Mapping[int, Transport] | None = None,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._conn, self._manifest, self._cfg, self._throttle = conn, manifest, config, throttle
        self._transports = transports or default_transports(config, manifest)
        self._now, self._sleep = now, sleep
        self._vary = [h.lower() for h in config.vary_headers]
        self._ttl = {"explore": config.explore_ttl_s, "verify": config.verify_ttl_s, "none": 0}

    async def __aenter__(self) -> "CtxHttp":
        return self

    async def __aexit__(self, *exc: object) -> None:
        for t in self._transports.values():
            await t.aclose()

    async def get(
        self,
        url: str,
        *,
        freshness: Freshness,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResult:
        req = HttpRequest.build("GET", url, params=params, headers=headers)
        return await self._request(req, freshness)

    async def post(
        self,
        url: str,
        *,
        freshness: Freshness,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResult:
        req = HttpRequest.build("POST", url, headers=headers, json_body=json)
        return await self._request(req, freshness)

    async def _request(self, req: HttpRequest, freshness: Freshness) -> FetchResult:
        self._check_allowed(req.url)
        self._check_not_blocked()
        ttl, key = self._ttl[freshness], self._cache_key(req)
        if ttl and (hit := self._cached(key)):
            return hit
        rung = start_rung(self._stats(), self._manifest.preferred_rung)
        backoff = self._cfg.rate_limited_backoff_s
        outcome, result = Outcome.FAILED, None
        for _ in range(self._cfg.max_attempts):
            result, latency = await self._send(rung, req)
            outcome = classify(result, self._cfg)
            # 404/5xx : le rung a bien livré une réponse, ce n'est pas un échec de rung
            rung_ok = outcome in (Outcome.OK, Outcome.FAILED)
            self._record(rung, None if rung_ok else f"{outcome} HTTP {result.status}", latency)
            if outcome is Outcome.OK:
                self._set_blocked(None)
                if ttl:
                    self._store(key, result, ttl)
                return result
            if outcome is Outcome.CAPTCHA or (outcome is Outcome.BLOCKED and rung == RUNGS[-1]):
                self._set_blocked(f"{outcome} at rung {rung}")
                raise SourceBlocked(f"{self._manifest.source}: {outcome} at rung {rung}")
            if outcome is Outcome.BLOCKED:
                rung += 1
            elif outcome is Outcome.RATE_LIMITED:
                await self._sleep(backoff)
                backoff *= 2
            else:
                break
        raise FetchFailed(self._manifest.source, outcome, result)

    async def _send(self, rung: int, req: HttpRequest) -> tuple[FetchResult, float]:
        """Un envoi sur un rung, redirections comprises, chaque saut vérifié contre l'allowlist.
        Renvoie la réponse finale et la latence cumulée."""
        transport, latency = self._transports[rung], 0.0
        for _ in range(MAX_REDIRECTS + 1):
            await self._throttle.wait(req.url, self._manifest.rate_limit)
            start = time.monotonic()
            try:
                result = await transport.send(req)
            except TransportError as e:
                self._record(rung, str(e)[:200], latency + time.monotonic() - start)
                raise FetchFailed(self._manifest.source, "transport", None) from e
            latency += time.monotonic() - start
            location = result.header("location")
            if transport.follows_redirects or not (300 <= result.status < 400 and location):
                self._check_hop(rung, result.url, latency)
                return result, latency
            target = str(httpx.URL(req.url).join(location))
            self._check_hop(rung, target, latency)
            keep = result.status in (307, 308)
            req = HttpRequest(
                req.method if keep else "GET", target, req.headers, req.body if keep else None
            )
        raise FetchFailed(self._manifest.source, "too many redirects", None)

    def _check_allowed(self, url: str) -> None:
        if allowed_domain(url, self._manifest.allowed_domains) is None:
            raise DomainNotAllowed(f"{self._manifest.source}: {url}")

    def _check_hop(self, rung: int, url: str, latency: float) -> None:
        """Une redirection hors allowlist compte comme un échec : souvent un mur anti-bot."""
        if allowed_domain(url, self._manifest.allowed_domains) is None:
            self._record(rung, "redirect off allowlist", latency)
            raise DomainNotAllowed(f"{self._manifest.source}: {url}")

    def _check_not_blocked(self) -> None:
        row = self._conn.execute(
            "SELECT blocked_until, reason FROM source_state WHERE source = ?",
            (self._manifest.source,),
        ).fetchone()
        if row and row["blocked_until"] and row["blocked_until"] > self._now():
            raise SourceBlocked(f"{self._manifest.source}: {row['reason']} (en backoff)")

    def _set_blocked(self, reason: str | None) -> None:
        """None : succès, remise à zéro. Sinon backoff doublé à chaque blocage consécutif."""
        src = self._manifest.source
        if reason is None:
            self._conn.execute("DELETE FROM source_state WHERE source = ?", (src,))
            return
        row = self._conn.execute(
            "SELECT strikes FROM source_state WHERE source = ?", (src,)
        ).fetchone()
        strikes = (row["strikes"] if row else 0) + 1
        until = self._now() + self._cfg.blocked_backoff_s * 2 ** (strikes - 1)
        self._conn.execute(
            "INSERT OR REPLACE INTO source_state VALUES (?, ?, ?, ?)", (src, strikes, until, reason)
        )

    def _cache_key(self, req: HttpRequest) -> str:
        h = hashlib.sha256()
        vary = (f"{v}:{req.header(v) or ''}" for v in self._vary)
        for part in (req.method, req.url, *vary):
            h.update(part.encode() + b"\0")
        h.update(req.body or b"")
        return h.hexdigest()

    # shortcut: sqlite synchrone dans l'event loop, ok pour un utilisateur ; passer par
    # asyncio.to_thread si la latence SSE de la phase 2 en souffre
    def _cached(self, key: str) -> FetchResult | None:
        row = self._conn.execute(
            "SELECT url, status, headers, body, rung FROM http_cache"
            " WHERE key = ? AND expires_at > ?",
            (key, self._now()),
        ).fetchone()
        if row is None:
            return None
        headers = tuple((k, v) for k, v in json.loads(row["headers"]))
        return FetchResult(row["url"], row["status"], headers, row["body"], row["rung"], True)

    def _store(self, key: str, r: FetchResult, ttl_s: int) -> None:
        now = self._now()
        self._conn.execute("DELETE FROM http_cache WHERE expires_at <= ?", (now,))
        self._conn.execute(
            "INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (key, r.url, r.status, json.dumps(r.headers), r.text, now, now + ttl_s, r.rung),
        )

    def _stats(self) -> dict[int, tuple[int, int]]:
        rows = self._conn.execute(
            "SELECT rung, successes, failures FROM fetch_stats WHERE source = ?",
            (self._manifest.source,),
        )
        return {r["rung"]: (r["successes"], r["failures"]) for r in rows}

    def _record(self, rung: int, failure: str | None, latency: float) -> None:
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
                rung,
                failure is None,
                failure is not None,
                latency,
                failure,
                self._now() if failure else None,
            ),
        )
