"""Recherche « dernière minute partout » : départs de J+0 à J+N depuis les origines, vers
n'importe quelle destination.

Étape 1 (en parallèle) : aller simples depuis les origines, Ryanair + Wizz + Google.
Étape 2 : pour les destinations les moins chères, les vols retour vers les origines.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from cheaphops.core.config import LastMinute
from cheaphops.lastminute import sources
from cheaphops.lastminute.fares import Fare, RoundTrip, cheapest_oneways, roundtrips

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
    requests: int
    seconds: float
    sources: dict[str, SourceReport] = field(default_factory=dict)


def _sample(d0: date, d1: date, n: int) -> list[date]:
    span = (d1 - d0).days
    return sorted({d0 + timedelta(days=round(i * span / max(n - 1, 1))) for i in range(n)})


async def run(cfg: LastMinute, today: date, emit: Emit = lambda e: None) -> Result:
    start = time.monotonic()
    d0, d1 = today, today + timedelta(days=cfg.days)
    reports: dict[str, SourceReport] = {}

    async def call(name: str, fn: Callable[[], tuple[list[Fare], int]]) -> list[Fare]:
        rep, t = reports.setdefault(name, SourceReport()), time.monotonic()
        try:
            fares, sent = await asyncio.to_thread(fn)
        except Exception as e:  # une source en panne ne doit pas faire tomber la recherche
            rep.error = f"{type(e).__name__}: {e}"[:200]
            fares, sent = [], 0
        rep.requests += sent
        rep.fares += len(fares)
        rep.seconds += time.monotonic() - t
        emit({"type": "source", "source": name, "fares": len(fares), "requests": sent,
              "error": rep.error})  # fmt: skip
        return fares

    # Étape 1 : budget d'abord pour Ryanair et Wizz (peu de requêtes), Google prend le reste
    n = len(cfg.origins)
    fixed = n + 1 + n + 2 * cfg.return_candidates  # ryanair + wizz + (retours estimés)
    g_left = max(cfg.request_budget - fixed, 0)
    g_dests = cfg.google.destinations
    g_dates = cfg.google.dates
    while n * len(g_dests) * g_dates > g_left and g_dates > 1:
        g_dates -= 1
    g_dests = g_dests[: g_left // max(n * g_dates, 1)]

    from ryanair import Ryanair

    api = Ryanair(currency="EUR")

    def ry_out() -> tuple[list[Fare], int]:
        fares = [f for o in cfg.origins for f in sources.ryanair(api, o, d0, d1)]
        return fares, api.num_queries

    stage1 = await asyncio.gather(
        call("ryanair", ry_out),
        call("wizzair", lambda: sources.wizz([([o], None) for o in cfg.origins])),
        call("google", lambda: sources.google(cfg.origins, g_dests, _sample(d0, d1, g_dates))),
    )
    outs = [f for fares in stage1 for f in fares if d0 <= f.day <= d1]
    for f in outs:
        reports[f.source].in_window += 1

    # Étape 2 : retours depuis les k destinations les moins chères (1 requête Ryanair chacune,
    # 1 page + 1 POST Wizz seulement pour celles que Wizz dessert)
    origins = set(cfg.origins)
    used = sum(r.requests for r in reports.values())
    k = min(cfg.return_candidates, max((cfg.request_budget - used - 1) // 2, 0))
    best: dict[str, Fare] = {}
    for f in sorted(outs, key=lambda f: f.price):
        best.setdefault(f.destination, f)
    picks = list(best.values())[:k]
    backs: list[Fare] = []
    if picks:
        before = api.num_queries

        def ry_back() -> tuple[list[Fare], int]:
            fares = [
                x
                for p in picks
                for x in sources.ryanair(
                    api, p.destination, p.day, p.day + timedelta(cfg.max_nights)
                )
                if x.destination in origins
            ]
            return fares, api.num_queries - before

        served = {f.destination for f in stage1[1]}
        wizz_dests = sorted(served & {p.destination for p in picks})
        wz = (
            (lambda: sources.wizz([([d], cfg.origins) for d in wizz_dests])) if wizz_dests else None
        )
        back_parts = await asyncio.gather(
            call("ryanair", ry_back), *([call("wizzair", wz)] if wz else [])
        )
        backs = [f for part in back_parts for f in part if f.destination in origins]

    total = sum(r.requests for r in reports.values())
    result = Result(
        cheapest_oneways(outs, cfg.top),
        roundtrips(outs, backs, origins, cfg.max_nights, cfg.top),
        total, time.monotonic() - start, reports,
    )  # fmt: skip
    emit({"type": "finished", "requests": total, "seconds": round(result.seconds, 1)})
    return result
