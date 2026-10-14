"""Candidats au niveau jour (§9), livrés par borne basse croissante.

Un candidat est un aller et un retour construits sur la grille Explore (prix minimal par jour et
par source). Les filtres de ce niveau sont des relaxations : ils n'écartent jamais un voyage que
le Verify, avec les vrais horaires, aurait accepté. Seuls les voyages sans horaires (Wizz) y
reçoivent leur contrôle définitif, au pire cas.

Le branch-and-bound se fait au Verify : il consomme ce flux tant que la borne du candidat suivant
peut encore battre le K-ième score *vérifié*. Couper ici sur des prix de grille serait faux : un
candidat bon marché peut échouer au Verify.
"""

import heapq
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from cheaphops.core.config import GroundConfig
from cheaphops.core.models import SearchParams
from cheaphops.search.model import GroundLeg, Quote

Grid = dict[tuple[str, str, str], dict[date, Quote]]  # (source, origine, destination)


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
    untimed: bool  # voyage d'une source sans horaires (Wizz)


@dataclass
class Ranked:
    """Flux des candidats ; `examined` / `pairs` mesurent ce que le branch-and-bound a épargné."""

    stream: Iterator[Candidate]
    pairs: int
    examined: list[int] = field(default_factory=lambda: [0])


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
    for (_, o, d), fares in grid.items():
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


def date_level_ok(out: Leg, ret: Leg, params: SearchParams, untimed: bool) -> bool:
    if ret.first_day < out.last_day:
        return False
    if (ret.last_day - out.first_day).days > params.max_nights:
        return False
    if params.depart_weekdays and out.first_day.weekday() not in params.depart_weekdays:
        return False
    if params.return_weekdays and ret.first_day.weekday() not in params.return_weekdays:
        return False
    deadline = params.return_deadline
    limit = deadline.limit_day(out.first_day) if deadline else None
    if untimed:
        # contrôle définitif au pire cas : arrivée à 23:59, retour à 00:00, rentré à 23:59
        if (ret.first_day - out.last_day).days * 24 - 24 < params.min_on_site_hours:
            return False
        if limit is not None and ret.last_day >= limit:
            return False
        span = (datetime.combine(out.first_day, time.min), datetime.combine(ret.last_day, time.max))
        return not params.blocked(*span)
    # relaxation : le meilleur cas des horaires doit pouvoir passer
    if ((ret.first_day - out.last_day).days + 1) * 24 < params.min_on_site_hours:
        return False
    return limit is None or ret.last_day <= limit


def candidates(
    grid: Grid,
    params: SearchParams,
    ground: GroundConfig,
    slack: Decimal,
    timed: set[str],
    metro_transfer: Decimal,
) -> Ranked:
    """Candidats valides au niveau jour, par borne basse croissante, générés paresseusement."""
    span = (params.date_to - params.date_from).days + 1
    out_days = {params.date_from + timedelta(days=i) for i in range(span)}
    back_days = {d + timedelta(days=i) for d in out_days for i in range(params.max_nights + 1)}
    stops = params.max_stops_per_direction if params.allow_self_transfer else 0
    reachable = [o for o in params.origins if o == params.home or _has_edge(ground, params.home, o)]
    city = metro_of(ground)

    def group(iata: str) -> str:
        return city.get(iata, iata)

    outs: dict[str, list[Leg]] = defaultdict(list)
    for leg in legs(grid, reachable, out_days, stops, timed):
        if leg.end not in params.origins:
            outs[group(leg.end)].append(leg)
    rets: dict[str, list[Leg]] = defaultdict(list)
    dest_airports = {leg.end for g in outs.values() for leg in g}
    for leg in legs(grid, dest_airports, back_days, stops, timed):
        if leg.end in reachable:
            rets[group(leg.start)].append(leg)

    pools = [
        (sorted(outs[g], key=lambda leg: leg.price), sorted(rets[g], key=lambda leg: leg.price))
        for g in outs
        if rets.get(g)
    ]
    ranked = Ranked(iter(()), sum(len(o) * len(r) for o, r in pools))

    def stream() -> Iterator[Candidate]:
        # Parcours best-first de chaque grille trié (aller x retour) : la paire (i, j) n'entre
        # dans la frontière qu'après (i-1, j) ou (i, j-1), donc la frontière sort les paires par
        # prix de vols croissant. Un candidat n'est livré que quand plus aucune paire de la
        # frontière ne peut avoir une borne plus basse que la sienne (sol et transfert >= 0).
        frontier: list[tuple[Decimal, int, int, int]] = []
        seen: set[tuple[int, int, int]] = set()
        for p, (o, r) in enumerate(pools):
            heapq.heappush(frontier, ((o[0].price + r[0].price) * slack, p, 0, 0))
            seen.add((p, 0, 0))
        ready: list[tuple[Decimal, int, Candidate]] = []
        tie = 0
        while frontier or ready:
            while frontier and (not ready or frontier[0][0] <= ready[0][0]):
                _, p, i, j = heapq.heappop(frontier)
                o, r = pools[p]
                ranked.examined[0] += 1
                for ni, nj in ((i + 1, j), (i, j + 1)):
                    if ni < len(o) and nj < len(r) and (p, ni, nj) not in seen:
                        seen.add((p, ni, nj))
                        heapq.heappush(frontier, ((o[ni].price + r[nj].price) * slack, p, ni, nj))
                c = _pair(o[i], r[j], params, ground, slack, metro_transfer, timed)
                if c is not None:
                    tie += 1
                    heapq.heappush(ready, (c.bound, tie, c))
            if ready:
                yield heapq.heappop(ready)[2]

    ranked.stream = stream()
    return ranked


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
    sources = {q.source in timed for q in (*out.quotes, *ret.quotes)}
    if sources == {True, False}:
        return None  # voyage mixte : les horaires connus d'un sens ne seraient pas contrôlés
    untimed = sources == {False}
    if untimed and (len(out.quotes) > 1 or len(ret.quotes) > 1):
        return None  # sans horaires, une correspondance n'est pas vérifiable (arbitrage Wizz)
    open_jaw = out.start != ret.end or out.end != ret.start
    if open_jaw and not params.allow_open_jaw:
        return None
    if not date_level_ok(out, ret, params, untimed):
        return None
    if (
        params.max_total_price is not None
        and (out.price + ret.price) * slack > params.max_total_price
    ):
        return None
    pair = (ground_leg(ground, params.home, out.start), ground_leg(ground, ret.end, params.home))
    ground_legs = tuple(g for g in pair if g is not None)
    fixed = sum((g.cost_eur for g in ground_legs), Decimal(0)) + (
        metro if out.end != ret.start else 0
    )
    flights = out.price + ret.price
    return Candidate(
        out, ret, ground_legs, Decimal(fixed), flights + fixed, flights * slack + fixed, untimed
    )
