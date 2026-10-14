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
    day: date | None = None  # départ, quand la source le donne
    back: date | None = None  # retour
    airline: str | None = None


@dataclass(frozen=True)
class RoundTrip:
    out: Fare
    back: Fare
    ground: Decimal  # bus du domicile à l'aéroport de départ + de l'aéroport d'arrivée au domicile
    bundled: bool = False  # tarif aller-retour unique (Kayak) : `back.price` vaut 0

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
    outs: list[Fare], backs: list[Fare], max_nights: int, ground: Ground
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
    return sorted(pairs, key=lambda t: (t.total, t.out.departure))


def dedupe(fares: list[Fare]) -> list[Fare]:
    """Un même vol vu par deux requêtes (SmartSearch avec heure, farechart au jour) : on garde
    la version horodatée."""
    best: dict[tuple[str, str, str, date, Decimal], Fare] = {}
    for f in fares:
        k = (f.source, f.origin, f.destination, f.day, f.price)
        if k not in best or (f.departure.time() != datetime.min.time()):
            best[k] = f
    return list(best.values())


def bundled_roundtrips(
    deals: list[Deal], origins: set[str], max_nights: int, ground: Ground
) -> list[RoundTrip]:
    """Bons plans datés (aller-retour à tarif unique) vus comme des aller-retours : le prix est
    porté par l'aller, le retour vaut 0. Hors origines ou hors `max_nights` : ignoré."""
    trips = []
    seen: set[tuple[str, date, date, Decimal, str | None]] = set()
    for d in deals:
        if d.day is None or d.back is None or d.origin not in origins:
            continue
        key = (d.origin, d.day, d.back, d.price, d.airline)
        if key in seen:  # Kayak liste la ville (MIL) et chacun de ses aéroports (BGY) : même offre
            continue
        seen.add(key)
        if not 0 <= (d.back - d.day).days <= max_nights:
            continue
        noon = datetime.combine(d.day, datetime.min.time())
        out = Fare(
            d.source, d.airline or d.source, d.origin, d.destination, noon, d.price, None, d.url
        )
        back_day = datetime.combine(d.back, datetime.min.time())
        back = Fare(d.source, d.airline or d.source, d.destination, d.origin, back_day,
                    Decimal(0), None, d.url)  # fmt: skip
        trips.append(RoundTrip(out, back, ground.get(d.origin, Decimal(0)) * 2, bundled=True))
    return trips


def best_per_destination(trips: list[RoundTrip]) -> list[RoundTrip]:
    """La meilleure combinaison par destination (aéroport d'arrivée de l'aller), triée par total."""
    best: dict[str, RoundTrip] = {}
    for t in sorted(trips, key=lambda t: (t.total, t.out.departure)):
        best.setdefault(t.out.destination, t)
    return sorted(best.values(), key=lambda t: (t.total, t.out.departure))


def by_destination(trips: list[RoundTrip], per: int) -> dict[str, list[RoundTrip]]:
    """Toutes les dates d'une destination (les `per` meilleures), pour l'option « voir tout »."""
    groups: dict[str, list[RoundTrip]] = {}
    for t in sorted(trips, key=lambda t: (t.total, t.out.departure)):
        group = groups.setdefault(t.out.destination, [])
        if len(group) < per:
            group.append(t)
    return groups
