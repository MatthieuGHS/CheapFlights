"""Composition horaire (§9) : enchaîner des vols réels en sens, puis en voyages.

Le graphe temporel est implicite : un nœud est (aéroport, instant), une arête un vol ou un
trajet sol. On n'énumère que les chemins d'un candidat, donc quelques dizaines de vols au plus.
"""

import itertools
from datetime import datetime, time, timedelta
from decimal import Decimal

from cheaphops.core.config import Penalties
from cheaphops.core.models import SearchParams
from cheaphops.search.candidates import deadline_day
from cheaphops.search.model import GroundLeg, Segment, Trip

NIGHT = (time(1), time(5))  # une escale qui couvre ce créneau local est une nuit en aéroport
UNTIMED_BADGE = "horaires et aéroport de départ à vérifier"


def _hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


def chains(per_leg: list[list[Segment]], params: SearchParams) -> list[tuple[Segment, ...]]:
    """Suites d'un vol par tronçon dont chaque correspondance respecte la marge minimale
    (self-transfer : aucune protection) et l'escale maximale."""
    found: list[tuple[Segment, ...]] = [(s,) for s in per_leg[0]]
    for options in per_leg[1:]:
        found = [(*c, s) for c in found for s in options if _connects(c[-1], s, params)]
    return found


def _connects(a: Segment, b: Segment, params: SearchParams) -> bool:
    if a.arrival is None or b.departure is None:
        return False
    gap = _hours(b.departure - a.arrival)
    return params.min_connection_hours <= gap <= params.max_layover_hours


def _night_layovers(direction: tuple[Segment, ...]) -> int:
    """Escales qui englobent un créneau 01:00-05:00 entier, en heure locale du hub."""
    count = 0
    for a, b in itertools.pairwise(direction):
        assert a.arrival is not None and b.departure is not None
        day = a.arrival.date() + timedelta(days=a.arrival.time() > NIGHT[0])
        night_end = datetime.combine(day, NIGHT[1], a.arrival.tzinfo)
        count += b.departure >= night_end
    return count


def assemble(
    out: tuple[Segment, ...],
    ret: tuple[Segment, ...],
    ground: tuple[GroundLeg, ...],
    metro_cost: Decimal,
    params: SearchParams,
    penalties: Penalties,
) -> Trip | None:
    """Voyage complet si toutes les contraintes horaires de §4.2 tiennent, sinon None."""
    to_origin = next((g for g in ground if g.origin == params.home), None)
    to_home = next((g for g in ground if g.destination == params.home), None)
    total = (
        sum((s.price_eur for s in (*out, *ret)), Decimal(0))
        + sum((g.cost_eur for g in ground), Decimal(0))
        + metro_cost
    )
    if params.max_total_price is not None and total > params.max_total_price:
        return None
    timed = all(s.timed for s in (*out, *ret))
    on_site: float | None = None
    if timed:
        first, last, arrive, leave_site = out[0], ret[-1], out[-1], ret[0]
        assert first.departure and last.arrival and arrive.arrival and leave_site.departure
        on_site = _hours(leave_site.departure - arrive.arrival)
        if on_site < params.min_on_site_hours:
            return None
        leave = first.departure - timedelta(minutes=to_origin.duration_min if to_origin else 0)
        back = last.arrival + timedelta(minutes=to_home.duration_min if to_home else 0)
        nights = (back.date() - leave.date()).days  # minuits locaux franchis
        if not _within_deadline(params, leave, back):
            return None
        naive = (leave.replace(tzinfo=None), back.replace(tzinfo=None))
        if any(b.start < naive[1] and b.end > naive[0] for b in params.blackout):
            return None
        if params.depart_weekdays and first.departure.weekday() not in params.depart_weekdays:
            return None
        if params.return_weekdays and leave_site.departure.weekday() not in params.return_weekdays:
            return None
    else:
        nights = (ret[-1].day - out[0].day).days  # contrôles au jour, faits par candidates
    if nights > params.max_nights:
        return None

    nights_in_airport = (_night_layovers(out) + _night_layovers(ret)) if timed else 0
    score = total + penalties.airport_night_eur * nights_in_airport
    badges = [
        *(["self-transfer"] if len(out) > 1 or len(ret) > 1 else []),
        *(
            ["open-jaw"]
            if out[0].origin != ret[-1].destination or out[-1].destination != ret[0].origin
            else []
        ),
        *(["sol"] if ground else []),
        *(["nuit en aéroport"] if nights_in_airport else []),
        *([] if timed else [UNTIMED_BADGE]),
    ]
    return Trip(out, ret, ground, score, total, nights, on_site, tuple(badges))


def _within_deadline(params: SearchParams, leave: datetime, back: datetime) -> bool:
    dl = params.return_deadline
    if dl is None:
        return True
    limit_day = deadline_day(params, leave.date()) or back.date()
    return back.replace(tzinfo=None) <= datetime.combine(limit_day, dl.at)
