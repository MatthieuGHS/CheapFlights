"""Moteur de bout en bout sur les fixtures Ryanair : Explore, candidats, Verify, sans réseau."""

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

from cheaphops.core.config import load_config, load_ground
from cheaphops.core.db import connect
from cheaphops.core.models import DayFare, Flight, Manifest, SearchParams
from cheaphops.fetch.http import Throttle
from cheaphops.fetch.types import HttpRequest, Transport
from cheaphops.recipes.registry import LoadedRecipe
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


async def test_zero_budget_sends_nothing_and_serves_cache_only() -> None:
    sent: list[HttpRequest] = []

    def route(req: HttpRequest) -> Path | None:
        sent.append(req)
        return FIX / "routes_VNO.json"

    base = load_config(ROOT / "config.yaml", ROOT / "absent.yaml")
    search = base.search.model_copy(update={"request_budget": 0})
    config = base.model_copy(update={"search": search})
    today = date(2026, 10, 14)

    async def no_wait(_: float) -> None:
        pass

    result = await run_search(
        base.search.defaults.params(today), config, load_ground(ROOT / "ground.yaml"),
        connect(":memory:"), today, lambda e: None,
        lambda m: dict.fromkeys((1, 2, 3, 4), FixtureTransport(route)), Throttle(sleep=no_wait),
    )  # fmt: skip
    assert sent == [] and result.requests == 0


class Hops:
    """Recette synthétique : VNO <-> STN en direct, STN <-> DUB ; DUB n'est desservi qu'en
    correspondance à STN. Horaires compatibles avec 3 h de marge self-transfer."""

    ROUTES: ClassVar = {"VNO": ["STN"], "STN": ["DUB", "VNO"], "KUN": [], "RIX": []}
    FLIGHTS: ClassVar = {  # (o, d, jour) -> (départ, arrivée, prix, décalage local)
        ("VNO", "STN", 6): ("06:00", "07:00", 15, (2, 0)),
        ("STN", "DUB", 6): ("11:00", "12:30", 10, (0, 0)),
        ("DUB", "STN", 9): ("09:00", "10:30", 12, (0, 0)),
        ("STN", "VNO", 9): ("15:00", "20:00", 14, (0, 2)),
    }

    async def routes(self, ctx: object, origin: str) -> list[str]:
        return self.ROUTES.get(origin, [])

    async def calendar(self, ctx: object, o: str, d: str, month: date) -> list[Any]:
        return [
            DayFare(
                origin=o, destination=d, day=date(2026, 11, day), price=Decimal(p), currency="EUR"
            )
            for (fo, fd, day), (_, _, p, _) in self.FLIGHTS.items()
            if (fo, fd) == (o, d) and month.month == 11
        ]

    async def day_flights(self, ctx: object, o: str, d: str, day: date) -> list[Flight]:
        found = self.FLIGHTS.get((o, d, day.day))
        if found is None:
            return []
        dep, arr, price, (tz_o, tz_d) = found

        def at(hm: str, tz: int) -> datetime:
            return datetime.fromisoformat(f"{day}T{hm}").replace(
                tzinfo=timezone(timedelta(hours=tz))
            )

        return [Flight(source="hops", flight_no="X1", origin=o, destination=d,
                       departure=at(dep, tz_o), arrival=at(arr, tz_d),
                       price=Decimal(price), currency="EUR")]  # fmt: skip

    def booking_url(self, o: str, d: str, day: date) -> str | None:
        return f"https://hops.example/{o}/{d}/{day}"


async def test_second_level_explore_yields_self_transfer() -> None:
    ryanair = ROOT / "cheaphops/recipes/ryanair/v1/manifest.yaml"
    manifest = Manifest.model_validate(yaml.safe_load(ryanair.read_text()) | {"source": "hops"})
    base = load_config(ROOT / "config.yaml", ROOT / "absent.yaml")
    today = date(2026, 10, 14)
    params = SearchParams.model_validate(
        base.search.defaults.params(today).model_dump()
        | {"date_from": date(2026, 11, 1), "date_to": date(2026, 11, 8)}
    )
    result = await run_search(
        params, base, load_ground(ROOT / "ground.yaml"), connect(":memory:"), today,
        recipes=[LoadedRecipe(manifest, Hops())],
    )  # fmt: skip
    dub = [t for t in result.trips if t.destination == "DUB"]
    assert dub and "self-transfer" in dub[0].badges
    assert [s.destination for s in dub[0].outbound] == ["STN", "DUB"]
    assert result.requests == 0
