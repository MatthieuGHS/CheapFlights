"""Recherche « dernière minute partout » : départs de J+0 à J+N depuis les origines, vers
n'importe quelle destination.

Étape 1 (en parallèle) : Ryanair, Wizz, Google et les sources YAML.
Étape 2 : retours Ryanair depuis chaque destination dont l'aller coûte moins que le seuil (Wizz
donne ses retours dans le même farechart que ses allers).
"""

import asyncio
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ryanair import Ryanair

from cheaphops.core.config import Ground, LastMinute
from cheaphops.lastminute import generic, sources
from cheaphops.lastminute.fares import (
    Deal,
    Fare,
    RoundTrip,
    best_per_destination,
    bundled_roundtrips,
    by_destination,
    cheapest_oneways,
    dedupe,
    roundtrips,
)
from cheaphops.lastminute.fx import Fx, load_fx

Emit = Callable[[dict[str, Any]], None]


@dataclass
class SourceReport:
    requests: int = 0
    fares: int = 0
    in_window: int = 0  # tarifs dont le départ tombe dans J+0..J+N
    seconds: float = 0.0
    error: str | None = None
    mode: str | None = None  # mode Scrapling qui a livré (sources YAML)


@dataclass
class Result:
    oneways: list[Fare]
    roundtrips: list[RoundTrip]  # la meilleure combinaison par destination
    alternatives: dict[str, list[RoundTrip]]  # toutes les dates des destinations affichées
    deals: list[Deal]  # bons plans sans date
    requests: int
    seconds: float
    sources: dict[str, SourceReport] = field(default_factory=dict)


def _in_window(d: Deal, d0: date, d1: date, cfg: LastMinute) -> bool:
    """Un bon plan daté part dans la fenêtre et revient en `max_nights` ; sans date, gardé."""
    if d.day is None:
        return True
    nights_ok = d.back is None or (d.back - d.day).days <= cfg.max_nights
    return d0 <= d.day <= d1 and nights_ok


def _sample(d0: date, d1: date, n: int) -> list[date]:
    span = (d1 - d0).days
    return sorted({d0 + timedelta(days=round(i * span / max(n - 1, 1))) for i in range(n)})


async def run(
    cfg: LastMinute,
    ground: Ground,
    today: date,
    emit: Emit = lambda e: None,
    fx: Fx | None = None,
) -> Result:
    start = time.monotonic()
    d0, d1 = today, today + timedelta(days=cfg.days)
    origins = set(cfg.origins)
    bus = {o: ground.cost(o) for o in origins}
    ground_by_airport = bus
    reports: dict[str, SourceReport] = {}
    modes: dict[str, str] = {}
    rates = fx if fx is not None else await asyncio.to_thread(load_fx)

    def pause() -> None:  # appelé depuis les threads des sources : time.sleep ne bloque que le leur
        time.sleep(random.uniform(*cfg.pause_s))

    async def call[T](name: str, fn: Callable[[], tuple[list[T], int]]) -> list[T]:
        rep, t = reports.setdefault(name, SourceReport()), time.monotonic()
        try:
            items, sent = await asyncio.to_thread(fn)
        except Exception as e:  # une source en panne ne doit pas faire tomber la recherche
            rep.error = f"{type(e).__name__}: {e}"[:200]
            items, sent = [], 0
        rep.requests += sent
        rep.fares += len(items)
        rep.seconds += time.monotonic() - t
        emit({"type": "source", "source": name, "fares": len(items), "requests": sent,
              "error": rep.error})  # fmt: skip
        return items

    # Budget : Ryanair et Wizz d'abord (leur coût est connu), Google prend ce qu'il reste en
    # gardant de la place pour les retours ; les routes Wizz se réduisent si la période est longue
    n = len(cfg.origins)
    span = cfg.days + cfg.max_nights + 1
    windows = -(-span // (2 * sources.FARECHART_RADIUS + 1))
    slices = -(-(cfg.days + 1) // sources.RYANAIR_SLICE_DAYS)
    returns = 25
    room = cfg.request_budget - n * slices - returns - (1 + n)
    wizz_routes = max(min(cfg.wizz_routes, room // windows), 0)
    g_dests, g_dates = cfg.google.destinations, cfg.google.dates
    g_left = room - wizz_routes * windows if cfg.google.enabled else 0
    while n * len(g_dests) * g_dates > g_left and g_dates > 1:
        g_dates -= 1
    g_dests = g_dests[: max(g_left, 0) // max(n * g_dates, 1)]

    api = Ryanair(currency="EUR")

    def ry_out() -> tuple[list[Fare], int]:
        fares, first = [], True
        for o in cfg.origins:
            for lo in range(0, cfg.days + 1, sources.RYANAIR_SLICE_DAYS):
                if not first:
                    pause()
                first = False
                hi = min(lo + sources.RYANAIR_SLICE_DAYS - 1, cfg.days)
                fares += sources.ryanair(api, o, d0 + timedelta(lo), d0 + timedelta(hi))
        return fares, api.num_queries

    web_fares: list[Fare] = []

    async def web_all() -> list[Deal]:
        """Sources YAML : une à la fois (chacune peut ouvrir un navigateur)."""
        deals: list[Deal] = []
        for src in generic.load_sources():

            def one(src: generic.Source = src) -> tuple[list[Deal], int]:
                got, fares, pages, mode = generic.run_source(
                    src, rates, (d0, d1, cfg.max_nights, cfg.origins)
                )
                web_fares.extend(fares)
                reports[f"web:{src.name}"].fares += len(fares)
                modes[src.name] = mode
                return got, pages

            got = await call(f"web:{src.name}", one)
            if src.name in modes:
                reports[f"web:{src.name}"].mode = modes[src.name]
            deals += [d for d in got if d.origin in origins and _in_window(d, d0, d1, cfg)]
        return deals

    ry, wz, gg, deals = await asyncio.gather(
        call("ryanair", ry_out),
        call("wizzair", lambda: sources.wizz(
            cfg.origins, d0, d1, cfg.max_nights, wizz_routes, pause, rates)),
        call("google", lambda: sources.google(
            cfg.origins, g_dests, _sample(d0, d1, g_dates), pause) if g_dests else ([], 0)),
        web_all(),
    )  # fmt: skip
    last = d1 + timedelta(days=cfg.max_nights)
    # VNO et KUN forment une zone MAC chez Wizz : un même vol sort des deux farecharts
    pool = [f for f in dedupe([*ry, *wz, *gg, *web_fares]) if d0 <= f.day <= last]
    outs = [f for f in pool if f.origin in origins and f.day <= d1]
    backs = [f for f in pool if f.destination in origins]
    for f in outs:
        reports.setdefault(
            f.source if f.source in reports else f"web:{f.source}", SourceReport()
        ).in_window += 1

    # Étape 2 : les retours manquants. Les allers simples de toutes les sources se combinent déjà
    # entre eux ; il reste à chercher (Ryanair, 1 requête chacune) le retour des destinations sans
    # aucun vol vers les origines dans le pool, les moins chères d'abord, dans ce que le budget
    # permet. Wizz donne ses retours dans le farechart : ses destinations sont déjà couvertes.
    covered = {b.origin for b in backs}
    cheapest: dict[str, Fare] = {}
    for f in sorted(outs, key=lambda f: f.price):
        if f.destination not in origins and f.destination not in covered:
            cheapest.setdefault(f.destination, f)
    used = sum(r.requests for r in reports.values())
    picks = [f for f in cheapest.values() if f.source != "wizzair"][
        : max(cfg.request_budget - used, 0)
    ]
    if picks:
        before = api.num_queries

        def ry_back() -> tuple[list[Fare], int]:
            fares = []
            for i, p in enumerate(picks):
                if i:
                    pause()
                span = p.day + timedelta(days=cfg.max_nights)
                fares += [x for x in sources.ryanair(api, p.destination, p.day, span)
                          if x.destination in origins]  # fmt: skip
            return fares, api.num_queries - before

        backs += await call("ryanair", ry_back)

    total = sum(r.requests for r in reports.values())
    dated = [d for d in deals if d.day is not None and d.back is not None]
    undated = {(d.origin, d.destination, d.price): d for d in deals if d not in dated}
    best_deals = sorted(undated.values(), key=lambda d: d.price)[: cfg.top]
    trips = roundtrips(outs, backs, cfg.max_nights, bus)
    trips += bundled_roundtrips(dated, origins, cfg.max_nights, ground_by_airport)
    ranked = best_per_destination(trips)[: cfg.top]
    shown = {t.out.destination for t in ranked}
    alternatives = {
        dest: group
        for dest, group in by_destination(trips, cfg.alternatives).items()
        if dest in shown
    }
    result = Result(
        cheapest_oneways(outs, cfg.oneways_max, bus),
        ranked,
        alternatives,
        best_deals,
        total,
        time.monotonic() - start,
        reports,
    )
    emit({"type": "finished", "requests": total, "seconds": round(result.seconds, 1)})
    return result
