from datetime import date
from typing import Protocol

from cheaphops.core.ctx import Ctx
from cheaphops.core.models import DayFare, Flight


class Recipe(Protocol):
    """Interface §6. `Manifest.capabilities` déclare les méthodes réellement prises en charge."""

    async def routes(self, ctx: Ctx, origin: str) -> list[str]: ...
    async def calendar(self, ctx: Ctx, o: str, d: str, month: date) -> list[DayFare]: ...
    async def day_flights(self, ctx: Ctx, o: str, d: str, day: date) -> list[Flight]: ...
    def booking_url(self, flight: Flight) -> str | None: ...
