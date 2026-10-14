import json
from calendar import monthrange
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from cheaphops.core.ctx import Ctx
from cheaphops.core.models import DayFare, Flight
from cheaphops.recipes.base import SchemaMismatch
from cheaphops.skills.timeparse import local_aware

API = "https://www.ryanair.com/api"
# client-version : sans lui, 409 « Availability declined » même dans le navigateur (2026-10-14).
# Il suit les déploiements du site : une dérive ici est un cas typique pour le Medic.
HEADERS = {
    "accept": "application/json, text/plain, */*",
    "client": "desktop",
    "client-version": "3.220.1",
}
# jours de part et d'autre de DateOut : 3 validé en live (6 : 400 InvalidRequestFields)
FLEX = 3
WINDOW = 2 * FLEX + 1


def window_start(day: date) -> date:
    """Fenêtres calées sur le 1er du mois : calendar() et day_flights() demandent les mêmes
    URL, donc le Verify réutilise le cache de l'Explore quand il est assez frais."""
    return day.replace(day=1) + timedelta(days=(day.day - 1) // WINDOW * WINDOW)


def parse_availability(text: str) -> list[Flight]:
    try:
        return list(_flights(json.loads(text)))
    except (KeyError, TypeError, IndexError, ValueError, ValidationError) as e:
        raise SchemaMismatch(f"ryanair availability: {type(e).__name__}: {e}") from e


def _flights(data: Any) -> Iterator[Flight]:
    currency = data["currency"]
    for trip in data["trips"]:
        for day in trip["dates"]:
            for f in day["flights"]:
                fare = f.get("regularFare")  # tarif de base ; absent si le vol est complet
                if not fare or f["faresLeft"] == 0:
                    continue
                adult = next((x for x in fare["fares"] if x["type"] == "ADT"), None)
                if adult is None:
                    raise KeyError("no ADT fare")
                yield Flight(
                    source="ryanair",
                    flight_no=f["flightNumber"].replace(" ", ""),
                    origin=trip["origin"],
                    destination=trip["destination"],
                    departure=local_aware(f["time"][0], f["timeUTC"][0]),
                    arrival=local_aware(f["time"][1], f["timeUTC"][1]),
                    price=Decimal(str(adult["amount"])),
                    currency=currency,
                )


class Recipe:
    async def routes(self, ctx: Ctx, origin: str) -> list[str]:
        url = f"{API}/views/locate/searchWidget/routes/en/airport/{origin}"
        r = await ctx.http.get(url, freshness="explore", headers=HEADERS)
        try:
            return sorted({x["arrivalAirport"]["code"] for x in r.json()})
        except (KeyError, TypeError, ValueError) as e:  # ValueError : corps non JSON
            raise SchemaMismatch(f"ryanair routes: {e}") from e

    async def _window(self, ctx: Ctx, o: str, d: str, start: date, verify: bool) -> list[Flight]:
        params: dict[str, str | int] = {
            "ADT": 1, "TEEN": 0, "CHD": 0, "INF": 0,
            "Origin": o, "Destination": d,
            "IncludeConnectingFlights": "false",
            "DateOut": max(start + timedelta(days=FLEX), ctx.today).isoformat(),
            "FlexDaysBeforeOut": FLEX, "FlexDaysOut": FLEX,
            "FlexDaysBeforeIn": FLEX, "FlexDaysIn": FLEX,
            "RoundTrip": "false", "IncludePrimeFares": "false", "ToUs": "AGREED",
        }  # fmt: skip
        r = await ctx.http.get(
            f"{API}/booking/v4/en-gb/availability",
            params=params,
            headers=HEADERS,
            freshness="verify" if verify else "explore",
        )
        return parse_availability(r.text)

    async def calendar(self, ctx: Ctx, o: str, d: str, month: date) -> list[DayFare]:
        first, days = month.replace(day=1), monthrange(month.year, month.month)[1]
        best: dict[date, Flight] = {}
        starts = (first + timedelta(days=k) for k in range(0, days, WINDOW))
        for start in (s for s in starts if s + timedelta(days=WINDOW) > ctx.today):
            for f in await self._window(ctx, o, d, start, verify=False):
                day = f.departure.date()
                if day.month == month.month and (day not in best or f.price < best[day].price):
                    best[day] = f
        return [
            DayFare(origin=o, destination=d, day=day, price=f.price, currency=f.currency)
            for day, f in sorted(best.items())
        ]

    async def day_flights(self, ctx: Ctx, o: str, d: str, day: date) -> list[Flight]:
        flights = await self._window(ctx, o, d, window_start(day), verify=True)
        return [f for f in flights if f.departure.date() == day]

    def booking_url(self, o: str, d: str, day: date) -> str | None:
        return (
            "https://www.ryanair.com/gb/en/trip/flights/select?adults=1&teens=0&children=0"
            f"&infants=0&isReturn=false&dateOut={day.isoformat()}&originIata={o}&destinationIata={d}"
        )
