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
from decimal import Decimal
from typing import Any

from ryanair import Ryanair

from cheaphops.core.config import Ground, LastMinute
from cheaphops.lastminute import generic, sources
from cheaphops.lastminute.fares import Deal, Fare, RoundTrip, cheapest_oneways, roundtrips

Emit = Callable[[dict[str, Any]], None]


@dataclass
class SourceReport:
    requests: int = 0
    fares: int = 0
    in_window: int = 0  # tarifs dont le départ tombe dans J+0..J+N
    seconds: float = 0.0
    error: str | None = None


@dataclass
class Result:
    oneways: list[Fare]
    roundtrips: list[RoundTrip]
    deals: list[Deal]
    requests: int
    seconds: float
    sources: dict[str, SourceReport] = field(default_factory=dict)


def _sample(d0: date, d1: date, n: int) -> list[date]:
    span = (d1 - d0).days
    return sorted({d0 + timedelta(days=round(i * span / max(n - 1, 1))) for i in range(n)})


async def run(cfg: LastMinute, ground: Ground, today: date, emit: Emit = lambda e: None) -> Result:
    start = time.monotonic()
    d0, d1 = today, today + timedelta(days=cfg.days)
    origins = set(cfg.origins)
    bus = {o: ground.cost(o) for o in origins}
    reports: dict[str, SourceReport] = {}

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
    # gardant de la place pour les retours
    n = len(cfg.origins)
    fixed = n + (1 + n + cfg.wizz_routes * -(-(cfg.days + cfg.max_nights + 1) // 19)) + 20
    g_left = max(cfg.request_budget - fixed, 0)
    g_dests, g_dates = cfg.google.destinations, cfg.google.dates
    while n * len(g_dests) * g_dates > g_left and g_dates > 1:
        g_dates -= 1
    g_dests = g_dests[: g_left // max(n * g_dates, 1)]

    api = Ryanair(currency="EUR")

    def ry_out() -> tuple[list[Fare], int]:
        fares = []
        for i, o in enumerate(cfg.origins):
            if i:
                pause()
            fares += sources.ryanair(api, o, d0, d1)
        return fares, api.num_queries

    def web() -> tuple[list[Deal], int]:
        deals, sent = [], 0
        for src in generic.load_sources():
            got, n_pages = generic.fetch_source(src, pause)
            deals += [d for d in got if d.origin in origins]
            sent += n_pages
        return deals, sent

    ry, wz, gg, deals = await asyncio.gather(
        call("ryanair", ry_out),
        call("wizzair", lambda: sources.wizz(
            cfg.origins, d0, d1, cfg.max_nights, cfg.wizz_routes, pause)),
        call("google", lambda: sources.google(
            cfg.origins, g_dests, _sample(d0, d1, g_dates), pause)),
        call("web", web),
    )  # fmt: skip
    last = d1 + timedelta(days=cfg.max_nights)
    # VNO et KUN forment une zone MAC chez Wizz : un même vol sort des deux farecharts
    pool = [f for f in dict.fromkeys((*ry, *wz, *gg)) if d0 <= f.day <= last]
    outs = [f for f in pool if f.origin in origins and f.day <= d1]
    backs = [f for f in pool if f.destination in origins]
    for f in outs:
        reports[f.source].in_window += 1

    # Étape 2 : un retour Ryanair par destination dont l'aller est sous le seuil
    cheap: dict[str, Fare] = {}
    for f in sorted(outs, key=lambda f: f.price):
        if f.price <= Decimal(str(cfg.return_below_eur)) and f.destination not in origins:
            cheap.setdefault(f.destination, f)
    used = sum(r.requests for r in reports.values())
    picks = list(cheap.values())[: max(cfg.request_budget - used, 0)]
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
    result = Result(
        cheapest_oneways(outs, cfg.top, bus),
        roundtrips(outs, backs, cfg.max_nights, cfg.top, bus),
        sorted(deals, key=lambda d: d.price)[: cfg.top],
        total, time.monotonic() - start, reports,
    )  # fmt: skip
    emit({"type": "finished", "requests": total, "seconds": round(result.seconds, 1)})
    return result
