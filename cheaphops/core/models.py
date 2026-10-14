from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    NaiveDatetime,
    StringConstraints,
    model_validator,
)

Iata = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
# shortcut: refuse un TLD nu mais pas un suffixe public (co.uk, github.io) ; en phase 4
# (Pathfinder), valider via la Public Suffix List (tldextract), pas de liste maison
Domain = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Price = Annotated[Decimal, Field(ge=0)]
Hours = Annotated[float, Field(ge=0)]
Weekday = Annotated[int, Field(ge=0, le=6)]  # lundi = 0, comme date.weekday()


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())


class DayFare(Model):
    origin: Iata
    destination: Iata
    day: date
    price: Price
    currency: Currency


class Flight(Model):
    source: str
    flight_no: str
    origin: Iata
    destination: Iata
    departure: AwareDatetime
    arrival: AwareDatetime
    price: Price
    currency: Currency

    @model_validator(mode="after")
    def _arrives_after_departure(self) -> Self:
        if self.arrival <= self.departure:
            raise ValueError("arrival must be after departure")
        return self


class Blackout(Model):
    """Créneau d'indisponibilité, en heure locale de Vilnius."""

    start: NaiveDatetime
    end: NaiveDatetime

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("blackout end must be after start")
        return self


class Deadline(Model):
    """Arrivée du retour au plus tard à `at` ; si `weekday` est fixé, à ce jour-là
    (prochaine occurrence après le départ), sinon le jour même de l'arrivée."""

    at: time
    weekday: Weekday | None

    def limit_day(self, leave: date) -> date | None:
        """Jour limite du retour pour un départ le jour `leave` (None : le jour de l'arrivée)."""
        if self.weekday is None:
            return None
        return leave + timedelta(days=(self.weekday - leave.weekday()) % 7)


class SearchOptions(Model):
    """Paramètres §4.2 hors fenêtre de dates. Aucun défaut ici : ils vivent dans config.yaml."""

    home: Iata  # là où j'habite : départ et retour de chaque voyage, trajets sol compris
    origins: Annotated[list[Iata], Field(min_length=1)]
    max_nights: Annotated[int, Field(ge=0)]
    min_on_site_hours: Hours
    return_deadline: Deadline | None
    depart_weekdays: list[Weekday] | None
    return_weekdays: list[Weekday] | None
    blackout: list[Blackout]
    max_total_price: Price | None
    allow_self_transfer: bool
    max_stops_per_direction: Annotated[int, Field(ge=0)]
    min_connection_hours: Hours
    max_layover_hours: Hours
    allow_open_jaw: bool
    top_k: Annotated[int, Field(ge=1)]

    def blocked(self, start: datetime, end: datetime) -> bool:
        """Un créneau d'indisponibilité chevauche-t-il [start, end] (heures locales naïves) ?"""
        return any(b.start < end and b.end > start for b in self.blackout)


class SearchParams(SearchOptions):
    date_from: date
    date_to: date

    @model_validator(mode="after")
    def _window(self) -> Self:
        if self.date_to < self.date_from:
            raise ValueError("date_to must not be before date_from")
        return self


class SearchDefaults(SearchOptions):
    start_offset_days: Annotated[int, Field(ge=0)]
    window_days: Annotated[int, Field(ge=1)]

    def params(self, today: date) -> SearchParams:
        fields = self.model_dump(exclude={"start_offset_days", "window_days"})
        start = today + timedelta(days=self.start_offset_days)
        return SearchParams(
            **fields, date_from=start, date_to=start + timedelta(days=self.window_days)
        )


class GroundEdge(Model):
    """Trajet sol bidirectionnel entre deux aéroports d'origine."""

    a: Iata
    b: Iata
    duration_min: Annotated[int, Field(gt=0)]
    cost_eur: Price
    margin_min: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if self.a == self.b:
            raise ValueError("ground edge endpoints must differ")
        return self


class RateLimit(Model):
    min_interval_s: Annotated[float, Field(gt=0)]
    jitter_s: Annotated[float, Field(ge=0)]


class RecipeStatus(StrEnum):
    DRAFT = "draft"
    QUARANTINED = "quarantined"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


Capability = Literal["routes", "calendar", "day_flights", "booking_url"]


class Manifest(Model):
    source: str
    version: Annotated[int, Field(ge=1)]
    capabilities: set[Capability]  # vide pour une source de données hors vols (taux BCE)
    allowed_domains: Annotated[list[Domain], Field(min_length=1)]
    home_url: Annotated[str, StringConstraints(pattern=r"^https://")]  # amorce des rungs 3-4
    block_markers: list[str]  # refus anti-bot propres à la source, en plus de ceux de la config
    headed: bool  # rung 4 en fenêtre visible : certains anti-bots refusent tout navigateur headless
    cookie_headers: dict[str, str]  # en-tête -> cookie à recopier (CSRF double-submit), rung 4
    preferred_rung: Annotated[int, Field(ge=1, le=4)]
    rate_limit: RateLimit
    status: RecipeStatus
