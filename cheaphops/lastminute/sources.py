"""Les sources « depuis X vers n'importe où ». Chaque fonction est synchrone (les libs le
sont) et renvoie (tarifs, requêtes envoyées) ; `run` les lance dans des threads."""

import datetime as dt
import json
import logging
import re
from collections.abc import Callable
from decimal import Decimal
from itertools import zip_longest
from typing import Any

from cheaphops.lastminute import cache
from cheaphops.lastminute.fares import Fare, best_per_route
from cheaphops.lastminute.fx import Fx

log = logging.getLogger("cheaphops.lastminute")
API_VERSION = re.compile(r"be\.wizzair\.com\\?/(\d+\.\d+\.\d+)")
FARECHART_RADIUS = 9  # farechart renvoie ±9 jours autour de la date demandée
Pause = Callable[[], None]
RYANAIR_SLICE_DAYS = 10  # oneWayFares ne renvoie que le moins cher par destination sur la plage
WIZZ_HOME = "https://www.wizzair.com/en-gb"
# shortcut: cookie de consentement figé (valeur publique), Google renvoie sinon la page de
# consentement UE ; à régénérer si fast-flights se met à lever IndexError partout
GOOGLE_COOKIES = {"SOCS": "CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg", "CONSENT": "PENDING+987"}
# compagnies déjà couvertes en direct : inutile de les rapatrier depuis Google
COVERED = ("Ryanair", "Wizz")


def ryanair(api: Any, airport: str, d0: dt.date, d1: dt.date) -> list[Fare]:
    """oneWayFares (farfnd, comme ryanair-py) : une requête par aéroport, le moins cher vers
    chaque destination entre d0 et d1 (EUR), avec l'heure d'arrivée que la lib jette.
    `api` est un `ryanair.Ryanair(currency="EUR")` : on garde sa session et ses reprises."""
    params = {
        "departureAirportIataCode": airport,
        "outboundDepartureDateFrom": d0.isoformat(),
        "outboundDepartureDateTo": d1.isoformat(),
        "outboundDepartureTimeFrom": "00:00",
        "outboundDepartureTimeTo": "23:59",
        "currency": "EUR",
    }
    data = cache.get("ryanair", params)  # une réponse en cache ne compte pas dans num_queries
    if data is None:
        data = api._retryable_query(
            "https://services-api.ryanair.com/farfnd/v4/oneWayFares", params
        )
        cache.put(data, "ryanair", params)
    return [
        _ryanair_fare(f, f["departureAirport"]["iataCode"], f["arrivalAirport"]["iataCode"],
                      f["flightNumber"].replace(" ", ""))
        for f in (x["outbound"] for x in data["fares"] or [])
        if _eur(f)
    ]  # fmt: skip


def _eur(f: dict[str, Any]) -> bool:
    return bool(f["price"]["currencyCode"] == "EUR")


def ryanair_calendar(
    api: Any, o: str, d: str, months: list[dt.date], d0: dt.date, last: dt.date, pause: Pause
) -> tuple[list[Fare], int]:
    """Prix par jour de la route o -> d (farfnd `cheapestPerDay`, une requête par mois), jours
    complets ou indisponibles écartés. Prix réels de la compagnie, avec l'heure du vol."""
    fares: list[Fare] = []
    sent = 0
    for month in months:
        data = cache.get("ryanair-calendar", o, d, month)
        if data is None:
            if sent:
                pause()
            sent += 1
            r = api.session.get(
                f"https://services-api.ryanair.com/farfnd/v4/oneWayFares/{o}/{d}/cheapestPerDay",
                params={"outboundMonthOfDate": month.isoformat(), "currency": "EUR"},
            )
            r.raise_for_status()
            data = r.json()
            cache.put(data, "ryanair-calendar", o, d, month)
        for x in data["outbound"]["fares"] or []:
            if x["soldOut"] or x["unavailable"] or not _eur(x):
                continue
            fare = _ryanair_fare(x, o, d)
            if d0 <= fare.day <= last:
                fares.append(fare)
    return fares, sent


def _ryanair_fare(x: dict[str, Any], o: str, d: str, flight_no: str | None = None) -> Fare:
    """Tarif farfnd (oneWayFares ou cheapestPerDay) : prix réel, heures de départ et d'arrivée."""
    when = dt.datetime.fromisoformat(x["departureDate"])
    arrival = x.get("arrivalDate")
    return Fare(
        "ryanair", "Ryanair", o, d, when, Decimal(str(x["price"]["value"])), flight_no,
        "https://www.ryanair.com/gb/en/trip/flights/select?adults=1&teens=0&children=0&infants=0"
        f"&isReturn=false&dateOut={when.date().isoformat()}&originIata={o}&destinationIata={d}",
        arrival=dt.datetime.fromisoformat(arrival) if arrival else None,
    )  # fmt: skip


def farechart_centers(d0: dt.date, last: dt.date) -> list[dt.date]:
    """Dates demandées au farechart pour couvrir d0..last (chacune couvre ±FARECHART_RADIUS)."""
    step = 2 * FARECHART_RADIUS + 1
    return [d0 + dt.timedelta(days=FARECHART_RADIUS + i * step)
            for i in range(-(-((last - d0).days + 1) // step))]  # fmt: skip


def farechart_centers_for(spans: list[tuple[dt.date, dt.date]]) -> list[dt.date]:
    """Centres couvrant des plages triées, sans repayer les jours déjà couverts par le précédent."""
    centers: list[dt.date] = []
    for a, b in spans:
        if centers:
            a = max(a, centers[-1] + dt.timedelta(days=FARECHART_RADIUS + 1))
        if a <= b:
            centers += farechart_centers(a, b)
    return centers


def wizz(
    origins: list[str],
    spans: list[tuple[dt.date, dt.date]],
    max_routes: int,
    pause: Pause,
    fx: Fx,
    routes: list[tuple[str, str]] | None = None,
) -> tuple[list[Fare], int]:
    """Depuis le contexte d'une page Wizz (Kasada accepte le headless furtif de Scrapling) :
    1. SmartSearchCheapFlightsV2 par origine : les destinations desservies (une requête chacune) ;
    2. farechart pour les `max_routes` routes les moins chères : prix par jour, aller et retour
       dans la même réponse (±9 jours autour de la date demandée, donc plusieurs fenêtres si la
       période est longue)."""
    from scrapling.fetchers import StealthyFetcher

    fares: list[Fare] = []
    sent = [1]  # la page elle-même

    version: list[str] = []

    def discover(page: Any) -> None:
        """Version d'API lue dans la page (HTML, puis requêtes que la page a déjà faites)."""
        seen = [page.content(), json.dumps(page.evaluate(
            "performance.getEntriesByType('resource').map(e => e.name)"))]  # fmt: skip
        for text in seen:
            if m := API_VERSION.search(text):
                version[:] = [m.group(1)]
                return
        raise LookupError("wizzair: version d'API introuvable dans la page")

    def post(page: Any, path: str, body: dict[str, Any]) -> str:
        cached = cache.get("wizzair", path, body)
        if cached is not None:
            return str(cached)
        for attempt in range(2):
            if not version:
                discover(page)
            sent[0] += 1
            status, text = page.evaluate(
                "async ([url, b]) => { const r = await fetch(url, {method: 'POST', headers:"
                " {'content-type': 'application/json'}, body: JSON.stringify(b)});"
                " return [r.status, await r.text()] }",
                [f"https://be.wizzair.com/{version[0]}/Api{path}", body],
            )
            pause()
            if status == 404 and attempt == 0:  # déploiement en cours : version relue
                version.clear()
                continue
            if status != 200:
                return ""
            cache.put(str(text), "wizzair", path, body)
            return str(text)
        return ""

    def act(page: Any) -> Any:
        known: dict[tuple[str, str], Decimal] = {}
        for o in [] if routes is not None else origins:
            body = {
                "departureStations": [o], "arrivalStations": None, "stdPlan": None,
                "isReturnFlight": False, "tripDuration": "1 week", "pax": 1,
                "dateFilterType": "Flexible", "departureDate": None, "returnDate": None,
            }  # fmt: skip
            found = parse_wizz(post(page, "/search/SmartSearchCheapFlightsV2", body), fx)
            fares.extend(found)
            for f in found:
                known[(o, f.destination)] = f.price
        cheapest = routes if routes is not None else sorted(known, key=lambda r: known[r])
        cheapest = cheapest[:max_routes]
        for center in farechart_centers_for(spans) if cheapest else []:
            for o, d in cheapest:
                stamp = f"{center.isoformat()}T00:00:00"
                fc: dict[str, Any] = {
                    "isRescueFare": False, "adultCount": 1, "childCount": 0,
                    "dayInterval": FARECHART_RADIUS, "wdc": False, "isFlightChange": False,
                    "flightList": [
                        {"departureStation": o, "arrivalStation": d, "date": stamp},
                        {"departureStation": d, "arrivalStation": o, "date": stamp},
                    ],
                }  # fmt: skip
                fares.extend(parse_farechart(post(page, "/asset/farechart", fc), fx))
        return page

    StealthyFetcher.fetch(
        WIZZ_HOME, headless=True, network_idle=True, page_action=act, timeout=120_000
    )
    return [f for f in fares if any(a <= f.day <= b for a, b in spans)], sent[0]


def _wizz_url(o: str, d: str, day: str) -> str:
    return f"https://www.wizzair.com/en-gb/booking/select-flight/{o}/{d}/{day}/null/1/0/0/null"


def parse_farechart(text: str, fx: Fx) -> list[Fare]:
    """Prix par jour des deux sens ; « noData » : pas de vol ce jour-là. Avec le regroupement MAC
    (VNO/KUN), la station réelle du vol est celle de la réponse."""
    try:
        data = json.loads(text)
        legs = (data["outboundFlights"] or []) + (data["returnFlights"] or [])
        fares = []
        for x in legs:
            price = x["price"]
            eur = fx.to_eur(Decimal(str(price["amount"])), price["currencyCode"])
            if x["priceType"] != "price" or eur is None:
                continue
            o, d, day = x["departureStation"], x["arrivalStation"], x["date"][:10]
            fares.append(Fare(
                "wizzair", "Wizz Air", o, d, dt.datetime.fromisoformat(day),
                eur, None, _wizz_url(o, d, day),
            ))  # fmt: skip
        return fares
    except (ValueError, KeyError, TypeError):
        return []


def parse_wizz(text: str, fx: Fx) -> list[Fare]:
    try:
        items = json.loads(text)["items"]
    except (ValueError, KeyError, TypeError):
        return []
    fares = []
    for it in items:
        f = it["outboundFlight"]
        price = f["regularPrice"]  # `wdcPrice` est le tarif club, réservé aux abonnés
        eur = fx.to_eur(Decimal(str(price["amount"])), price["currencyCode"])
        if eur is None:
            continue
        o, d, when = f["departureStation"], f["arrivalStation"], f["std"][:10]
        fares.append(Fare(
            "wizzair", "Wizz Air", o, d, dt.datetime.fromisoformat(f["std"]),
            eur, None, _wizz_url(o, d, when),
        ))  # fmt: skip
    return fares


def google(
    origins: list[str], destinations: list[str], days: list[dt.date], pause: Pause
) -> tuple[list[Fare], int]:
    """fast-flights : une requête par (origine, destination, jour), vols directs hors Ryanair
    et Wizz. Sans « n'importe où » côté Google, c'est un échantillon de hubs, pas une carte."""
    from fast_flights import FlightQuery, create_query
    from fast_flights.integrations.base import FetchIntegration
    from fast_flights.parser import parse
    from primp import Client

    class Consent(FetchIntegration):
        def __init__(self) -> None:
            self.client = Client(
                impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True
            )

        def fetch_html(self, q: Any, /) -> str:
            url = "https://www.google.com/travel/flights"
            return str(self.client.get(url, params=q.params(), cookies=GOOGLE_COOKIES).text)

    fetcher, fares, sent = Consent(), [], 0
    for o in origins:
        for d in destinations:
            if d == o:  # une cible qui est aussi une origine
                continue
            for day in days:
                q = create_query(
                    flights=[FlightQuery(date=day.isoformat(), from_airport=o, to_airport=d,
                                         max_stops=0)],
                    currency="EUR", language="en",
                )  # fmt: skip
                html = cache.get("google", o, d, day)
                if html is None:
                    if sent:
                        pause()
                    sent += 1
                    html = fetcher.fetch_html(q)
                try:
                    results = parse(html)
                    cache.put(html, "google", o, d, day)  # seulement une page qui se lit
                except Exception as e:  # une route sans résultat ne doit pas tuer la source
                    log.info("google %s-%s %s: %s", o, d, day, type(e).__name__)
                    continue
                fares += [f for r in results if (f := _google_fare(r, o, d, q.url()))]
    return fares, sent


def _google_fare(r: Any, o: str, d: str, url: str) -> Fare | None:
    airline = ", ".join(r.airlines)
    if not r.flights or any(c in airline for c in COVERED):
        return None
    dep = r.flights[0].departure
    when = dt.datetime(*dep.date, *dep.time)
    return Fare("google", airline, o, d, when, Decimal(r.price), None, url, True)


AIRBALTIC = "https://www.airbaltic.com"


def airbaltic(
    origins: list[str], aim: list[str], spans: list[tuple[dt.date, dt.date]], budget: int,
    pause: Pause,
) -> tuple[list[Fare], int]:  # fmt: skip
    """API du site (GET publics, sans navigateur) : les routes directes (orig-dest), puis le prix
    de chaque jour sur un an, une requête par route et par sens. Allers de toutes les routes,
    puis retours des moins chères, dans `budget` requêtes."""
    from primp import Client

    client, sent = Client(impersonate="chrome_145", impersonate_os="windows"), [0]

    def get(path: str, **params: str) -> Any:
        data = cache.get("airbaltic", path, params)
        if data is None:
            if sent[0]:
                pause()
            sent[0] += 1
            data = json.loads(client.get(f"{AIRBALTIC}/api/{path}", params=params).text)
            cache.put(data, "airbaltic", path, params)
        return data

    def days(o: str, d: str) -> list[Fare]:
        data = get("fsf/outbound", flightMode="oneway", origin=o, destin=d)
        return [f for f in parse_airbaltic(data, o, d) if any(a <= f.day <= b for a, b in spans)]

    routes = airbaltic_routes(get("orig-dest/en"), origins, aim)
    room = budget - sent[0]
    outs = [f for o, d in routes[:room] for f in days(o, d)]
    cheapest = best_per_route(outs)[: max(budget - sent[0], 0)]
    backs = [b for f in cheapest for b in days(f.destination, f.origin)]
    return outs + backs, sent[0]


def airbaltic_routes(od: Any, origins: list[str], aim: list[str]) -> list[tuple[str, str]]:
    """(origine, destination) des vols directs airBaltic, les origines servies à tour de rôle (un
    budget court ne doit pas tout donner à RIX)."""
    by_origin: dict[str, list[str]] = {o: [] for o in origins}
    for key, v in od["destinData"].items():
        d = key[:-1]  # « CPHA » : code + type (A : aéroport)
        if not key.endswith("A") or d in origins or (aim and d not in aim):
            continue
        for o in origins:
            if (v["btDest"].get(o + "A") or v["nonBtDest"].get(o + "A") or {}).get("hasBTDirect"):
                by_origin[o].append(d)
    rounds = zip_longest(*([(o, d) for d in ds] for o, ds in by_origin.items()))
    return [r for group in rounds for r in group if r]


def parse_airbaltic(data: Any, o: str, d: str) -> list[Fare]:
    """Prix au jour (sans heure) ; null : pas de vol. « isDirect » faux : escale airBaltic à Riga,
    même billet."""
    if not data.get("success"):  # route inconnue : {"success": false, "error": ...}
        return []
    fares = []
    for x in data.get("data") or []:
        price = x.get("updatedPrice") or x["price"]
        if price:
            url = (f"{AIRBALTIC}/en/book-flight?originCode={o}&destinCode={d}&originType=A"
                   f"&destinType=A&tripType=oneway&departure={x['date']}&numAdt=1")  # fmt: skip
            fares.append(Fare("airbaltic", "airBaltic", o, d, dt.datetime.fromisoformat(x["date"]),
                              Decimal(str(price)), None, url))  # fmt: skip
    return fares


KIWI = "https://api.skypicker.com/umbrella/v2/graphql"
# Ryanair, Malta Air, Buzz, Lauda, Ryanair UK et Wizz (Hongrie, UK, Malte) : déjà lus en direct
KIWI_COVERED = ["FR", "AL", "RR", "OE", "RK", "W6", "W9", "W4"]
_KIWI_ARGS = (
    "($search: SearchOnewayInput, $filter: ItinerariesFilterInput,"
    " $options: ItinerariesOptionsInput)"
)
_KIWI_IN = "(search: $search, filter: $filter, options: $options)"
_KIWI_END = "station { code city { slug } } localTime"
_KIWI_ERR = "__typename ... on AppError { error: message }"
KIWI_PER_CITY = (
    f"query OnePerCity{_KIWI_ARGS} {{ onewayOnePerCityItineraries{_KIWI_IN} {{ {_KIWI_ERR}"
    " ... on OnePerCityItineraries { itineraries { ... on OnewayOnePerCityItinerary {"
    f" price {{ amount }} source {{ {_KIWI_END} }} destination {{ {_KIWI_END} }} }} }} }} }} }}"
)
KIWI_ONEWAY = (
    f"query OneWay{_KIWI_ARGS} {{ onewayItineraries{_KIWI_IN} {{ {_KIWI_ERR}"
    " ... on Itineraries { itineraries { ... on ItineraryOneWay { price { amount }"
    " sector { sectorSegments { segment {"
    f" source {{ {_KIWI_END} }} destination {{ {_KIWI_END} }} carrier {{ code name }} code"
    " } } } } } } } }"
)


def kiwi(
    origins: list[str], aim: list[str], spans: list[tuple[dt.date, dt.date]], returns: int,
    pause: Pause,
) -> tuple[list[Fare], int]:  # fmt: skip
    """GraphQL de kiwi.com (sans jeton ni navigateur), prix indicatifs. Par plage : n'importe où,
    le moins cher par ville, puis le retour des `returns` destinations les moins chères ; en mode
    cibles, aller et retour vers chaque cible. Ryanair et Wizz sont exclus : lus en direct."""
    from primp import Client

    client, sent = Client(impersonate="chrome_145", impersonate_os="windows"), [0]

    def ask(query: str, src: list[str], dst: list[str], a: dt.date, b: dt.date) -> list[Any]:
        var = _kiwi_vars(src, dst, a, b)
        data = cache.get("kiwi", query, var)
        if data is None:
            if sent[0]:
                pause()
            sent[0] += 1
            r = client.post(KIWI, json={"query": query, "variables": var},
                            headers={"origin": "https://www.kiwi.com"})  # fmt: skip
            data = json.loads(r.text)["data"]
            cache.put(data, "kiwi", query, var)
        node = next(iter(data.values()))
        if "itineraries" not in node:  # AppError : cette requête seulement
            log.info("kiwi %s -> %s : %s", src, dst, node.get("error"))
            return []
        return list(node["itineraries"])

    home = [f"Station:airport:{o}" for o in origins]
    fares: list[Fare] = []
    for a, b in spans:
        for t in aim:
            there = [f"Station:airport:{t}"]
            fares += [parse_kiwi(x) for x in ask(KIWI_ONEWAY, home, there, a, b)]
            fares += [parse_kiwi(x) for x in ask(KIWI_ONEWAY, there, home, a, b)]
        if aim:
            continue
        found = [parse_kiwi_city(x) for x in ask(KIWI_PER_CITY, home, ["anywhere"], a, b)]
        fares += found
        dests = [f.destination for f in sorted(found, key=lambda f: f.price)
                 if f.destination not in origins]  # fmt: skip
        for d in list(dict.fromkeys(dests))[:returns]:
            fares += [parse_kiwi(x) for x in ask(KIWI_ONEWAY, [f"Station:airport:{d}"], home, a, b)]
    return fares, sent[0]


def _kiwi_vars(src: list[str], dst: list[str], a: dt.date, b: dt.date) -> dict[str, Any]:
    return {
        "search": {
            "itinerary": {
                "source": {"ids": src}, "destination": {"ids": dst},
                "outboundDepartureDate": {"start": f"{a}T00:00:00", "end": f"{b}T23:59:59"},
            },
            "passengers": {"adults": 1, "children": 0, "infants": 0, "adultsHoldBags": [0],
                           "adultsHandBags": [0], "childrenHoldBags": [], "childrenHandBags": []},
            "cabinClass": {"cabinClass": "ECONOMY", "applyMixedClasses": False},
        },
        "filter": {
            "allowChangeInboundDestination": True, "allowChangeInboundSource": True,
            "allowDifferentStationConnection": False, "enableSelfTransfer": True,
            "enableThrowAwayTicketing": False, "enableTrueHiddenCity": False,
            "transportTypes": ["FLIGHT"], "contentProviders": ["KIWI"], "limit": 100,
            "excludeCarriers": KIWI_COVERED,
        },
        "options": {"sortBy": "PRICE", "currency": "eur", "locale": "en", "partner": "skypicker",
                    "market": "fr", "partnerMarket": "fr", "storeSearch": False},
    }  # fmt: skip


def _kiwi_url(src: Any, dst: Any, day: dt.date) -> str:
    """Page de résultats du jour : stable, contrairement au lien de réservation (jeton)."""
    a, b = src["station"]["city"]["slug"], dst["station"]["city"]["slug"]
    return f"https://www.kiwi.com/en/search/results/{a}/{b}/{day}/no-return"


def parse_kiwi_city(x: Any) -> Fare:
    """Le moins cher vers une ville : sans compagnie (Kiwi ne la donne pas ici)."""
    s, d = x["source"], x["destination"]
    dep = dt.datetime.fromisoformat(s["localTime"])
    return Fare("kiwi", "Kiwi.com", s["station"]["code"], d["station"]["code"], dep,
                Decimal(x["price"]["amount"]), None, _kiwi_url(s, d, dep.date()), True,
                dt.datetime.fromisoformat(d["localTime"]))  # fmt: skip


def parse_kiwi(x: Any) -> Fare:
    """Un itinéraire vendu par Kiwi, direct ou avec escale (un seul achat chez Kiwi)."""
    segs = [s["segment"] for s in x["sector"]["sectorSegments"]]
    first, end = segs[0], segs[-1]
    dep = dt.datetime.fromisoformat(first["source"]["localTime"])
    airline = " + ".join(dict.fromkeys(s["carrier"]["name"] for s in segs))
    flight = f"{first['carrier']['code']}{first['code']}" if len(segs) == 1 else None
    return Fare("kiwi", airline, first["source"]["station"]["code"],
                end["destination"]["station"]["code"], dep, Decimal(x["price"]["amount"]), flight,
                _kiwi_url(first["source"], end["destination"], dep.date()), True,
                dt.datetime.fromisoformat(end["destination"]["localTime"]))  # fmt: skip
