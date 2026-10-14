"""Un tarif d'aller simple et l'assemblage pur (sans réseau) des aller-retours."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

SAME_DAY_GAP = timedelta(hours=6)  # retour le jour même : les horaires d'arrivée manquent
Ground = dict[str, Decimal]  # aéroport -> bus aller simple depuis le domicile


@dataclass(frozen=True)
class Fare:
    source: str  # ryanair | wizzair | google
    airline: str
    origin: str
    destination: str
    departure: datetime  # heure locale naïve, ou minuit si la source ne donne que le jour
    price: Decimal  # EUR
    flight_no: str | None
    url: str | None

    @property
    def day(self) -> date:
        return self.departure.date()


@dataclass(frozen=True)
class Deal:
    """Bon plan d'un site : prix et trajet en texte, souvent sans date précise."""

    source: str
    title: str
    origin: str
    destination: str
    price: Decimal
    url: str
    when: str | None = None  # date ou période, telle que la source la donne


@dataclass(frozen=True)
class RoundTrip:
    out: Fare
    back: Fare
    ground: Decimal  # bus du domicile à l'aéroport de départ + de l'aéroport d'arrivée au domicile

    @property
    def total(self) -> Decimal:
        return self.out.price + self.back.price + self.ground

    @property
    def nights(self) -> int:
        return (self.back.day - self.out.day).days


def cheapest_oneways(fares: list[Fare], top: int, ground: Ground) -> list[Fare]:
    """Le moins cher par (origine, destination, jour), bus compris pour le classement : une
    même ligne vue par deux sources ne compte qu'une fois."""
    best: dict[tuple[str, str, date], Fare] = {}
    for f in fares:
        k = (f.origin, f.destination, f.day)
        if k not in best or f.price < best[k].price:
            best[k] = f
    ranked = sorted(best.values(), key=lambda f: (f.price + ground.get(f.origin, 0), f.departure))
    return ranked[:top]


def roundtrips(
    outs: list[Fare], backs: list[Fare], max_nights: int, top: int, ground: Ground
) -> list[RoundTrip]:
    """Deux allers simples quelconques : compagnies différentes, retour vers un autre aéroport
    d'origine (open-jaw côté maison) acceptés. Même aéroport de destination à l'aller et au
    retour, retour au plus `max_nights` nuits après l'aller. `outs` part des origines, `backs`
    arrive aux origines."""
    pairs = [
        RoundTrip(o, b, ground.get(o.origin, Decimal(0)) + ground.get(b.destination, Decimal(0)))
        for o in outs
        for b in backs
        if o.destination == b.origin
        and 0 <= (b.day - o.day).days <= max_nights
        and (b.day > o.day or b.departure - o.departure >= SAME_DAY_GAP)
    ]
    return sorted(pairs, key=lambda t: (t.total, t.out.departure))[:top]
