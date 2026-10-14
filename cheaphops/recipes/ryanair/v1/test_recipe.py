import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from cheaphops.core.models import Manifest
from cheaphops.fetch.types import HttpRequest
from cheaphops.recipes.base import SchemaMismatch
from cheaphops.recipes.ryanair.v1.recipe import Recipe, parse_availability, window_start
from cheaphops.recipes.testing import FixtureTransport, fixture_ctx

pytestmark = pytest.mark.anyio
HERE = Path(__file__).parent
FIX = HERE / "fixtures"
MANIFEST = Manifest.model_validate(yaml.safe_load((HERE / "manifest.yaml").read_text()))
AVAIL = FIX / "availability_VNO_BGY_2026-11-06.json"


def route(req: HttpRequest) -> Path | None:
    if "/routes/en/airport/VNO" in req.url:
        return FIX / "routes_VNO.json"
    return AVAIL if "/availability" in req.url else None


async def test_routes() -> None:
    routes = await Recipe().routes(fixture_ctx(MANIFEST, FixtureTransport(route)), "VNO")
    assert "BGY" in routes and len(routes) == 19 and routes == sorted(routes)


async def test_calendar_matches_prices_visible_on_rendered_page() -> None:
    transport = FixtureTransport(route)
    fares = await Recipe().calendar(
        fixture_ctx(MANIFEST, transport), "VNO", "BGY", date(2026, 11, 1)
    )
    assert [(f.day, f.price) for f in fares] == [
        (date(2026, 11, 4), Decimal("37.23")),
        (date(2026, 11, 7), Decimal("31.8")),
        (date(2026, 11, 8), Decimal("36.99")),
    ]
    truth = json.loads((FIX / "ground_truth.json").read_text())["visible_prices"]
    visible = sorted(int(p.split()[-1]) for p in truth)
    assert sorted(int(f.price) for f in fares) == visible  # le carrousel affiche l'euro entier
    windows = [r.url for r in transport.sent]
    assert len(windows) == 5 and all("FlexDaysOut=3" in u for u in windows)  # 30 jours / 7


async def test_day_flights_has_aware_local_times_and_reuses_calendar_window() -> None:
    transport = FixtureTransport(route)
    ctx = fixture_ctx(MANIFEST, transport)
    flights = await Recipe().day_flights(ctx, "VNO", "BGY", date(2026, 11, 4))
    assert [(f.flight_no, f.price) for f in flights] == [
        ("FR4236", Decimal("42.47")),
        ("FR2871", Decimal("37.23")),
    ]
    f = flights[0]
    assert f.departure.isoformat() == "2026-11-04T11:25:00+02:00"
    assert f.arrival.utcoffset() == timedelta(hours=1)
    assert "DateOut=2026-11-04" in transport.sent[0].url  # fenêtre 1-7 du mois, centrée le 4


def test_windows_align_on_month_start() -> None:
    assert [window_start(date(2026, 11, d)).day for d in (1, 7, 8, 30)] == [1, 1, 8, 29]


def test_sold_out_flights_skipped() -> None:
    data = json.loads(AVAIL.read_text())
    data["trips"][0]["dates"][0]["flights"][0]["faresLeft"] = 0
    data["trips"][0]["dates"][0]["flights"][1]["regularFare"] = None
    flights = parse_availability(json.dumps(data))
    assert all(f.departure.date() != date(2026, 11, 4) for f in flights)


def test_schema_change_raises_schema_mismatch() -> None:
    data = json.loads(AVAIL.read_text())
    del data["trips"][0]["dates"][0]["flights"][0]["timeUTC"]
    with pytest.raises(SchemaMismatch):
        parse_availability(json.dumps(data))


def test_missing_adult_fare_or_non_json_raises_schema_mismatch() -> None:
    data = json.loads(AVAIL.read_text())
    data["trips"][0]["dates"][0]["flights"][1]["regularFare"]["fares"][0]["type"] = "TEEN"
    with pytest.raises(SchemaMismatch):
        parse_availability(json.dumps(data))
    with pytest.raises(SchemaMismatch):
        parse_availability("<html>maintenance</html>")


async def test_routes_html_body_raises_schema_mismatch(tmp_path: Path) -> None:
    page = tmp_path / "page.html"
    page.write_text("<html>maintenance</html>")
    ctx = fixture_ctx(MANIFEST, FixtureTransport(lambda req: page))
    with pytest.raises(SchemaMismatch):
        await Recipe().routes(ctx, "VNO")


def test_booking_url() -> None:
    url = Recipe().booking_url("VNO", "BGY", date(2026, 11, 4))
    assert url is not None and "dateOut=2026-11-04" in url and "destinationIata=BGY" in url


async def test_calendar_skips_windows_already_past() -> None:
    transport = FixtureTransport(route)
    await Recipe().calendar(fixture_ctx(MANIFEST, transport), "VNO", "BGY", date(2026, 10, 1))
    # 14 octobre : la fenêtre 1-7 est passée ; celle du 8 est centrée sur aujourd'hui
    assert [u.split("DateOut=")[1][:10] for u in (r.url for r in transport.sent)] == [
        "2026-10-14", "2026-10-18", "2026-10-25", "2026-11-01",
    ]  # fmt: skip
