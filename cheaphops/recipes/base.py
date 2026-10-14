"""Interface d'une recette (§6), une capacité par Protocol.

Une recette n'implémente que les capacités listées dans `Manifest.capabilities`. Le moteur choisit
les sources d'après ce manifeste, jamais par introspection à l'appel. Les signatures sont garanties
par les tests de contrat de chaque recette ; ces Protocols servent à typer le code appelant.
"""

from datetime import date
from typing import Protocol

from cheaphops.core.ctx import Ctx
from cheaphops.core.models import DayFare, Flight


class Routes(Protocol):
    async def routes(self, ctx: Ctx, origin: str) -> list[str]: ...


class Calendar(Protocol):
    async def calendar(self, ctx: Ctx, o: str, d: str, month: date) -> list[DayFare]: ...


class DayFlights(Protocol):
    async def day_flights(self, ctx: Ctx, o: str, d: str, day: date) -> list[Flight]: ...


class BookingUrl(Protocol):
    def booking_url(self, flight: Flight) -> str | None: ...
