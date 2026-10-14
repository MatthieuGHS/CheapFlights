import json
from calendar import monthrange
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from cheaphops.core.ctx import Ctx
from cheaphops.core.models import DayFare, Flight
from cheaphops.recipes.base import SchemaMismatch
from cheaphops.skills.timeparse import with_offset

# La version de l'API suit les déploiements du site : une dérive ici est un cas typique du Medic.
API = "https://be.wizzair.com/29.20.1/Api"
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


def parse_search(text: str) -> list[Flight]:
    try:
        return list(_flights(json.loads(text)))
    except PARSE_ERRORS as e:
        raise SchemaMismatch(f"wizzair search: {type(e).__name__}: {e}") from e


def _flights(data: Any) -> Iterator[Flight]:
    for f in (data["outboundFlights"] or []) + (data["returnFlights"] or []):
        basic = [x for x in f["fares"] if x["bundle"] == "basic" and not x["isWdc"]]
        if not basic:
            raise KeyError("no regular basic fare")
        fare = basic[0]
        if fare["soldOut"]:
            continue
        # tarif normal (pas Discount Club) + frais de dossier, obligatoires à la réservation
        price = Decimal(str(fare["basePrice"]["amount"])) + Decimal(
            str(fare["administrationFeePrice"]["amount"])
        )
        yield Flight(
            source="wizzair",
            flight_no=f"{f['carrierCode']}{f['flightNumber'].strip()}",
            origin=f["departureStation"],
            destination=f["arrivalStation"],
            departure=with_offset(f["departureDateTime"], f["departureTimeUtcOffset"]),
            arrival=with_offset(f["arrivalDateTime"], f["arrivalTimeUtcOffset"]),
            price=price,
            currency=fare["basePrice"]["currencyCode"],
        )


class Recipe:
    async def routes(self, ctx: Ctx, origin: str) -> list[str]:
        r = await ctx.http.get(
            f"{API}/asset/map", params={"languageCode": "en-gb"}, freshness="explore"
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
            r = await ctx.http.post(
                f"{API}/asset/farechart", json=body, headers=HEADERS, freshness="explore"
            )
            leg = "outboundFlights" if (a, b) == (o, d) else "returnFlights"
            for fare in parse_farechart(r.text, leg):
                if fare.day.month == month.month and (
                    fare.day not in best or fare.price < best[fare.day].price
                ):
                    best[fare.day] = fare
        return [best[day] for day in sorted(best)]

    async def day_flights(self, ctx: Ctx, o: str, d: str, day: date) -> list[Flight]:
        body = {
            "isFlightChange": False,
            "flightList": [
                {"departureStation": o, "arrivalStation": d, "departureDate": f"{day}T00:00:00"}
            ],
            "adultCount": 1, "childCount": 0, "infantCount": 0, "wdc": False,
        }  # fmt: skip
        r = await ctx.http.post(
            f"{API}/search/search", json=body, headers=HEADERS, freshness="verify"
        )
        return [f for f in parse_search(r.text) if f.departure.date() == day]

    def booking_url(self, flight: Flight) -> str | None:
        return (
            f"https://www.wizzair.com/en-gb/booking/select-flight/{flight.origin}/"
            f"{flight.destination}/{flight.departure.date().isoformat()}/null/1/0/0/null"
        )
