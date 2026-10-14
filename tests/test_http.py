import asyncio
import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from cheaphops.core.config import load_config
from cheaphops.core.db import connect
from cheaphops.core.models import Manifest
from cheaphops.fetch.http import (
    CtxHttp,
    DomainNotAllowed,
    FetchFailed,
    SourceBlocked,
    Throttle,
    registrable_domain,
)
from cheaphops.fetch.ladder import start_rung
from cheaphops.fetch.types import FetchResult, HttpRequest, TransportError

pytestmark = pytest.mark.anyio
CFG = load_config(Path(__file__).parent.parent / "config.yaml", Path("/nonexistent")).http
JSON = (("content-type", "application/json"),)


def manifest(source: str = "ryanair", domains: tuple[str, ...] = ("ryanair.com",)) -> Manifest:
    return Manifest.model_validate(
        {
            "source": source,
            "version": 1,
            "capabilities": {"calendar"},
            "allowed_domains": list(domains),
            "home_url": f"https://www.{domains[0]}/",
            "preferred_rung": 1,
            "block_markers": ["Availability declined"],
            "headed": False,
            "cookie_headers": {},
            "rate_limit": {"min_interval_s": 2.0, "jitter_s": 0.5},
            "status": "active",
        }
    )


Reply = tuple[int, tuple[tuple[str, str], ...], str] | Exception


class Scripted:
    """Transport factice : `handler(req)` décide de la réponse ; garde la trace des envois."""

    def __init__(self, rung: int, handler: Callable[[HttpRequest], Reply], follows: bool = False):
        self.rung, self.handler, self.follows_redirects = rung, handler, follows
        self.sent: list[HttpRequest] = []

    async def send(self, req: HttpRequest) -> FetchResult:
        self.sent.append(req)
        out = self.handler(req)
        if isinstance(out, Exception):
            raise out
        status, headers, text = out
        loaded = 3 if self.rung == 4 else 0  # rung 4 : la page charge aussi ses ressources
        return FetchResult(req.url, status, headers, text, self.rung, browser_requests=loaded)

    async def aclose(self) -> None:
        pass


def ok(req: HttpRequest) -> Reply:
    return 200, JSON, json.dumps({"url": req.url})


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


def make(
    conn: sqlite3.Connection,
    clock: FakeClock,
    *handlers: Callable[[HttpRequest], Reply],
    m: Manifest | None = None,
    throttle: Throttle | None = None,
) -> tuple[CtxHttp, list[Scripted]]:
    """Rung i+1 répond via handlers[i] ; les rungs non fournis répondent comme le dernier."""
    hs = list(handlers) + [handlers[-1]] * (4 - len(handlers))
    transports = [Scripted(i + 1, h) for i, h in enumerate(hs)]
    throttle = throttle or Throttle(clock=clock, sleep=clock.sleep, jitter=lambda lo, hi: hi)
    http = CtxHttp(
        conn,
        m or manifest(),
        CFG,
        throttle,
        transports={t.rung: t for t in transports},
        now=clock,
        sleep=clock.sleep,
    )
    return http, transports


def stats(conn: sqlite3.Connection) -> dict[int, tuple[int, int]]:
    rows = conn.execute("SELECT rung, successes, failures FROM fetch_stats")
    return {r[0]: (r[1], r[2]) for r in rows}


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
    http, ts = make(conn, clock, ok)
    with pytest.raises(DomainNotAllowed):
        await http.get(url, freshness="none")
    assert all(t.sent == [] for t in ts)


async def test_redirect_inside_allowlist_followed_as_get(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    def handle(req: HttpRequest) -> Reply:
        if req.url.endswith("/a"):
            return 302, (("Location", "/b"),), ""
        return ok(req)

    http, ts = make(conn, clock, handle)
    r = await http.post("https://www.ryanair.com/a", json={"x": 1}, freshness="none")
    assert r.url == "https://www.ryanair.com/b"
    assert [(q.method, q.body) for q in ts[0].sent] == [("POST", b'{"x":1}'), ("GET", None)]


async def test_redirect_off_allowlist_blocked_and_counted(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, ts = make(conn, clock, lambda req: (302, (("location", "https://evil.net/x"),), ""))
    with pytest.raises(DomainNotAllowed):
        await http.get("https://www.ryanair.com/a", freshness="none")
    assert len(ts[0].sent) == 1
    assert stats(conn) == {1: (0, 1)}


async def test_cache_hit_until_ttl_expires(conn: sqlite3.Connection, clock: FakeClock) -> None:
    http, ts = make(conn, clock, ok)
    url, params = "https://api.ryanair.com/f", {"d": "BGY"}
    first = await http.get(url, params=params, freshness="verify")
    second = await http.get(url, params=params, freshness="verify")
    assert (first.from_cache, second.from_cache, second.text) == (False, True, first.text)
    assert len(ts[0].sent) == 1
    clock.t += CFG.verify_ttl_s + 1
    assert not (await http.get(url, params=params, freshness="verify")).from_cache
    assert len(ts[0].sent) == 2


async def test_freshness_none_skips_cache_read_but_writes(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, ts = make(conn, clock, ok)
    for _ in range(2):
        await http.get("https://api.ryanair.com/f", freshness="none")
    assert len(ts[0].sent) == 2
    assert (await http.get("https://api.ryanair.com/f", freshness="explore")).from_cache


async def test_cache_key_includes_params_body_and_vary_headers(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, ts = make(conn, clock, ok)
    url = "https://api.ryanair.com/f"
    await http.get(url, params={"d": "BGY"}, freshness="explore")
    await http.get(url, params={"d": "STN"}, freshness="explore")
    await http.get(url, params={"d": "BGY"}, headers={"Accept-Language": "lt"}, freshness="explore")
    await http.get(url, params={"d": "BGY"}, headers={"X-Trace": "1"}, freshness="explore")
    await http.post(url, json={"a": 1}, freshness="explore")
    await http.post(url, json={"a": 2}, freshness="explore")
    assert len(ts[0].sent) == 5  # X-Trace ne fait pas varier la réponse : cache hit


async def test_cached_headers_keep_pairs_and_case_insensitive_lookup(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    cookies = (("Content-Type", "application/json"), ("Set-Cookie", "a=1"), ("Set-Cookie", "b=2"))
    http, _ = make(conn, clock, lambda req: (200, cookies, "{}"))
    await http.get("https://www.ryanair.com/x", freshness="explore")
    hit = await http.get("https://www.ryanair.com/x", freshness="explore")
    assert hit.from_cache and hit.header("content-type") == "application/json"
    assert [v for k, v in hit.headers if k == "Set-Cookie"] == ["a=1", "b=2"]


async def test_failure_not_cached_not_retried_on_other_rungs(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, ts = make(conn, clock, lambda req: (404, JSON, "{}"))
    for _ in range(2):
        with pytest.raises(FetchFailed) as e:
            await http.get("https://www.ryanair.com/x", freshness="explore")
        assert e.value.outcome == "failed"
    assert len(ts[0].sent) == 2 and ts[1].sent == []
    assert stats(conn) == {1: (2, 0)}  # le rung a répondu : pas un échec de rung


async def test_blocked_climbs_one_rung(conn: sqlite3.Connection, clock: FakeClock) -> None:
    http, ts = make(conn, clock, lambda req: (403, (), "Access Denied"), ok)
    r = await http.get("https://www.ryanair.com/x", freshness="none")
    assert r.rung == 2 and len(ts[0].sent) == 1
    assert stats(conn) == {1: (0, 1), 2: (1, 0)}


async def test_browser_resources_counted_apart_from_scraping_requests(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, _ = make(conn, clock, *[lambda req: (403, (), "x")] * 3, ok)
    await http.get("https://www.ryanair.com/x", freshness="none")
    row = conn.execute(
        "SELECT successes, failures, browser_requests FROM fetch_stats WHERE rung = 4"
    )
    assert tuple(row.fetchone()) == (1, 0, 3)


async def test_blocked_on_every_rung_marks_source_blocked_with_doubling_backoff(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, ts = make(conn, clock, lambda req: (403, (), "nope"))
    with pytest.raises(SourceBlocked):
        await http.get("https://www.ryanair.com/x", freshness="none")
    assert [len(t.sent) for t in ts] == [1, 1, 1, 1]
    with pytest.raises(SourceBlocked, match="backoff"):
        await http.get("https://www.ryanair.com/x", freshness="none")
    assert len(ts[0].sent) == 1  # rien envoyé pendant le backoff
    clock.t += CFG.blocked_backoff_s + 1
    with pytest.raises(SourceBlocked):
        await http.get("https://www.ryanair.com/x", freshness="none")
    until = conn.execute("SELECT blocked_until FROM source_state").fetchone()[0]
    assert until == pytest.approx(clock.t + 2 * CFG.blocked_backoff_s)


async def test_captcha_blocks_source_without_climbing(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    page = (("content-type", "text/html"),)
    http, ts = make(conn, clock, lambda req: (200, page, "<div class='cf-turnstile'>"), ok)
    with pytest.raises(SourceBlocked, match="captcha"):
        await http.get("https://www.ryanair.com/x", freshness="none")
    assert ts[1].sent == []


async def test_source_marker_in_json_error_climbs(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, _ = make(conn, clock, lambda req: (409, JSON, '{"message":"Availability declined"}'), ok)
    assert (await http.get("https://www.ryanair.com/x", freshness="none")).rung == 2


async def test_antibot_challenge_served_as_429_is_blocked_not_rate_limited(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    challenge = (429, (("content-type", "text/html"),), "<script>window.KPSDK={}</script>")
    m = manifest().model_copy(update={"block_markers": ["KPSDK"]})
    http, ts = make(conn, clock, lambda req: challenge, ok, m=m)
    assert (await http.get("https://www.ryanair.com/x", freshness="none")).rung == 2
    assert len(ts[0].sent) == 1  # pas d'attente ni de nouvel essai sur le même rung


async def test_real_page_citing_recaptcha_is_not_a_wall(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    page = "<html>" + "x" * 120_000 + "<a class='recaptcha-terms-privacy'>"  # comme l'accueil Wizz
    http, _ = make(conn, clock, lambda req: (200, (("content-type", "text/html"),), page))
    assert (await http.get("https://www.ryanair.com/", freshness="none")).status == 200


async def test_json_mentioning_captcha_is_ok(conn: sqlite3.Connection, clock: FakeClock) -> None:
    http, _ = make(conn, clock, lambda req: (200, JSON, '{"captcha": false}'))
    assert (await http.get("https://www.ryanair.com/x", freshness="none")).status == 200


async def test_success_clears_block_state(conn: sqlite3.Connection, clock: FakeClock) -> None:
    conn.execute("INSERT INTO source_state VALUES ('ryanair', 2, ?, 'old')", (clock.t - 1,))
    http, _ = make(conn, clock, ok)
    await http.get("https://www.ryanair.com/x", freshness="none")
    assert conn.execute("SELECT count(*) FROM source_state").fetchone()[0] == 0


async def test_rate_limited_backs_off_exponentially_on_same_rung(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    replies = iter([(429, JSON, "{}"), (429, JSON, "{}"), (200, JSON, "{}")])
    http, ts = make(conn, clock, lambda req: next(replies))
    clock.slept.clear()
    await http.get("https://www.ryanair.com/x", freshness="none")
    backoffs = [s for s in clock.slept if s >= CFG.rate_limited_backoff_s]
    assert backoffs == [CFG.rate_limited_backoff_s, 2 * CFG.rate_limited_backoff_s]
    assert len(ts[0].sent) == 3 and ts[1].sent == []
    assert stats(conn) == {1: (1, 0)}  # un 429 parle du domaine, pas du rung


async def test_transport_error_counted_and_raised(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, _ = make(conn, clock, lambda req: TransportError("down"))
    with pytest.raises(FetchFailed, match="transport"):
        await http.get("https://www.ryanair.com/x", freshness="none")
    assert stats(conn) == {1: (0, 1), 2: (0, 1), 3: (0, 1), 4: (0, 1)}  # chaque rung tenté


async def test_transport_error_climbs(conn: sqlite3.Connection, clock: FakeClock) -> None:
    http, _ = make(conn, clock, lambda req: TransportError("no browser"), ok)
    assert (await http.get("https://www.ryanair.com/x", freshness="none")).rung == 2


async def test_next_request_starts_on_rung_that_worked(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, ts = make(conn, clock, lambda req: (403, (), "x"), ok)
    await http.get("https://www.ryanair.com/a", freshness="none")
    await http.get("https://www.ryanair.com/b", freshness="none")
    assert len(ts[0].sent) == 1 and len(ts[1].sent) == 2


def test_start_rung_heuristic() -> None:
    assert start_rung({}, preferred=3) == 3
    assert start_rung({1: (10, 1)}, preferred=1) == 1
    assert start_rung({1: (0, 5)}, preferred=1) == 2  # rung 1 en échec : un rung neuf vaut mieux
    assert start_rung({1: (10, 1), 3: (1, 0)}, preferred=1) == 1  # un succès isolé ne suffit pas


async def test_throttle_shared_by_registrable_domain_across_sources(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    throttle = Throttle(clock=clock, sleep=clock.sleep, jitter=lambda lo, hi: hi)
    a, _ = make(conn, clock, ok, m=manifest("a", ("ryanair.com",)), throttle=throttle)
    b, _ = make(conn, clock, ok, m=manifest("b", ("www.ryanair.com",)), throttle=throttle)
    await asyncio.gather(
        a.get("https://api.ryanair.com/x", freshness="none"),
        b.get("https://www.ryanair.com/y", freshness="none"),
    )
    assert clock.slept == [2.5]


async def test_throttle_does_not_couple_different_domains(clock: FakeClock) -> None:
    throttle = Throttle(clock=clock, sleep=clock.sleep, jitter=lambda lo, hi: hi)
    rate = manifest().rate_limit
    await throttle.wait("https://www.ryanair.com/", rate)
    await throttle.wait("https://wizzair.com/", rate)
    assert clock.slept == []


def test_registrable_domain_uses_public_suffix_list() -> None:
    assert registrable_domain("https://services-api.ryanair.com/x") == "ryanair.com"
    assert registrable_domain("https://a.b.example.co.uk/") == "example.co.uk"


async def test_explore_cache_entry_too_old_for_verify(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, ts = make(conn, clock, ok)
    await http.get("https://www.ryanair.com/x", freshness="explore")
    clock.t += CFG.verify_ttl_s + 1
    assert (await http.get("https://www.ryanair.com/x", freshness="explore")).from_cache
    assert not (await http.get("https://www.ryanair.com/x", freshness="verify")).from_cache
    assert len(ts[0].sent) == 2


async def test_blocked_source_still_serves_fresh_cache(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    http, _ = make(conn, clock, ok)
    await http.get("https://www.ryanair.com/x", freshness="explore")
    conn.execute("INSERT INTO source_state VALUES ('ryanair', 1, ?, 'blocked')", (clock.t + 99,))
    assert (await http.get("https://www.ryanair.com/x", freshness="explore")).from_cache
    with pytest.raises(SourceBlocked):
        await http.get("https://www.ryanair.com/other", freshness="explore")


async def test_closed_gate_still_serves_cache_but_refuses_network(
    conn: sqlite3.Connection, clock: FakeClock
) -> None:
    from cheaphops.fetch.http import BudgetExhausted

    http, ts = make(conn, clock, ok)
    await http.get("https://www.ryanair.com/x", freshness="explore")
    closed = CtxHttp(conn, manifest(), CFG, Throttle(clock=clock, sleep=clock.sleep),
                     transports={t.rung: t for t in ts}, now=clock, gate=lambda: False)  # fmt: skip
    assert (await closed.get("https://www.ryanair.com/x", freshness="explore")).from_cache
    with pytest.raises(BudgetExhausted):
        await closed.get("https://www.ryanair.com/other", freshness="explore")
    assert len(ts[0].sent) == 1
