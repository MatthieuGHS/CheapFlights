import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from cheaphops.core.config import load_config
from cheaphops.lastminute import run as run_mod
from cheaphops.lastminute import sources
from cheaphops.lastminute.fares import Fare, cheapest_oneways, roundtrips

HOME = {"VNO", "KUN", "RIX"}


def fare(o: str, d: str, day: str, price: str, hour: int = 8, src: str = "ryanair") -> Fare:
    when = datetime.fromisoformat(day) + timedelta(hours=hour)
    return Fare(src, src, o, d, when, Decimal(price), None, f"u/{o}{d}{day}")


def test_cheapest_oneways_dedupes_same_line_across_sources() -> None:
    a, b = (
        fare("VNO", "BGY", "2026-10-20", "30"),
        fare("VNO", "BGY", "2026-10-20", "25", src="google"),
    )
    c = fare("VNO", "ATH", "2026-10-21", "40")
    assert cheapest_oneways([a, b, c], 10) == [b, c]
    assert cheapest_oneways([a, b, c], 1) == [b]


def test_roundtrip_mixes_airlines_and_open_jaw_within_nights() -> None:
    out = fare("VNO", "BGY", "2026-10-20", "20")
    ok = fare("BGY", "RIX", "2026-10-23", "15", src="wizzair")  # autre compagnie, autre maison
    late = fare("BGY", "VNO", "2026-10-24", "5")  # 4 nuits
    wrong_dest = fare("MXP", "VNO", "2026-10-22", "5")
    not_home = fare("BGY", "WAW", "2026-10-22", "5")
    got = roundtrips([out], [late, wrong_dest, not_home, ok], HOME, 3, 10)
    assert [(t.back, t.total, t.nights) for t in got] == [(ok, Decimal("35"), 3)]


def test_same_day_return_needs_a_gap() -> None:
    out = fare("VNO", "BGY", "2026-10-20", "20", hour=6)
    soon = fare("BGY", "VNO", "2026-10-20", "5", hour=9)
    later = fare("BGY", "VNO", "2026-10-20", "5", hour=18)
    assert [t.back for t in roundtrips([out], [soon, later], HOME, 3, 10)] == [later]


def test_roundtrips_sorted_by_total() -> None:
    o1, o2 = fare("VNO", "BGY", "2026-10-20", "50"), fare("KUN", "BGY", "2026-10-20", "10")
    back = fare("BGY", "VNO", "2026-10-21", "10")
    assert [t.total for t in roundtrips([o1, o2], [back], HOME, 3, 10)] == [20, 60]


def test_parse_wizz_keeps_regular_eur_price_and_ignores_garbage() -> None:
    def item(cur: str) -> dict[str, object]:
        price = {"amount": 55.99, "currencyCode": cur}
        return {"outboundFlight": {
            "departureStation": "VNO", "arrivalStation": "AGP", "std": "2026-10-25T06:00:00",
            "regularPrice": price, "wdcPrice": {"amount": 45.99, "currencyCode": cur},
        }}  # fmt: skip

    got = sources.parse_wizz(json.dumps({"items": [item("EUR"), item("PLN")]}))
    assert [(f.origin, f.destination, f.price, f.departure.hour) for f in got] == [
        ("VNO", "AGP", Decimal("55.99"), 6)
    ]
    assert sources.parse_wizz("<html>Kasada</html>") == []
    assert sources.parse_wizz('{"items": []}') == []


def test_run_respects_budget_and_survives_a_dead_source(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    today = date(2026, 10, 14)
    cfg = load_config().lastminute.model_copy(update={"request_budget": 20, "return_candidates": 2})
    calls = {"google": 0}

    def fake_ry(api, airport, d0, d1):  # type: ignore[no-untyped-def]
        api.num_queries += 1
        if airport in HOME:
            return [fare(airport, "BGY", "2026-10-15", "20")]
        return [fare("BGY", "VNO", "2026-10-17", "12")]

    def dead_wizz(searches):  # type: ignore[no-untyped-def]
        raise RuntimeError("Kasada")

    def fake_google(origins, dests, days):  # type: ignore[no-untyped-def]
        calls["google"] = len(origins) * len(dests) * len(days)
        return [], calls["google"]

    monkeypatch.setattr(sources, "ryanair", fake_ry)
    monkeypatch.setattr(sources, "wizz", dead_wizz)
    monkeypatch.setattr(sources, "google", fake_google)
    import ryanair

    monkeypatch.setattr(ryanair, "Ryanair", lambda currency: SimpleNamespace(num_queries=0))

    import asyncio

    r = asyncio.run(run_mod.run(cfg, today))
    assert r.sources["wizzair"].error and not r.sources["ryanair"].error
    assert r.requests <= 20
    assert [t.total for t in r.roundtrips][:1] == [Decimal("32")]
