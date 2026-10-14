import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from cheaphops.api.app import create_app
from cheaphops.search.engine import SearchResult
from cheaphops.search.model import Segment, Trip

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).parent.parent
TZ = timezone(timedelta(hours=2))


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    text = (
        (ROOT / "config.yaml")
        .read_text()
        .replace("db_path: data/cheaphops.db", f"db_path: {tmp_path}/t.db")
    )
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return path


def a_trip() -> Trip:
    dep = datetime(2026, 11, 6, 8, tzinfo=TZ)
    out = Segment(
        "ryanair", "VNO", "BGY", dep.date(), Decimal("19.99"), dep, dep + timedelta(hours=2)
    )
    back = Segment("wizzair", "BGY", "VNO", date(2026, 11, 8), Decimal("25"))
    return Trip((out,), (back,), (), Decimal("44.99"), Decimal("44.99"), 2, None, ("à vérifier",))


async def fake_search(
    params: Any, config: Any, ground: Any, conn: Any, today: date, emit: Any, throttle: Any
) -> SearchResult:
    assert throttle is not None  # un seul rate limiter par process, partagé entre recherches
    for i in range(3):  # forme réelle des événements du moteur (engine.py)
        emit({"type": "progress", "phase": "explore", "level": 1, "of": 3, "done": i + 1,
              "source": "ryanair", "requests": i, "cache_hits": 0, "rung": 3})  # fmt: skip
        await asyncio.sleep(0)
    emit({"type": "candidates", "count": 12})
    return SearchResult([a_trip()], requests=7, budget_exhausted=False, candidates=4, pruned=9)


def client(config_path: Path) -> httpx.AsyncClient:
    app = create_app(config_path, ROOT / "ground.yaml", fake_search, lambda: date(2026, 10, 14))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_search_streams_progress_in_order_then_results(config_path: Path) -> None:
    async with client(config_path) as c:
        run = (
            await c.post("/api/searches", json={"preset": "weekend", "overrides": {"top_k": 5}})
        ).json()
        stream = (await c.get(f"/api/searches/{run['id']}/events")).text
        events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
        assert [e["type"] for e in events] == ["progress"] * 3 + ["candidates", "finished"]
        assert [e.get("done") for e in events[:3]] == [1, 2, 3]
        body = (await c.get(f"/api/searches/{run['id']}")).json()
    assert body["done"] and body["error"] is None and body["params"]["top_k"] == 5
    assert body["params"]["depart_weekdays"] == [4, 5]  # preset week-end
    trip = body["result"]["trips"][0]
    assert trip["outbound"][0]["flight_no"] is None and trip["inbound"][0]["departure"] is None
    assert trip["score"] == 44.99 and body["result"]["requests"] == 7


async def test_invalid_override_rejected(config_path: Path) -> None:
    async with client(config_path) as c:
        r = await c.post("/api/searches", json={"overrides": {"max_nights": -1}})
        assert r.status_code == 422
        assert (await c.post("/api/searches", json={"preset": "nope"})).status_code == 422
        assert (await c.get("/api/searches/missing")).status_code == 404


async def test_saved_defaults_go_to_local_file_only(config_path: Path) -> None:
    before = config_path.read_text()
    local = config_path.with_name("config.local.yaml")
    async with client(config_path) as c:
        r = await c.put("/api/config/defaults", json={"max_nights": 5, "origins": ["VNO"]})
        assert r.status_code == 200 and r.json()["defaults"]["max_nights"] == 5
        assert (await c.put("/api/config/defaults", json={"max_nights": -3})).status_code == 422
        assert (await c.get("/api/config")).json()["defaults"]["max_nights"] == 5  # intact
        assert not list(config_path.parent.glob("*.tmp"))
    assert config_path.read_text() == before and "max_nights: 5" in local.read_text()


async def test_sources_health(config_path: Path) -> None:
    async with client(config_path) as c:
        sources = (await c.get("/api/sources")).json()
    assert {s["source"] for s in sources} == {"ryanair", "wizzair"}
    wizz = next(s for s in sources if s["source"] == "wizzair")
    assert wizz["preferred_rung"] == 4 and "day_flights" not in wizz["capabilities"]


async def test_config_exposes_origins_from_ground_edges(config_path: Path) -> None:
    async with client(config_path) as c:
        assert (await c.get("/api/config")).json()["origins"] == ["KUN", "RIX", "VNO"]
