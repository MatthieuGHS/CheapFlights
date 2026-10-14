"""Génération des candidats au niveau jour (§9), avec branch-and-bound sur la borne basse.

Un candidat est un aller et un retour construits sur la grille Explore (prix minimal par jour).
Les filtres de ce niveau sont des relaxations : ils n'écartent jamais un voyage que le Verify,
avec les vrais horaires, aurait accepté. Seuls les segments sans horaires (Wizz) y reçoivent
leur contrôle définitif, prudent.
"""

import heapq
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from cheaphops.core.config import GroundConfig
from cheaphops.core.models import SearchParams
from cheaphops.search.model import GroundLeg, Quote

Grid = dict[tuple[str, str], dict[date, Quote]]


@dataclass(frozen=True)
class Leg:
    """Un sens de voyage au niveau jour : 1 vol, ou 2 en self-transfer."""

    quotes: tuple[Quote, ...]

    @property
    def start(self) -> str:
        return self.quotes[0].origin

    @property
    def end(self) -> str:
        return self.quotes[-1].destination

    @property
    def first_day(self) -> date:
        return self.quotes[0].day

    @property
    def last_day(self) -> date:
        return self.quotes[-1].day

    @property
    def price(self) -> Decimal:
        return sum((q.price_eur for q in self.quotes), Decimal(0))


@dataclass(frozen=True)
class Candidate:
    out: Leg
    ret: Leg
    ground: tuple[GroundLeg, ...]
    metro_cost: Decimal  # transfert entre deux aéroports d'une même ville de destination
    total: Decimal  # prix de grille + sol + transfert
    bound: Decimal  # prix de grille * slack + sol + transfert : borne basse du vrai prix
    untimed: bool  # au moins un segment d'une source sans horaires (Wizz)


def ground_leg(ground: GroundConfig, a: str, b: str) -> GroundLeg | None:
    if a == b:
        return None
    for e in ground.edges:
        if {e.a, e.b} == {a, b}:
            return GroundLeg(a, b, e.duration_min + e.margin_min, e.cost_eur)
    raise LookupError(f"no ground edge {a}-{b}")


def metro_of(ground: GroundConfig) -> dict[str, str]:
    """Aéroport -> ville. shortcut: overrides de ground.yaml seulement ; le regroupement par
    rayon (OurAirports) reste à faire quand une destination manque à l'appel"""
    return {iata: city for city, airports in ground.metro.overrides.items() for iata in airports}


def legs(
    grid: Grid, starts: Iterable[str], days: set[date], stops: int, timed: set[str]
) -> list[Leg]:
    """Sens possibles partant de `starts` un jour de `days`. Une correspondance (self-transfer)
    n'utilise que des sources horodatées et part le jour même ou le lendemain du hub."""
    starts = set(starts)
    by_origin: dict[str, list[tuple[str, dict[date, Quote]]]] = defaultdict(list)
    for (o, d), fares in grid.items():
        by_origin[o].append((d, fares))
    out: list[Leg] = []
    for o in starts:
        for hub, fares in by_origin[o]:
            for day, q in fares.items():
                if day not in days:
                    continue
                out.append(Leg((q,)))
                if stops < 1 or q.source not in timed:
                    continue
                for d, onward in by_origin[hub]:
                    if d in starts or d == o:
                        continue
                    for nxt in (day, day + timedelta(days=1)):
                        q2 = onward.get(nxt)
                        if q2 is not None and q2.source in timed:
                            out.append(Leg((q, q2)))
    return out


def deadline_day(params: SearchParams, leave: date) -> date | None:
    dl = params.return_deadline
    if dl is None or dl.weekday is None:
        return None
    return leave + timedelta(days=(dl.weekday - leave.weekday()) % 7)


def date_level_ok(c_out: Leg, c_ret: Leg, params: SearchParams, untimed: bool) -> bool:
    if c_ret.first_day < c_out.last_day:
        return False
    if (c_ret.last_day - c_out.first_day).days > params.max_nights:
        return False
    on_site_max = ((c_ret.first_day - c_out.last_day).days + 1) * 24
    if on_site_max < params.min_on_site_hours:
        return False
    if params.depart_weekdays and c_out.first_day.weekday() not in params.depart_weekdays:
        return False
    if params.return_weekdays and c_ret.first_day.weekday() not in params.return_weekdays:
        return False
    limit = deadline_day(params, c_out.first_day)
    if limit is not None and c_ret.last_day > limit:
        return False
    if untimed:
        # contrôle définitif prudent : sans horaires, on suppose le pire
        if (c_ret.first_day - c_out.last_day).days * 24 < params.min_on_site_hours:
            return False
        span = (
            datetime.combine(c_out.first_day, time.min),
            datetime.combine(c_ret.last_day, time.max),
        )
        if any(b.start < span[1] and b.end > span[0] for b in params.blackout):
            return False
    return True


def candidates(
    grid: Grid,
    params: SearchParams,
    ground: GroundConfig,
    slack: Decimal,
    keep: int,
    timed: set[str],
    metro_transfer: Decimal,
) -> tuple[list[Candidate], int]:
    """Renvoie les candidats dont la borne basse peut battre le `keep`-ième meilleur prix de
    grille, triés par prix, et le nombre de paires aller/retour écartées par la borne."""
    out_days = {
        params.date_from + timedelta(days=i)
        for i in range((params.date_to - params.date_from).days + 1)
    }
    back_days = {d + timedelta(days=i) for d in out_days for i in range(params.max_nights + 1)}
    stops = params.max_stops_per_direction if params.allow_self_transfer else 0
    reachable = [o for o in params.origins if o == params.home or _has_edge(ground, params.home, o)]
    city = metro_of(ground)

    def group(iata: str) -> str:
        return city.get(iata, iata)

    outs_by_group: dict[str, list[Leg]] = defaultdict(list)
    for leg in legs(grid, reachable, out_days, stops, timed):
        if leg.end not in params.origins:
            outs_by_group[group(leg.end)].append(leg)
    rets_by_group: dict[str, list[Leg]] = defaultdict(list)
    dest_airports = {leg.end for g in outs_by_group.values() for leg in g}
    for leg in legs(grid, dest_airports, back_days, stops, timed):
        if leg.end in reachable:
            rets_by_group[group(leg.start)].append(leg)

    best: list[Decimal] = []  # tas des `keep` meilleurs totaux (négatifs : tas max)
    found: list[Candidate] = []
    pruned = 0
    for g, outs in outs_by_group.items():
        rets = sorted(rets_by_group.get(g, []), key=lambda leg: leg.price)
        for out in sorted(outs, key=lambda leg: leg.price):
            for i, ret in enumerate(rets):
                kth = -best[0] if len(best) >= keep else None
                if kth is not None and (out.price + ret.price) * slack > kth:
                    pruned += len(rets) - i  # les retours suivants sont encore plus chers
                    break
                c = _pair(out, ret, params, ground, slack, metro_transfer, timed)
                if c is None or (kth is not None and c.bound > kth):
                    continue
                if params.max_total_price is not None and c.bound > params.max_total_price:
                    continue
                found.append(c)
                heapq.heappush(best, -c.total)
                if len(best) > keep:
                    heapq.heappop(best)
    kth = -best[0] if len(best) >= keep else None
    kept = [c for c in found if kth is None or c.bound <= kth]
    pruned += len(found) - len(kept)
    return sorted(kept, key=lambda c: c.total), pruned


def _has_edge(ground: GroundConfig, a: str, b: str) -> bool:
    return any({e.a, e.b} == {a, b} for e in ground.edges)


def _pair(
    out: Leg,
    ret: Leg,
    params: SearchParams,
    ground: GroundConfig,
    slack: Decimal,
    metro: Decimal,
    timed: set[str],
) -> Candidate | None:
    untimed = any(q.source not in timed for q in (*out.quotes, *ret.quotes))
    if untimed and (len(out.quotes) > 1 or len(ret.quotes) > 1):
        return None  # sans horaires, une correspondance n'est pas vérifiable (arbitrage Wizz)
    open_jaw = out.start != ret.end or out.end != ret.start
    if open_jaw and not params.allow_open_jaw:
        return None
    if not date_level_ok(out, ret, params, untimed):
        return None
    legs_ = (ground_leg(ground, params.home, out.start), ground_leg(ground, ret.end, params.home))
    ground_legs = tuple(g for g in legs_ if g is not None)
    fixed = sum((g.cost_eur for g in ground_legs), Decimal(0)) + (
        metro if out.end != ret.start else 0
    )
    flights = out.price + ret.price
    return Candidate(
        out, ret, ground_legs, Decimal(fixed), flights + fixed, flights * slack + fixed, untimed
    )
