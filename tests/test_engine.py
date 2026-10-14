"""Moteur de bout en bout sur les fixtures Ryanair : Explore, candidats, Verify, sans réseau."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from cheaphops.core.config import load_config, load_ground
from cheaphops.core.db import connect
from cheaphops.core.models import Manifest, SearchParams
from cheaphops.fetch.http import Throttle
from cheaphops.fetch.types import HttpRequest, Transport
from cheaphops.recipes.testing import FixtureTransport
from cheaphops.search.engine import Event, run_search

pytestmark = pytest.mark.anyio
ROOT = Path(__file__).parent.parent
FIX = ROOT / "cheaphops/recipes/ryanair/v1/fixtures"


@pytest.fixture
def back_fixture(tmp_path: Path) -> Path:
    """Retour BGY -> VNO synthétique : la capture aller, sens inversé."""
    data = json.loads((FIX / "availability_VNO_BGY_2026-11-06.json").read_text())
    trip = data["trips"][0]
    trip["origin"], trip["destination"] = "BGY", "VNO"
    for day in trip["dates"]:
        for f in day["flights"]:
            for s in f["segments"]:
                s["origin"], s["destination"] = "BGY", "VNO"
    path = tmp_path / "back.json"
    path.write_text(json.dumps(data))
    return path


async def test_search_on_fixtures_respects_constraints(back_fixture: Path) -> None:
    def route(req: HttpRequest) -> Path | None:
        if "/routes/en/airport/VNO" in req.url:
            return FIX / "routes_VNO.json"
        if "/availability" in req.url and "Origin=VNO" in req.url and "Destination=BGY" in req.url:
            return FIX / "availability_VNO_BGY_2026-11-06.json"
        if "/availability" in req.url and "Origin=BGY" in req.url:
            return back_fixture
        return None  # autres routes : 404, signalées puis ignorées

    def transports(m: Manifest) -> dict[int, Transport]:
        return dict.fromkeys((1, 2, 3, 4), FixtureTransport(route))

    base = load_config(ROOT / "config.yaml", ROOT / "absent.yaml")
    search = base.search.model_copy(update={"sources": ["ryanair"], "request_budget": 10_000})
    config = base.model_copy(update={"search": search})
    today = date(2026, 10, 14)
    params = SearchParams.model_validate(
        base.search.defaults.params(today).model_dump()
        | {"origins": ["VNO"], "date_from": date(2026, 11, 1), "date_to": date(2026, 11, 8)}
    )
    events: list[Event] = []

    async def no_wait(_: float) -> None:
        pass

    result = await run_search(
        params, config, load_ground(ROOT / "ground.yaml"), connect(":memory:"), today,
        events.append, transports, Throttle(sleep=no_wait),
    )  # fmt: skip

    assert result.trips, events
    assert [t.score for t in result.trips] == sorted(t.score for t in result.trips)
    for t in result.trips:
        out, ret = t.outbound[0], t.inbound[0]
        assert (out.origin, out.destination, ret.destination) == ("VNO", "BGY", "VNO")
        assert out.departure and out.arrival and ret.departure
        assert ret.departure - out.arrival >= timedelta(hours=params.min_on_site_hours)
        assert t.nights <= params.max_nights and out.booking_url
    assert {e["type"] for e in events} >= {"explore", "candidates", "progress", "done"}
