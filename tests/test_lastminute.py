import asyncio
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from cheaphops.core.config import Ground, load_config
from cheaphops.lastminute import generic, sources
from cheaphops.lastminute import run as run_mod
from cheaphops.lastminute.fares import (
    Bus,
    Deal,
    Fare,
    best_per_destination,
    bundled_roundtrips,
    by_destination,
    cheapest_oneways,
    roundtrips,
)
from cheaphops.lastminute.fx import Fx

FX = Fx({"PLN": Decimal("4.25")})
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
    got = roundtrips([out], [late, wrong_dest, ok], 3, {})
    assert [(t.back, t.total, t.nights) for t in got] == [(ok, Decimal("35"), 3)]


def test_same_day_return_needs_a_gap() -> None:
    out = fare("VNO", "BGY", "2026-10-20", "20", hour=6)
    soon = fare("BGY", "VNO", "2026-10-20", "5", hour=9)
    later = fare("BGY", "VNO", "2026-10-20", "5", hour=18)
    assert [t.back for t in roundtrips([out], [soon, later], 3, {})] == [later]


def test_roundtrips_sorted_by_total() -> None:
    o1, o2 = fare("VNO", "BGY", "2026-10-20", "50"), fare("KUN", "BGY", "2026-10-20", "10")
    back = fare("BGY", "VNO", "2026-10-21", "10")
    assert [t.total for t in roundtrips([o1, o2], [back], 3, {})] == [20, 60]


def test_parse_wizz_keeps_regular_eur_price_and_ignores_garbage() -> None:
    def item(cur: str) -> dict[str, object]:
        price = {"amount": 55.99, "currencyCode": cur}
        return {"outboundFlight": {
            "departureStation": "VNO", "arrivalStation": "AGP", "std": "2026-10-25T06:00:00",
            "regularPrice": price, "wdcPrice": {"amount": 45.99, "currencyCode": cur},
        }}  # fmt: skip

    got = sources.parse_wizz(json.dumps({"items": [item("EUR"), item("PLN"), item("XXX")]}), FX)
    assert [(f.origin, f.price, f.departure.hour) for f in got] == [
        ("VNO", Decimal("55.99"), 6),
        ("VNO", Decimal("13.17"), 6),  # PLN converti ; la devise inconnue est écartée
    ]
    assert sources.parse_wizz("<html>Kasada</html>", FX) == []
    assert sources.parse_wizz('{"items": []}', FX) == []


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
    got = sources.parse_farechart(text, FX)
    assert [(f.origin, f.destination, f.day.isoformat(), f.price) for f in got] == [
        ("VNO", "AGP", "2026-10-20", Decimal("40.5")),
        ("AGP", "KUN", "2026-10-23", Decimal(30)),
        ("AGP", "KUN", "2026-10-24", Decimal("2.12")),
    ]
    assert sources.parse_farechart("blocked", FX) == []


def test_bus_is_information_only_never_added_to_totals_or_ranking() -> None:
    bus = {"KUN": Bus(Decimal(10), 100), "RIX": Bus(Decimal(15), 270)}
    a = fare("VNO", "BGY", "2026-10-20", "20")
    b = fare("KUN", "BGY", "2026-10-20", "12")  # moins cher, malgré 10 € de bus
    assert cheapest_oneways([a, b], 2) == [b, a]
    back = fare("BGY", "RIX", "2026-10-22", "10")
    (t,) = roundtrips([b], [back], 3, bus)
    assert t.total == Decimal(22)  # 12 + 10 : vols seulement
    assert (t.bus.cost, t.bus.minutes) == (Decimal(25), 370)  # affiché à part


PATTERN = (
    r"^(?P<origin>[^,]+),.*? to (?P<destination>[^,]+),.*?(?:only|from)\s+"
    r"(?P<price>[€$£]\s?[0-9][0-9.,]*(?:\s[A-Z]{3}\b)?)"
)
SF = generic.Source.model_validate({
    "name": "sf", "urls": ["https://x"], "cities": {"Vilnius": "VNO", "Riga": "RIX"},
    "extract": {"kind": "selectors", "item": "article", "fields": {}, "pattern": PATTERN},
})  # fmt: skip
FX2 = Fx({"CAD": Decimal("1.6"), "USD": Decimal("1.1"), "PLN": Decimal("4.25")})


def test_parse_money_handles_symbols_codes_and_separators() -> None:
    pm = generic.parse_money
    assert pm("€66") == (Decimal(66), "EUR")
    assert pm("$663 CAD") == (Decimal(663), "CAD")
    assert pm("$663") == (Decimal(663), "USD")
    assert pm("1 299 zł") == (Decimal(1299), "PLN")
    assert pm("1,299.50 EUR") == (Decimal("1299.50"), "EUR")
    assert pm("49,90 EUR") == (Decimal("49.90"), "EUR")
    assert pm("rien") is None


def test_generic_titles_convert_currency_and_keep_only_known_origins() -> None:
    rows = [
        {"title": "Vilnius, Lithuania to Reykjavik, Iceland for only €66 roundtrip", "url": "u1"},
        {"title": "Vilnius, Lithuania to Toronto, Canada from only $160 CAD one-way", "url": "u2"},
        {"title": "Toronto, Canada to Vilnius, Lithuania for only $663 CAD roundtrip", "url": "u3"},
        {"title": "Riga, Latvia to Oslo, Norway for only $55", "url": "u4"},
        {"title": "Vilnius, Lithuania to Oslo, Norway for only ¥50", "url": "u5"},
    ]
    got, no_fares = generic.deals_from_rows(SF, rows, FX2)
    assert no_fares == []
    assert [(d.origin, d.destination, d.price) for d in got] == [
        ("VNO", "Reykjavik", Decimal("66.00")),
        ("VNO", "Toronto", Decimal("100.00")),
        ("RIX", "Oslo", Decimal("50.00")),
    ]


def test_generic_rss_rows_then_pattern_on_description() -> None:
    xml = b"""<rss><channel><item><title>Deal alert</title><link>https://x/1</link>
    <description>Riga, Latvia to Rome, Italy for only \xe2\x82\xac39 return</description></item>
    </channel></rss>"""
    rows = generic.rows_from_rss(xml)
    ((d,), _) = generic.deals_from_rows(SF, rows, FX2)
    assert (d.origin, d.destination, d.price, d.url) == (
        "RIX",
        "Rome",
        Decimal("39.00"),
        "https://x/1",
    )


def test_generic_json_mapping_follows_dotted_paths() -> None:
    src = SF.model_copy(update={"extract": generic.JsonTap(
        kind="json", response_url_contains="deals", items="data.0.deals", currency="PLN",
        fields={"origin": "from", "destination": "to.code", "price": "p", "url": "link",
                "when": "month"},
    )})  # fmt: skip
    payload = {"data": [{"deals": [
        {"from": "Vilnius", "to": {"code": "BGY"}, "p": 85, "link": "l1", "month": "nov"},
        {"from": "Riga", "to": {}, "p": 5, "link": "l2"},  # destination absente : ignoré
    ]}]}  # fmt: skip
    (d,) = generic.deals_from_json(src, payload, FX2)
    assert (d.origin, d.destination, d.price, d.when) == ("VNO", "BGY", Decimal("20.00"), "nov")


def test_fx_cache_is_reused_within_24h(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from cheaphops.lastminute import fx as fx_mod

    cache = tmp_path / "fx.json"
    cache.write_text(json.dumps({"at": 1000, "rates": {"PLN": "4.0"}}))
    fresh = fx_mod.load_fx(cache, now=1000 + 3600)  # pas de réseau : le cache sert
    assert fresh.to_eur(Decimal(8), "PLN") == Decimal("2.00")
    assert fx_mod.parse_ecb("<Cube currency='USD' rate='1.1'/>") == {"USD": Decimal("1.1")}


def test_best_per_destination_and_all_dates() -> None:
    outs = [
        fare("VNO", "BGY", "2026-10-20", "20"),
        fare("VNO", "BGY", "2026-10-22", "30"),
        fare("VNO", "ATH", "2026-10-21", "25"),
    ]
    backs = [fare("BGY", "VNO", "2026-10-23", "10"), fare("ATH", "VNO", "2026-10-23", "9")]
    trips = roundtrips(outs, backs, 3, {})
    assert [(t.out.destination, t.total) for t in best_per_destination(trips)] == [
        ("BGY", Decimal(30)),
        ("ATH", Decimal(34)),
    ]
    assert [t.total for t in by_destination(trips, 5)["BGY"]] == [30, 40]


def test_dated_deal_becomes_a_bundled_roundtrip_in_the_same_ranking() -> None:
    deal = Deal(
        "kayak-explore", "VNO -> BGY", "VNO", "BGY", Decimal("33.05"), "https://k/1",
        None, date(2026, 11, 6), date(2026, 11, 9), "Ryanair",
    )  # fmt: skip
    far = Deal("k", "VNO -> X", "VNO", "XXX", Decimal(10), "u", None, date(2026, 11, 6),
               date(2026, 11, 20), None)  # fmt: skip
    twin = Deal(
        "kayak-explore", "VNO -> MIL", "VNO", "MIL", Decimal("33.05"), "https://k/2",
        None, date(2026, 11, 6), date(2026, 11, 9), "Ryanair",
    )  # fmt: skip
    trips = bundled_roundtrips([deal, twin, far], {"VNO"}, 3, {"VNO": Bus(Decimal(0), 0)})
    assert [(t.total, t.nights, t.bundled) for t in trips] == [(Decimal("33.05"), 3, True)]
    pair = roundtrips([fare("VNO", "ATH", "2026-11-06", "20")],
                      [fare("ATH", "VNO", "2026-11-08", "15")], 3, {})  # fmt: skip
    ranked = best_per_destination([*pair, *trips])
    assert [t.out.destination for t in ranked] == ["BGY", "ATH"]  # 33,05 < 35


def test_run_pairs_all_sources_and_only_fetches_missing_returns(monkeypatch) -> None:  # type: ignore[no-untyped-def]
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
        return [fare("ATH", "VNO", "2026-10-17", "12")]

    def fake_wizz(*args):  # type: ignore[no-untyped-def]
        # le retour BGY->VNO vient de Wizz : BGY est couverte, seule ATH reste à chercher
        return [fare("BGY", "VNO", "2026-10-17", "9", src="wizzair")], 3

    monkeypatch.setattr(sources, "ryanair", fake_ry)
    monkeypatch.setattr(sources, "wizz", fake_wizz)
    monkeypatch.setattr(sources, "google", lambda *a: ([], 0))
    monkeypatch.setattr(generic, "load_sources", lambda: [])
    monkeypatch.setattr(run_mod, "Ryanair", lambda currency: SimpleNamespace(num_queries=0))
    ground = Ground.model_validate({"home": "VNO", "buses": {}})

    r = asyncio.run(run_mod.run(cfg, ground, date(2026, 10, 14), fx=FX))
    assert queried == ["ATH"]
    assert r.requests <= 40
    assert [(t.out.destination, t.total) for t in r.roundtrips] == [
        ("BGY", Decimal(29)),
        ("ATH", Decimal(57)),
    ]
    assert set(r.alternatives) == {"BGY", "ATH"}


def test_teztour_fixture_yields_dated_oneway_charters() -> None:
    from pathlib import Path

    from scrapling.parser import Selector

    src = next(s for s in generic.load_sources() if s.name == "teztour")
    assert isinstance(src.extract, generic.Selectors)
    page = Selector(
        (Path(__file__).parent / "fixtures/web/teztour.html").read_text(),
        url="https://www.teztour.lt/x",
    )
    deals, fares = generic.deals_from_rows(src, generic.page_rows(src, src.extract, page), FX2)
    assert deals == [] and len(fares) == 3
    f = fares[0]
    assert (f.origin, f.destination, f.price, f.source) == (
        "VNO",
        "HER",
        Decimal("69.00"),
        "teztour",
    )
    assert (
        f.departure.hour == 6 and f.url and f.url.startswith("https://www.teztour.lt/flightsearch/")
    )


def test_fly4free_com_feed_titles() -> None:
    src = next(s for s in generic.load_sources() if s.name == "fly4free-com")
    items = [
        "Etihad Airways flights from Vilnius to South Korea 🍁 from €585",
        "Finnair flights from the Baltic countries to Singapore from €563",
        "Cheap first minute flights from Riga, Latvia to spectacular Faroe Islands 🏔 for €208",
        "Thailand classics from Warsaw 🌴 Bangkok + Krabi — all flights for just €515 total",
        "Top-rated 4🌟 Eurostars Metropole in Riga, Latvia for €50/double",
    ]
    xml = "<rss><channel>" + "".join(
        f"<item><title>{t}</title><link>https://f4f/{i}</link></item>" for i, t in enumerate(items)
    ) + "</channel></rss>"  # fmt: skip
    deals, fares = generic.deals_from_rows(src, generic.rows_from_rss(xml.encode()), FX2)
    assert fares == []
    assert [(d.origin, d.destination, d.price) for d in deals] == [
        ("VNO", "South Korea", Decimal("585.00")),
        ("RIX", "spectacular Faroe Islands", Decimal("208.00")),
    ]


def test_azair_fixture_gives_both_legs_with_airline_and_booking_link() -> None:
    from pathlib import Path

    from scrapling.parser import Selector

    src = next(s for s in generic.load_sources() if s.name == "azair")
    assert isinstance(src.extract, generic.Selectors)
    html = (Path(__file__).parent / "fixtures/web/azair.html").read_text()
    page = Selector(html, url="https://www.azair.eu/azfin.php")
    _, fares = generic.deals_from_rows(src, generic.page_rows(src, src.extract, page), FX2)
    assert len(fares) == 4  # 2 résultats x (aller + retour)
    out, back = fares[0], fares[1]
    assert (out.origin, out.destination, out.airline) == ("VNO", "NUE", "Ryanair")
    assert out.departure.hour == 12 and out.price == Decimal("21.99")
    assert (back.origin, back.destination) == ("NUE", "VNO") and back.day > out.day
    assert out.url and out.url.startswith("https://www.azair.eu/book/b.php")


def test_kayak_explore_json_gives_dated_round_trips_converted_to_eur() -> None:
    src = next(s for s in generic.load_sources() if s.name == "kayak-explore")
    payload = {"destinations": [
        {"originAirportCode": "VNO", "airport": {"iata": "BGY"}, "dateDepart": "2026-11-28",
         "dateReturn": "2026-11-30", "airline": "Ryanair", "clickoutUrl": "/flights/VNO-BGY/",
         "flightInfo": {"localePrice": {"price": 55.0, "currency": "USD"}}},
        {"originAirportCode": "VNO", "airport": {"iata": "XXX"}, "clickoutUrl": "/x/",
         "flightInfo": {"localePrice": {"price": 10, "currency": "ZZZ"}}},  # devise inconnue
    ]}  # fmt: skip
    (d,) = generic.deals_from_json(src, payload, FX2)
    assert (d.origin, d.destination, d.price, d.airline) == (
        "VNO",
        "BGY",
        Decimal("50.00"),
        "Ryanair",
    )
    assert (d.day, d.back) == (date(2026, 11, 28), date(2026, 11, 30))
    assert d.url == "https://www.kayak.com/flights/VNO-BGY/"
    assert d.when == "2026-11-28 -> 2026-11-30"


def test_dedupe_keeps_the_timed_version_of_the_same_flight() -> None:
    from cheaphops.lastminute.fares import dedupe

    day_only = fare("VNO", "TLL", "2026-11-06", "19.99", hour=0, src="wizzair")
    timed = fare("VNO", "TLL", "2026-11-06", "19.99", hour=6, src="wizzair")
    other = fare("VNO", "TLL", "2026-11-06", "24.99", hour=0, src="wizzair")
    assert dedupe([day_only, timed, other]) == [timed, other]
    assert dedupe([timed, day_only]) == [timed]
