"""Formes de données du moteur de recherche (§9)."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class Quote:
    """Prix minimal d'un jour sur une route (grille Explore), en EUR."""

    source: str
    origin: str
    destination: str
    day: date
    price_eur: Decimal


@dataclass(frozen=True)
class Segment:
    """Un vol. Sans horaires (`departure is None`) si la source ne fournit que des prix au jour."""

    source: str
    origin: str
    destination: str
    day: date
    price_eur: Decimal
    departure: datetime | None = None
    arrival: datetime | None = None
    flight_no: str | None = None
    booking_url: str | None = None
    fetched_at: datetime | None = None

    @property
    def timed(self) -> bool:
        return self.departure is not None


@dataclass(frozen=True)
class GroundLeg:
    origin: str
    destination: str
    duration_min: int
    cost_eur: Decimal


@dataclass(frozen=True)
class Trip:
    outbound: tuple[Segment, ...]
    inbound: tuple[Segment, ...]
    ground: tuple[GroundLeg, ...]
    score: Decimal
    total_eur: Decimal  # vols + sol, sans pénalités
    nights: int
    on_site_hours: float | None  # None : horaires non vérifiés
    badges: tuple[str, ...] = field(default=())

    @property
    def destination(self) -> str:
        return self.outbound[-1].destination
