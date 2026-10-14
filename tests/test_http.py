import asyncio
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from cheaphops.core.config import load_config
from cheaphops.core.db import connect
from cheaphops.core.models import Manifest
from cheaphops.fetch.http import CtxHttp, DomainNotAllowed, Throttle

pytestmark = pytest.mark.anyio
HTTP_CFG = load_config(Path(__file__).parent.parent / "config.yaml", Path("/nonexistent")).http
MANIFEST = Manifest(
    source="ryanair",
    version=1,
    capabilities={"calendar"},
    allowed_domains=["ryanair.com"],
    preferred_rung=1,
    rate_limit={"min_interval_s": 2.0, "jitter_s": 0.5},
    status="active",
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    c = connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make(conn: sqlite3.Connection, clock: FakeClock, handler: httpx.MockTransport) -> CtxHttp:
    throttle = Throttle(clock=clock, sleep=clock.sleep, jitter=lambda lo, hi: hi)
    return CtxHttp(conn, MANIFEST, HTTP_CFG, throttle, transport=handler, now=clock)


def counting(status: int = 200) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(status, json={"n": len(seen)})

    return httpx.MockTransport(handle), seen


@pytest.mark.parametrize(
    "url",
    [
        "https://evilryanair.com/api",
        "https://ryanair.com.evil.net/api",
        "http://www.ryanair.com/api",
        "https://wizzair.com/api",
    ],
)
async def test_disallowed_url_never_sent(
    conn: sqlite3.Connection, clock: FakeClock, url: str
) -> None:
    transport, seen = counting()
    async with make(conn, clock, transport) as http:
        with pytest.raises(DomainNotAllowed):
            await http.get(url, ttl_s=0)
    assert seen == []


async def test_redirect_off_allowlist_blocked(conn: sqlite3.Connection, clock: FakeClock) -> None:
    hosts: list[str] = []

    def handle(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return httpx.Response(302, headers={"location": "https://evil.net/x"})

    async with make(conn, clock, httpx.MockTransport(handle)) as http:
        with pytest.raises(DomainNotAllowed):
            await http.get("https://www.ryanair.com/a", ttl_s=0)
    assert hosts == ["www.ryanair.com"]


async def test_cache_hit_until_ttl_expires(conn: sqlite3.Connection, clock: FakeClock) -> None:
    transport, seen = counting()
    async with make(conn, clock, transport) as http:
        first = await http.get("https://api.ryanair.com/f", params={"d": "BGY"}, ttl_s=60)
        second = await http.get("https://api.ryanair.com/f", params={"d": "BGY"}, ttl_s=60)
        assert (first.from_cache, second.from_cache, second.text) == (False, True, first.text)
        assert len(seen) == 1
        clock.t += 61
        third = await http.get("https://api.ryanair.com/f", params={"d": "BGY"}, ttl_s=60)
    assert not third.from_cache and len(seen) == 2


async def test_cache_key_includes_params_body_and_vary_headers(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    transport, seen = counting()
    url = "https://api.ryanair.com/f"
    async with make(conn, clock, transport) as http:
        await http.get(url, params={"d": "BGY"}, ttl_s=60)
        await http.get(url, params={"d": "STN"}, ttl_s=60)
        await http.get(url, params={"d": "BGY"}, headers={"Accept-Language": "lt"}, ttl_s=60)
        await http.get(url, params={"d": "BGY"}, headers={"X-Trace": "1"}, ttl_s=60)
        await http.post(url, json={"a": 1}, ttl_s=60)
        await http.post(url, json={"a": 2}, ttl_s=60)
    assert len(seen) == 5  # X-Trace ne fait pas varier la réponse : cache hit


async def test_errors_not_cached_and_counted(conn: sqlite3.Connection, clock: FakeClock) -> None:
    transport, seen = counting(status=403)
    async with make(conn, clock, transport) as http:
        r = await http.get("https://www.ryanair.com/x", ttl_s=60)
        await http.get("https://www.ryanair.com/x", ttl_s=60)
    assert r.status == 403 and len(seen) == 2
    row = conn.execute("SELECT * FROM fetch_stats WHERE source = 'ryanair'").fetchone()
    assert (row["rung"], row["successes"], row["failures"]) == (1, 0, 2)
    assert row["last_failure"] == "HTTP 403"


async def test_network_error_counted_and_raised(conn: sqlite3.Connection, clock: FakeClock) -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=req)

    async with make(conn, clock, httpx.MockTransport(boom)) as http:
        with pytest.raises(httpx.ConnectError):
            await http.get("https://www.ryanair.com/x", ttl_s=0)
    row = conn.execute("SELECT failures, last_failure FROM fetch_stats").fetchone()
    assert tuple(row) == (1, "ConnectError")


async def test_same_domain_spaced_by_interval_plus_jitter(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    transport, _ = counting()
    async with make(conn, clock, transport) as http:
        await asyncio.gather(
            *(http.get(f"https://{h}.ryanair.com/x", ttl_s=0) for h in ("a", "b", "c"))
        )
    assert clock.slept == [2.5, 2.5]  # sous-domaines = même domaine de l'allowlist


async def test_other_domain_not_throttled_by_first(clock: FakeClock) -> None:
    throttle = Throttle(clock=clock, sleep=clock.sleep, jitter=lambda lo, hi: hi)
    await throttle.wait("ryanair.com", MANIFEST.rate_limit)
    await throttle.wait("wizzair.com", MANIFEST.rate_limit)
    assert clock.slept == []


async def test_store_purges_expired_entries(conn: sqlite3.Connection, clock: FakeClock) -> None:
    transport, _ = counting()
    async with make(conn, clock, transport) as http:
        await http.get("https://www.ryanair.com/old", ttl_s=10)
        clock.t += 11
        await http.get("https://www.ryanair.com/new", ttl_s=10)
    urls = [r[0] for r in conn.execute("SELECT url FROM http_cache")]
    assert urls == ["https://www.ryanair.com/new"]
