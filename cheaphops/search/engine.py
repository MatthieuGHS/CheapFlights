"""Recherche de bout en bout (§9) : Explore -> candidats -> Verify, sous budget de requêtes."""

import sqlite3
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from cheaphops.core.config import Config, GroundConfig
from cheaphops.core.ctx import Ctx, make_ctx
from cheaphops.core.models import Manifest, SearchParams
from cheaphops.fetch.http import BudgetExhausted, CtxHttp, FetchFailed, SourceBlocked, Throttle
from cheaphops.fetch.types import Transport
from cheaphops.recipes.base import RecipeError
from cheaphops.recipes.registry import LoadedRecipe, load
from cheaphops.search.candidates import Grid, Ranked, candidates
from cheaphops.search.fx import ECB, Fx
from cheaphops.search.graph import assemble, chains
from cheaphops.search.model import Quote, Segment, Trip
from cheaphops.search.planner import Budget

Event = dict[str, Any]
Emit = Callable[[Event], None]
TransportsFor = Callable[[Manifest], Mapping[int, Transport] | None]
SOURCE_ERRORS = (FetchFailed, RecipeError)


@dataclass(frozen=True)
class SearchResult:
    trips: list[Trip]
    requests: int
    budget_exhausted: bool
    candidates: int
    pruned: int


def months(first: date, last: date) -> list[date]:
    out, m = [], first.replace(day=1)
    while m <= last:
        out.append(m)
        m = (m + timedelta(days=32)).replace(day=1)
    return out


@dataclass
class _Source:
    loaded: LoadedRecipe
    ctx: Ctx
    blocked: bool = False
    over_budget: bool = False

    @property
    def name(self) -> str:
        return self.loaded.manifest.source

    def can(self, capability: str) -> bool:
        return capability in self.loaded.manifest.capabilities

    def stats(self) -> Event:
        http = self.ctx.http
        return {"source": self.name, "requests": http.sent, "cache_hits": http.cache_hits,
                "rung": http.last_rung}  # fmt: skip


async def run_search(
    params: SearchParams,
    config: Config,
    ground: GroundConfig,
    conn: sqlite3.Connection,
    today: date,
    emit: Emit = lambda e: None,
    transports_for: TransportsFor = lambda m: None,
    throttle: Throttle | None = None,
    recipes: list[LoadedRecipe] | None = None,
) -> SearchResult:
    """`transports_for`, `throttle` et `recipes` : points d'injection des tests (sans réseau)."""
    run_id = uuid.uuid4().hex[:8]
    throttle = throttle or Throttle()
    budget = Budget(config.search.request_budget, config.search.verify_reserve)
    sources = [
        _Source(
            lr,
            make_ctx(
                config,
                conn,
                lr.manifest,
                throttle,
                run_id,
                today,
                transports_for(lr.manifest),
                gate=budget.allow,
            ),
        )
        for lr in recipes or [load(name) for name in config.search.sources]
    ]
    fx_http = CtxHttp(conn, ECB, config.http, throttle, transports_for(ECB), gate=budget.allow)
    fx = Fx(fx_http)
    async with AsyncExitStack() as stack:
        for http in (*(s.ctx.http for s in sources), fx_http):
            await stack.enter_async_context(http)
        grid = await _explore(sources, params, budget, fx, emit)
        timed = {s.name for s in sources if s.can("day_flights")}
        slack = Decimal(str(config.search.bound_slack))
        ranked = candidates(grid, params, ground, slack, timed, ground.metro.transfer_cost_eur)
        emit({"type": "candidates", "count": ranked.pairs})
        budget.start_verify()
        trips = await _verify(ranked, sources, params, config, fx, emit)
    pruned = ranked.pairs - ranked.examined[0]  # paires jamais examinées : écartées par la borne
    emit({"type": "done", "trips": len(trips), "requests": budget.spent,
          "pruned": pruned, "fx_skipped": fx.unavailable})  # fmt: skip
    return SearchResult(trips, budget.spent, budget.exhausted, ranked.pairs, pruned)


async def _guarded[T](src: _Source, emit: Emit, what: str, call: Awaitable[T]) -> T | None:
    """Une erreur de source n'arrête jamais la recherche : elle est signalée, la source continue
    (ou s'arrête si elle est bloquée)."""
    try:
        return await call
    except BudgetExhausted:
        if not src.over_budget:  # un seul événement par source : la suite vient du cache ou rien
            emit({"type": "budget", "source": src.name, "what": what})
        src.over_budget = True
    except SourceBlocked as e:
        src.blocked = True
        emit({"type": "error", "source": src.name, "what": what, "error": str(e), "blocked": True})
    except SOURCE_ERRORS as e:
        emit({"type": "error", "source": src.name, "what": what, "error": str(e)})
    return None


async def _explore(
    sources: list[_Source], params: SearchParams, budget: Budget, fx: Fx, emit: Emit
) -> Grid:
    grid: Grid = {}
    out_months = months(params.date_from, params.date_to)
    back_months = months(params.date_from, params.date_to + timedelta(days=params.max_nights))

    async def add(src: _Source, o: str, d: str, month: date) -> None:
        fares = await _guarded(
            src, emit, f"calendar {o}-{d}", src.loaded.recipe.calendar(src.ctx, o, d, month)
        )
        for f in fares or []:
            eur = await fx.to_eur(f.price, f.currency)
            if eur is None:
                continue
            q = Quote(src.name, f.origin, f.destination, f.day, eur)
            day_fares = grid.setdefault((src.name, f.origin, f.destination), {})
            if f.day not in day_fares or eur < day_fares[f.day].price_eur:
                day_fares[f.day] = q

    async def explore_pairs(
        queues: list[tuple[_Source, list[tuple[str, str]]]], level: int
    ) -> None:
        """Chaque source à son tour : un budget serré profite à toutes."""
        for i in range(max((len(q) for _, q in queues), default=0)):
            for src, pairs in queues:
                if i >= len(pairs) or src.blocked:
                    continue
                o, d = pairs[i]
                for m in out_months:
                    await add(src, o, d, m)
                for m in back_months:
                    await add(src, d, o, m)
                emit({"type": "progress", "phase": "explore", "level": level, "of": len(pairs),
                      "done": i + 1, **src.stats()})  # fmt: skip

    origins = set(params.origins)
    level1: list[tuple[_Source, list[tuple[str, str]]]] = []
    for src in sources:
        pairs: list[tuple[str, str]] = []
        for o in params.origins:
            dests = await _guarded(src, emit, f"routes {o}", src.loaded.recipe.routes(src.ctx, o))
            pairs += [(o, d) for d in dests or [] if d not in origins]
        served = {d: sum(1 for _, x in pairs if x == d) for _, d in pairs}
        # shortcut: priorité aux destinations desservies depuis plusieurs origines (open-jaw),
        # puis alphabétique ; l'historique des prix (ex-phase 5) donnerait un meilleur ordre
        pairs.sort(key=lambda p: (-served[p[1]], p[1], p[0]))
        emit({"type": "explore", "level": 1, "source": src.name, "routes": len(pairs)})
        level1.append((src, pairs))
    await explore_pairs(level1, 1)

    if not (params.allow_self_transfer and params.max_stops_per_direction):
        return grid
    # Second niveau (self-transfer) : depuis les hubs atteints au meilleur prix, vers des
    # destinations finales, en commençant par celles qu'aucune origine ne dessert en direct.
    level2: list[tuple[_Source, list[tuple[str, str]]]] = []
    for src, pairs in level1:
        if src.blocked or not src.can("day_flights"):  # sans horaires, pas de correspondance
            continue
        direct = {d for _, d in pairs}
        cheapest = {
            d: min(q.price_eur for q in fares.values())
            for (source, o, d), fares in grid.items()
            if source == src.name and o in origins and d in direct and fares
        }
        hops: list[tuple[str, str]] = []
        for hub in sorted(cheapest, key=lambda h: cheapest[h]):
            finals = await _guarded(
                src, emit, f"routes {hub}", src.loaded.recipe.routes(src.ctx, hub)
            )
            hops += [(hub, f) for f in finals or [] if f not in origins and f != hub]
        hops.sort(key=lambda p: (p[1] in direct, cheapest[p[0]]))
        emit({"type": "explore", "level": 2, "source": src.name, "routes": len(hops)})
        level2.append((src, hops))
    await explore_pairs(level2, 2)
    return grid


async def _verify(
    ranked: Ranked,
    sources: list[_Source],
    params: SearchParams,
    config: Config,
    fx: Fx,
    emit: Emit,
) -> list[Trip]:
    """Branch-and-bound (§9) : vérifie les candidats par borne croissante et s'arrête dès que la
    borne du suivant dépasse le K-ième score vérifié ; aucun candidat restant ne peut entrer."""
    by_name = {s.name: s for s in sources}
    flights: dict[tuple[str, str, str, date], list[Segment]] = {}
    # shortcut: l'âge des prix vaut l'heure du Verify, même servi par le cache (écart <= 15 min,
    # la fraîcheur « verify ») ; exposer http_cache.fetched_at si l'UI doit être exacte
    now = datetime.now(UTC)

    async def segments(q: Quote) -> list[Segment]:
        src = by_name[q.source]
        url = src.loaded.recipe.booking_url(q.origin, q.destination, q.day)
        if not src.can("day_flights"):
            return [Segment(q.source, q.origin, q.destination, q.day, q.price_eur, booking_url=url)]
        key = (q.source, q.origin, q.destination, q.day)
        if key not in flights:
            got = await _guarded(
                src,
                emit,
                f"day_flights {q.origin}-{q.destination} {q.day}",
                src.loaded.recipe.day_flights(src.ctx, q.origin, q.destination, q.day),
            )
            flights[key] = [
                Segment(
                    f.source, f.origin, f.destination, f.departure.date(), eur,
                    departure=f.departure, arrival=f.arrival, flight_no=f.flight_no,
                    booking_url=url, fetched_at=now,
                )
                for f in got or [] if (f.origin, f.destination) == (q.origin, q.destination)
                if (eur := await fx.to_eur(f.price, f.currency)) is not None
            ]  # fmt: skip
        return flights[key]

    best: list[Trip] = []
    for i, c in enumerate(ranked.stream):
        if len(best) >= params.top_k and c.bound > best[params.top_k - 1].score:
            break
        outs = chains([await segments(q) for q in c.out.quotes], params)
        rets = chains([await segments(q) for q in c.ret.quotes], params)
        options = [
            t for o in outs for r in rets
            if (t := assemble(o, r, c.ground, c.metro_cost, params, config.search.penalties))
        ]  # fmt: skip
        if options:
            best = sorted([*best, min(options, key=lambda t: t.score)], key=lambda t: t.score)[
                : params.top_k
            ]
        emit({"type": "progress", "phase": "verify", "done": i + 1, "of": ranked.pairs,
              "requests": sum(src.ctx.http.sent for src in sources)})  # fmt: skip
    return best
