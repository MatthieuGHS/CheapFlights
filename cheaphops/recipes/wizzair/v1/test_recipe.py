import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from cheaphops.core.models import Manifest
from cheaphops.fetch.types import HttpRequest
from cheaphops.recipes.base import SchemaMismatch
from cheaphops.recipes.testing import FixtureTransport, fixture_ctx
from cheaphops.recipes.wizzair.v1.recipe import Recipe, parse_farechart, parse_search

pytestmark = pytest.mark.anyio
HERE = Path(__file__).parent
FIX = HERE / "fixtures"
MANIFEST = Manifest.model_validate(yaml.safe_load((HERE / "manifest.yaml").read_text()))
CHART = FIX / "farechart_VNO_LTN_2026-11-13.json"
SEARCH = FIX / "search_VNO_LTN_2026-11-13.json"


def route(req: HttpRequest) -> Path | None:
    for part, path in (
        ("/asset/map", "map.json"),
        ("/farechart", CHART.name),
        ("/search/", SEARCH.name),
    ):
        if part in req.url:
            return FIX / path
    return None


def bodies(t: FixtureTransport) -> list[dict[str, object]]:
    return [json.loads(r.body or b"{}") for r in t.sent]


async def test_routes_are_direct_and_already_open() -> None:
    routes = await Recipe().routes(fixture_ctx(MANIFEST, FixtureTransport(route)), "VNO")
    assert "LTN" in routes and "LON" not in routes and routes == sorted(routes)
    assert await Recipe().routes(fixture_ctx(MANIFEST, FixtureTransport(route)), "XXX") == []


async def test_calendar_regular_fares_match_visible_chart_and_keep_real_station() -> None:
    t = FixtureTransport(route)
    fares = await Recipe().calendar(fixture_ctx(MANIFEST, t), "VNO", "LTN", date(2026, 11, 1))
    by_day = {f.day: (f.origin, f.price) for f in fares}
    assert by_day[date(2026, 11, 9)] == ("VNO", Decimal("24.99"))
    assert by_day[date(2026, 11, 11)] == ("KUN", Decimal("31.99"))  # regroupement MAC
    assert date(2026, 11, 10) not in by_day  # « noData »
    truth = {
        p.replace("€", "")
        for p in json.loads((FIX / "ground_truth.json").read_text())["visible_prices"]
    }
    chart = {str(f.price) for f in fares}
    assert {
        "49.99",
        "31.99",
        "29.99",
    } <= truth & chart  # affichés par la page et lus par la recette
    assert all(b["wdc"] is False and b["dayInterval"] == 9 for b in bodies(t))


async def test_both_directions_share_one_request_body() -> None:
    t = FixtureTransport(route)
    ctx = fixture_ctx(MANIFEST, t)
    await Recipe().calendar(ctx, "VNO", "LTN", date(2026, 11, 1))
    back = await Recipe().calendar(ctx, "LTN", "VNO", date(2026, 11, 1))
    assert len(t.sent) == 2  # le sens retour est servi par le cache
    assert all(f.origin == "LTN" for f in back)


async def test_day_flights_regular_basic_fare_plus_admin_fee() -> None:
    t = FixtureTransport(route)
    flights = await Recipe().day_flights(fixture_ctx(MANIFEST, t), "VNO", "LTN", date(2026, 11, 13))
    assert [(f.flight_no, f.origin, f.price) for f in flights] == [
        ("W61901", "VNO", Decimal("123.99")),
        ("W95450", "KUN", Decimal("78.99")),  # Wizz Air UK
    ]
    assert flights[0].departure.isoformat() == "2026-11-13T05:55:00+02:00"
    assert flights[0].arrival.utcoffset() == timedelta(0)
    assert bodies(t)[0]["wdc"] is False


def test_missing_regular_fare_or_garbage_raises_schema_mismatch() -> None:
    data = json.loads(SEARCH.read_text())
    for f in data["outboundFlights"][0]["fares"]:
        f["isWdc"] = True
    with pytest.raises(SchemaMismatch):
        parse_search(json.dumps(data))
    with pytest.raises(SchemaMismatch):
        parse_farechart("<html>405</html>", "outboundFlights")


def test_sold_out_skipped() -> None:
    data = json.loads(SEARCH.read_text())
    for f in data["outboundFlights"][0]["fares"]:
        f["soldOut"] = True
    assert "W61901" not in [f.flight_no for f in parse_search(json.dumps(data))]


def test_booking_url() -> None:
    f = parse_search(SEARCH.read_text())[0]
    assert Recipe().booking_url(f) == (
        "https://www.wizzair.com/en-gb/booking/select-flight/VNO/LTN/2026-11-13/null/1/0/0/null"
    )
