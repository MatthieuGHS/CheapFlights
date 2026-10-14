import json
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from cheaphops.core.ctx import Ctx
from cheaphops.core.models import DayFare
from cheaphops.fetch.http import FetchFailed
from cheaphops.fetch.types import FetchResult
from cheaphops.recipes.base import SchemaMismatch

HOME = "https://www.wizzair.com/en-gb"
# La version de l'API (« 29.20.1 » en octobre 2026) change à chaque déploiement : elle est lue
# dans le HTML de l'accueil, puis relue quand l'API répond 404.
API_VERSION = re.compile(r"be\.wizzair\.com\\?/(\d+\.\d+\.\d+)")
HEADERS = {"accept": "application/json, text/plain, */*", "content-type": "application/json"}
DAY_INTERVAL = 9  # farechart renvoie ±9 jours autour de la date demandée
WINDOW = 2 * DAY_INTERVAL + 1
ROUTE_HORIZON = timedelta(days=180)  # liaisons annoncées mais pas encore ouvertes : ignorées
PARSE_ERRORS = (KeyError, TypeError, IndexError, ValueError, ValidationError)


def _day(iso: str) -> date:
    return datetime.fromisoformat(iso).date()


def _pair(o: str, d: str) -> tuple[str, str]:
    """Ordre canonique : calendar(o, d) et calendar(d, o) envoient le même corps, donc un seul
    appel (servi par le cache ensuite) donne les deux sens."""
    return (o, d) if o > d else (d, o)


def parse_farechart(text: str, leg: str) -> list[DayFare]:
    """`leg` : `outboundFlights` (1er trajet de flightList) ou `returnFlights` (2e)."""
    try:
        return [
            DayFare(
                origin=x["departureStation"],
                destination=x["arrivalStation"],
                day=_day(x["date"]),
                price=Decimal(str(x["price"]["amount"])),
                currency=x["price"]["currencyCode"],
            )
            for x in json.loads(text)[leg] or []
            if x["priceType"] == "price"  # « noData » : pas de vol ce jour-là
        ]
    except PARSE_ERRORS as e:
        raise SchemaMismatch(f"wizzair farechart: {type(e).__name__}: {e}") from e


class Recipe:
    """Pas de `day_flights` : l'endpoint `search` (horaires) renvoie un défi Kasada à tout
    navigateur automatisé. Wizz ne fournit que des prix au jour (voir DEBT.md, piste timetable)."""

    def __init__(self) -> None:
        self._version: str | None = None

    async def _api_base(self, ctx: Ctx, refresh: bool) -> str:
        if self._version is None or refresh:
            home = await ctx.http.get(HOME, freshness="none" if refresh else "explore")
            found = API_VERSION.search(home.text)
            if found is None:
                raise SchemaMismatch("wizzair: API version not found on home page")
            self._version = found.group(1)
        return f"https://be.wizzair.com/{self._version}/Api"

    async def _call(self, ctx: Ctx, path: str, **kwargs: Any) -> FetchResult:
        """GET, ou POST si `json` est fourni ; sur 404, la version est relue puis l'appel rejoué."""
        for refresh in (False, True):
            url = await self._api_base(ctx, refresh) + path
            try:
                if "json" in kwargs:
                    return await ctx.http.post(url, headers=HEADERS, **kwargs)
                return await ctx.http.get(url, **kwargs)
            except FetchFailed as e:
                if refresh or e.result is None or e.result.status != 404:
                    raise
        raise AssertionError("unreachable")

    async def routes(self, ctx: Ctx, origin: str) -> list[str]:
        r = await self._call(
            ctx, "/asset/map", params={"languageCode": "en-gb"}, freshness="explore"
        )
        try:
            cities = r.json()["cities"]
            airports = {c["iata"] for c in cities if not c["isFakeStation"]}  # LON, MIL : villes
            city = next(c for c in cities if c["iata"] == origin)
            horizon = ctx.today + ROUTE_HORIZON
            return sorted(
                c["iata"]
                for c in city["connections"]
                if c["isDirectFlight"]
                and c["iata"] in airports
                and _day(c["operationStartDate"]) <= horizon
            )
        except StopIteration:
            return []  # Wizz ne dessert pas cet aéroport
        except PARSE_ERRORS as e:
            raise SchemaMismatch(f"wizzair map: {type(e).__name__}: {e}") from e

    async def calendar(self, ctx: Ctx, o: str, d: str, month: date) -> list[DayFare]:
        """Prix minimal par jour dans le sens o -> d. Avec le regroupement MAC, un jour peut
        porter l'autre aéroport de la zone (KUN pour VNO) : la vraie station est conservée."""
        first, days = month.replace(day=1), monthrange(month.year, month.month)[1]
        a, b = _pair(o, d)
        best: dict[date, DayFare] = {}
        for k in range(0, days, WINDOW):
            center = max(first + timedelta(days=k + DAY_INTERVAL), ctx.today)
            if center - timedelta(days=DAY_INTERVAL) > first.replace(day=days):
                continue
            stamp = f"{center.isoformat()}T00:00:00"
            body = {
                "isRescueFare": False, "adultCount": 1, "childCount": 0,
                "dayInterval": DAY_INTERVAL, "wdc": False, "isFlightChange": False,
                "flightList": [
                    {"departureStation": a, "arrivalStation": b, "date": stamp},
                    {"departureStation": b, "arrivalStation": a, "date": stamp},
                ],
            }  # fmt: skip
            r = await self._call(ctx, "/asset/farechart", json=body, freshness="explore")
            leg = "outboundFlights" if (a, b) == (o, d) else "returnFlights"
            for fare in parse_farechart(r.text, leg):
                if fare.day.month == month.month and (
                    fare.day not in best or fare.price < best[fare.day].price
                ):
                    best[fare.day] = fare
        return [best[day] for day in sorted(best)]

    def booking_url(self, o: str, d: str, day: date) -> str | None:
        return f"https://www.wizzair.com/en-gb/booking/select-flight/{o}/{d}/{day}/null/1/0/0/null"
