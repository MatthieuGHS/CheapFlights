"""Les trois sources « depuis X vers n'importe où ». Chaque fonction est synchrone (les libs le
sont) et renvoie (tarifs, requêtes envoyées) ; `run` les lance dans des threads."""

import datetime as dt
import json
import logging
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from cheaphops.lastminute.fares import Fare
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
    """oneWayFares de ryanair-py : une requête par aéroport, le moins cher vers chaque
    destination entre d0 et d1 (EUR). `api` est un `ryanair.Ryanair(currency="EUR")`."""
    return [_ryanair_fare(f) for f in api.get_cheapest_flights(airport, d0, d1)
            if f.currency == "EUR"]  # fmt: skip


def ryanair_calendar(
    api: Any, o: str, d: str, months: list[dt.date], d0: dt.date, last: dt.date, pause: Pause
) -> tuple[list[Fare], int]:
    """Prix par jour de la route o -> d (farfnd `cheapestPerDay`, une requête par mois), jours
    complets ou indisponibles écartés. Prix réels de la compagnie, avec l'heure du vol."""
    fares: list[Fare] = []
    for i, month in enumerate(months):
        if i:
            pause()
        r = api.session.get(
            f"https://services-api.ryanair.com/farfnd/v4/oneWayFares/{o}/{d}/cheapestPerDay",
            params={"outboundMonthOfDate": month.isoformat(), "currency": "EUR"},
        )
        r.raise_for_status()
        for x in r.json()["outbound"]["fares"] or []:
            if x["soldOut"] or x["unavailable"] or x["price"]["currencyCode"] != "EUR":
                continue
            when = dt.datetime.fromisoformat(x["departureDate"])
            if d0 <= when.date() <= last:
                day = when.date().isoformat()
                fares.append(Fare(
                    "ryanair", "Ryanair", o, d, when, Decimal(str(x["price"]["value"])), None,
                    "https://www.ryanair.com/gb/en/trip/flights/select?adults=1&teens=0"
                    f"&children=0&infants=0&isReturn=false&dateOut={day}&originIata={o}"
                    f"&destinationIata={d}",
                ))  # fmt: skip
    return fares, len(months)


def _ryanair_fare(f: Any) -> Fare:
    day = f.departureTime.date().isoformat()
    return Fare(
        "ryanair", "Ryanair", f.origin, f.destination, f.departureTime, Decimal(str(f.price)),
        f.flightNumber.replace(" ", ""),
        "https://www.ryanair.com/gb/en/trip/flights/select?adults=1&teens=0&children=0&infants=0"
        f"&isReturn=false&dateOut={day}&originIata={f.origin}&destinationIata={f.destination}",
    )  # fmt: skip


def wizz(
    origins: list[str],
    d0: dt.date,
    d1: dt.date,
    nights: int,
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
            return str(text) if status == 200 else ""
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
        center = d0 + dt.timedelta(days=FARECHART_RADIUS)
        while cheapest and center - dt.timedelta(days=FARECHART_RADIUS) <= d1 + dt.timedelta(
            nights
        ):
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
            center += dt.timedelta(days=2 * FARECHART_RADIUS + 1)
        return page

    StealthyFetcher.fetch(
        WIZZ_HOME, headless=True, network_idle=True, page_action=act, timeout=120_000
    )
    last = d1 + dt.timedelta(days=nights)
    return [f for f in fares if d0 <= f.day <= last], sent[0]


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
            for day in days:
                if sent:
                    pause()
                sent += 1
                q = create_query(
                    flights=[FlightQuery(date=day.isoformat(), from_airport=o, to_airport=d,
                                         max_stops=0)],
                    currency="EUR", language="en",
                )  # fmt: skip
                try:
                    results = parse(fetcher.fetch_html(q))
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
