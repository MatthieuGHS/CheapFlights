import asyncio
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from cheaphops.core.config import Ground, load_config
from cheaphops.lastminute import generic, sources
from cheaphops.lastminute import run as run_mod
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
    assert cheapest_oneways([a, b, c], 10, {}) == [b, c]
    assert cheapest_oneways([a, b, c], 1, {}) == [b]


def test_roundtrip_mixes_airlines_and_open_jaw_within_nights() -> None:
    out = fare("VNO", "BGY", "2026-10-20", "20")
    ok = fare("BGY", "RIX", "2026-10-23", "15", src="wizzair")  # autre compagnie, autre maison
    late = fare("BGY", "VNO", "2026-10-24", "5")  # 4 nuits
    wrong_dest = fare("MXP", "VNO", "2026-10-22", "5")
    got = roundtrips([out], [late, wrong_dest, ok], 3, 10, {})
    assert [(t.back, t.total, t.nights) for t in got] == [(ok, Decimal("35"), 3)]


def test_same_day_return_needs_a_gap() -> None:
    out = fare("VNO", "BGY", "2026-10-20", "20", hour=6)
    soon = fare("BGY", "VNO", "2026-10-20", "5", hour=9)
    later = fare("BGY", "VNO", "2026-10-20", "5", hour=18)
    assert [t.back for t in roundtrips([out], [soon, later], 3, 10, {})] == [later]


def test_roundtrips_sorted_by_total() -> None:
    o1, o2 = fare("VNO", "BGY", "2026-10-20", "50"), fare("KUN", "BGY", "2026-10-20", "10")
    back = fare("BGY", "VNO", "2026-10-21", "10")
    assert [t.total for t in roundtrips([o1, o2], [back], 3, 10, {})] == [20, 60]


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


def test_parse_farechart_keeps_priced_days_of_both_directions() -> None:
    def day(o: str, d: str, date_: str, kind: str, amount: float, cur: str = "EUR") -> dict:  # type: ignore[type-arg]
        return {"departureStation": o, "arrivalStation": d, "date": f"{date_}T00:00:00+01:00",
                "priceType": kind, "price": {"amount": amount, "currencyCode": cur}}  # fmt: skip

    text = json.dumps({
        "outboundFlights": [day("VNO", "AGP", "2026-10-20", "price", 40.5),
                            day("VNO", "AGP", "2026-10-21", "noData", 0)],
        "returnFlights": [day("AGP", "KUN", "2026-10-23", "price", 30),
                          day("AGP", "KUN", "2026-10-24", "price", 9, "PLN")],
    })  # fmt: skip
    got = sources.parse_farechart(text)
    assert [(f.origin, f.destination, f.day.isoformat(), f.price) for f in got] == [
        ("VNO", "AGP", "2026-10-20", Decimal("40.5")),
        ("AGP", "KUN", "2026-10-23", Decimal(30)),
    ]
    assert sources.parse_farechart("blocked") == []


def test_ground_cost_is_added_and_reorders() -> None:
    bus = {"KUN": Decimal(10), "RIX": Decimal(15)}
    a = fare("VNO", "BGY", "2026-10-20", "20")
    b = fare("KUN", "BGY", "2026-10-20", "12")  # 12 + 10 bus > 20
    assert cheapest_oneways([a, b], 2, bus) == [a, b]
    back = fare("BGY", "RIX", "2026-10-22", "10")
    (t,) = roundtrips([b], [back], 3, 5, bus)
    assert (t.ground, t.total) == (Decimal(25), Decimal(47))


PATTERN = r"^(?P<origin>[^,]+),.*? to (?P<destination>[^,]+),.*?€(?P<price>[0-9.,]+)"
SF = generic.Source.model_validate({
    "name": "sf", "urls": ["https://x"], "mode": "fetcher",
    "cities": {"Vilnius": "VNO", "Riga": "RIX"},
    "extract": {"kind": "selectors", "item": "article", "fields": {},
                "pattern": PATTERN},
})  # fmt: skip


def test_generic_titles_keep_only_known_origins_and_euro_prices() -> None:
    rows = [
        {"title": "Vilnius, Lithuania to Reykjavik, Iceland for only €66 roundtrip", "url": "u1"},
        {"title": "Toronto, Canada to Vilnius, Lithuania for only $663 CAD roundtrip", "url": "u2"},
        {"title": "Riga, Latvia to Rome, Italy for only €1,5 roundtrip", "url": "u3"},
        {"title": "Vilnius, Lithuania to Oslo, Norway for only £50", "url": "u4"},
    ]
    got = generic.deals_from_titles(SF, rows)
    assert [(d.origin, d.destination, d.price) for d in got] == [
        ("VNO", "Reykjavik", Decimal(66)),
        ("RIX", "Rome", Decimal("1.5")),
    ]


def test_generic_json_mapping_follows_dotted_paths() -> None:
    src = SF.model_copy(update={"extract": generic.JsonTap(
        kind="json", response_url_contains="deals", items="data.0.deals",
        fields={"origin": "from", "destination": "to.code", "price": "p", "url": "link",
                "when": "month"},
    )})  # fmt: skip
    payload = {"data": [{"deals": [
        {"from": "Vilnius", "to": {"code": "BGY"}, "p": 19.9, "link": "l1", "month": "nov"},
        {"from": "Riga", "to": {}, "p": 5, "link": "l2"},  # destination absente : ignoré
    ]}]}  # fmt: skip
    (d,) = generic.deals_from_json(src, payload)
    assert (d.origin, d.destination, d.price, d.when) == ("VNO", "BGY", Decimal("19.9"), "nov")


def test_run_threshold_budget_and_dead_source(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cfg = load_config().lastminute.model_copy(update={"request_budget": 40, "pause_s": (0, 0)})
    queried: list[str] = []

    def fake_ry(api, airport, d0, d1):  # type: ignore[no-untyped-def]
        api.num_queries += 1
        if airport in HOME:
            return [
                fare(airport, "BGY", "2026-10-15", "20"),
                fare(airport, "ATH", "2026-10-15", "45"),
            ]
        queried.append(airport)
        return [fare("BGY", "VNO", "2026-10-17", "12")]

    def dead_wizz(*args):  # type: ignore[no-untyped-def]
        raise RuntimeError("Kasada")

    monkeypatch.setattr(sources, "ryanair", fake_ry)
    monkeypatch.setattr(sources, "wizz", dead_wizz)
    monkeypatch.setattr(sources, "google", lambda *a: ([], 0))
    monkeypatch.setattr(generic, "load_sources", lambda: [])
    monkeypatch.setattr(run_mod, "Ryanair", lambda currency: SimpleNamespace(num_queries=0))
    ground = Ground.model_validate({"home": "VNO", "buses": {}})

    r = asyncio.run(run_mod.run(cfg, ground, date(2026, 10, 14)))
    assert queried == ["BGY"]  # ATH à 45 € dépasse le seuil de 30 €
    assert r.sources["wizzair"].error and not r.sources["ryanair"].error
    assert r.requests <= 40
    assert r.roundtrips[0].total == Decimal("32")
