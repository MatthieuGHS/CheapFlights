import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from cheaphops.core.models import Manifest
from cheaphops.fetch.types import HttpRequest
from cheaphops.recipes.base import SchemaMismatch
from cheaphops.recipes.testing import FixtureTransport, fixture_ctx
from cheaphops.recipes.wizzair.v1.recipe import Recipe, parse_farechart

pytestmark = pytest.mark.anyio
HERE = Path(__file__).parent
FIX = HERE / "fixtures"
MANIFEST = Manifest.model_validate(yaml.safe_load((HERE / "manifest.yaml").read_text()))
HOME = "https://www.wizzair.com/en-gb"
CHART = FIX / "farechart_VNO_LTN_2026-11-13.json"


def route(req: HttpRequest) -> Path | None:
    if req.url == HOME:
        return FIX / "home_snippet.html"
    for part, name in (("/asset/map", "map.json"), ("/farechart", CHART.name)):
        if part in req.url:
            return FIX / name
    return None


def bodies(t: FixtureTransport) -> list[dict[str, object]]:
    return [json.loads(r.body) for r in t.sent if r.body]


async def test_routes_are_direct_open_airports() -> None:
    ctx = fixture_ctx(MANIFEST, FixtureTransport(route))
    routes = await Recipe().routes(ctx, "VNO")
    assert "LTN" in routes and "LON" not in routes and routes == sorted(routes)  # LON : ville
    assert await Recipe().routes(ctx, "XXX") == []


async def test_calendar_regular_fares_match_visible_chart_and_keep_real_station() -> None:
    t = FixtureTransport(route)
    fares = await Recipe().calendar(fixture_ctx(MANIFEST, t), "VNO", "LTN", date(2026, 11, 1))
    by_day = {f.day: (f.origin, f.price) for f in fares}
    assert by_day[date(2026, 11, 9)] == ("VNO", Decimal("24.99"))
    assert by_day[date(2026, 11, 11)] == ("KUN", Decimal("31.99"))  # regroupement MAC
    assert date(2026, 11, 10) not in by_day  # « noData »
    visible = json.loads((FIX / "ground_truth.json").read_text())["visible_prices"]
    truth = {p.replace("€", "") for p in visible}
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
    recipe = Recipe()
    await recipe.calendar(ctx, "VNO", "LTN", date(2026, 11, 1))
    back = await recipe.calendar(ctx, "LTN", "VNO", date(2026, 11, 1))
    assert len(t.sent) == 3  # accueil (version) + 2 fenêtres ; le sens retour vient du cache
    assert all(f.origin == "LTN" for f in back)


def test_garbage_raises_schema_mismatch() -> None:
    with pytest.raises(SchemaMismatch):
        parse_farechart("<html>405</html>", "outboundFlights")


async def test_api_version_read_from_home_then_refreshed_on_404(tmp_path: Path) -> None:
    pages = iter(["29.20.1", "29.21.0"])

    def site(req: HttpRequest) -> Path | None:
        if req.url == HOME:
            home = tmp_path / "home.html"
            home.write_text((FIX / "home_snippet.html").read_text().replace("29.20.1", next(pages)))
            return home
        return FIX / "map.json" if "/29.21.0/" in req.url else None  # ancienne version : 404

    t = FixtureTransport(site)
    assert "LTN" in await Recipe().routes(fixture_ctx(MANIFEST, t), "VNO")
    api_calls = [r.url.split("/Api")[0].rsplit("/", 1)[1] for r in t.sent if "/Api" in r.url]
    assert api_calls == ["29.20.1", "29.21.0"]


def test_booking_url() -> None:
    assert Recipe().booking_url("VNO", "LTN", date(2026, 11, 13)) == (
        "https://www.wizzair.com/en-gb/booking/select-flight/VNO/LTN/2026-11-13/null/1/0/0/null"
    )
