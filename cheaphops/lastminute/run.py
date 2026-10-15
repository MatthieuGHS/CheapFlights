"""Recherche « dernière minute partout » : départs de J+0 à J+N depuis les origines, vers
n'importe quelle destination.

Étape 1 (en parallèle) : Ryanair, Wizz, Google et les sources YAML.
Étape 2 : retours Ryanair depuis chaque destination dont l'aller coûte moins que le seuil (Wizz
donne ses retours dans le même farechart que ses allers).
"""

import asyncio
import logging
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
from cheaphops.lastminute.fares import (
    Bus,
    Calendar,
    Deal,
    Fare,
    RoundTrip,
    best_per_destination,
    bundled_roundtrips,
    by_destination,
    calendar_for,
    cheapest_oneways,
    dedupe,
    roundtrips,
    weekend_back,
    weekend_out,
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
    bus: dict[str, Bus]  # bus depuis le domicile par aéroport d'origine (info)
    calendars: dict[str, Calendar]  # prix par jour (aller et retour) des destinations affichées
    requests: int
    seconds: float
    sources: dict[str, SourceReport] = field(default_factory=dict)


RESERVE_RETURNS = 20  # requêtes gardées pour les retours manquants
log = logging.getLogger("cheaphops.lastminute")


async def _none() -> list[Fare]:
    return []


def _kind(airline: str) -> str | None:
    low = airline.lower()
    return "ryanair" if "ryanair" in low else "wizzair" if "wizz" in low else None


def _route(f: Fare, origins: set[str], kind: str) -> tuple[str, str, str] | None:
    """Route normalisée (domicile, autre extrémité, compagnie) d'un vol, dans les deux sens."""
    if f.origin in origins:
        return (f.origin, f.destination, kind)
    if f.destination in origins:
        return (f.destination, f.origin, kind)
    return None


def _deal_route(d: Deal, kind: str) -> tuple[str, str, str]:
    return (d.origin, d.destination, kind)


def _targets(
    pool: list[Fare], deals: list[Deal], origins: set[str]
) -> dict[tuple[str, str, str], Decimal]:
    """Routes Ryanair/Wizz vues par un agrégateur, avec le prix indicatif le plus bas. Les codes
    ville de Kayak (MIL, LON…) échouent plus tard chez la compagnie et restent indicatifs."""
    found: dict[tuple[str, str, str], Decimal] = {}
    for f in pool:
        kind = _kind(f.airline)
        route = _route(f, origins, kind) if f.indicative and kind else None
        if route and (route not in found or f.price < found[route]):
            found[route] = f.price
    for d in deals:
        kind = _kind(d.airline or "")
        if kind and d.origin in origins:
            route = _deal_route(d, kind)
            if route not in found or d.price < found[route]:
                found[route] = d.price
    return found


def _ry_windows(d0: date, d1: date, weekend: bool) -> list[tuple[date, date]]:
    """Plages interrogées sur oneWayFares (une requête par plage et par aéroport, le moins cher
    par destination). Normal : tranches de 10 jours. Week-end : seulement les vendredis-samedis,
    où un départ est possible."""
    if not weekend:
        step = sources.RYANAIR_SLICE_DAYS
        return [
            (d0 + timedelta(lo), min(d0 + timedelta(lo + step - 1), d1))
            for lo in range(0, (d1 - d0).days + 1, step)
        ]
    days = [d0 + timedelta(i) for i in range((d1 - d0).days + 1)]
    days = [d for d in days if d.weekday() in (4, 5)]
    windows: list[tuple[date, date]] = []
    for d in days:
        if windows and windows[-1][1] == d - timedelta(1):
            windows[-1] = (windows[-1][0], d)
        else:
            windows.append((d, d))
    return windows


def _months(d0: date, last: date) -> list[date]:
    months, cur = [], d0.replace(day=1)
    while cur <= last:
        months.append(cur)
        cur = (cur + timedelta(days=32)).replace(day=1)
    return months


def _weekend_leg(f: Fare, cfg: LastMinute) -> bool:
    return weekend_out(f) or weekend_back(f, cfg.weekend_return_before)[0]


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
    bus = {
        o: Bus(ground.buses[o].cost_eur, ground.buses[o].duration_min)
        for o in origins
        if o in ground.buses
    }  # information seulement : jamais dans les totaux
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
    ry_windows = _ry_windows(d0, d1, cfg.weekend)
    slices = len(ry_windows)
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
            for lo, hi in ry_windows:
                if not first:
                    pause()
                first = False
                fares += sources.ryanair(api, o, lo, hi)
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

    # Vérification : les agrégateurs découvrent des routes, le prix vient de la compagnie.
    # Pour chaque route Ryanair ou Wizz trouvée par un agrégateur, calendrier réel sur toute la
    # fenêtre, dans les deux sens ; il remplace les prix de l'agrégateur.
    dated_deals = [d for d in deals if d.day is not None and d.back is not None]
    months = _months(d0, last)
    ry_cost, wz_cost = 2 * len(months), windows + 1
    used = sum(r.requests for r in reports.values())
    if cfg.weekend:  # pas de requête de calendrier pour une route vue seulement un mardi
        pool_hint = [f for f in pool if not f.indicative or _weekend_leg(f, cfg)]
        deal_hint = [d for d in dated_deals if d.day and d.day.weekday() in (4, 5)]
    else:
        pool_hint, deal_hint = pool, dated_deals
    targets = _targets(pool_hint, deal_hint, origins)
    todo: dict[str, list[tuple[str, str]]] = {"ryanair": [], "wizzair": []}
    left = cfg.request_budget - used - RESERVE_RETURNS
    for (home, other, kind), _price in sorted(targets.items(), key=lambda kv: kv[1]):
        cost = ry_cost if kind == "ryanair" else wz_cost
        if len(todo["ryanair"]) + len(todo["wizzair"]) >= cfg.verify_routes or cost > left:
            continue
        todo[kind].append((home, other))
        left -= cost
    verified: set[tuple[str, str, str]] = set()
    verified_fares: list[Fare] = []

    def ry_verify() -> tuple[list[Fare], int]:
        fares, sent = [], 0
        for home, other in todo["ryanair"]:
            try:
                for o, d in ((home, other), (other, home)):
                    got, n_req = sources.ryanair_calendar(api, o, d, months, d0, last, pause)
                    fares += got
                    sent += n_req
                    pause()
            except Exception as e:
                log.info("calendrier Ryanair %s-%s: %s", home, other, e)
                continue
            verified.add((home, other, "ryanair"))
        return fares, sent

    def wz_verify() -> tuple[list[Fare], int]:
        routes = todo["wizzair"]
        got, sent = sources.wizz(
            cfg.origins, d0, d1, cfg.max_nights, len(routes), pause, rates, routes
        )
        verified.update((h, o, "wizzair") for h, o in routes)
        return got, sent

    vr, vw = await asyncio.gather(
        call("ryanair", ry_verify) if todo["ryanair"] else _none(),
        call("wizzair", wz_verify) if todo["wizzair"] else _none(),
    )
    verified_fares = [*vr, *vw]
    if verified:
        pool = [
            f
            for f in pool
            if not (f.indicative and (k := _kind(f.airline)) and _route(f, origins, k) in verified)
        ]
        dated_deals = [
            d
            for d in dated_deals
            if not ((k := _kind(d.airline or "")) and _deal_route(d, k) in verified)
        ]
        pool = dedupe([*pool, *verified_fares])
        pool = [f for f in pool if d0 <= f.day <= last]
    outs = [f for f in pool if f.origin in origins and f.day <= d1]
    backs = [f for f in pool if f.destination in origins]
    cutoff = cfg.weekend_return_before if cfg.weekend else None
    if cutoff is not None:
        outs = [f for f in outs if weekend_out(f)]
        backs = [b for b in backs if weekend_back(b, cutoff)[0]]
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
    picks = [f for f in cheapest.values() if f.source != "wizzair" and not f.indicative][
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
        if cutoff is not None:  # les retours cherchés après le filtre doivent le respecter aussi
            backs = [b for b in backs if weekend_back(b, cutoff)[0]]

    total = sum(r.requests for r in reports.values())
    dated = dated_deals
    undated = {
        (d.origin, d.destination, d.price): d for d in deals if d.day is None or d.back is None
    }
    best_deals = sorted(undated.values(), key=lambda d: d.price)[: cfg.top]
    trips = roundtrips(outs, backs, cfg.max_nights, bus, cutoff)
    trips += bundled_roundtrips(dated, origins, cfg.max_nights, bus, cutoff)
    ranked = best_per_destination(trips)[: cfg.top]
    shown = {t.out.destination for t in ranked}
    calendars = {dest: calendar_for(dest, pool, origins) for dest in shown}
    alternatives = {
        dest: group
        for dest, group in by_destination(trips, cfg.alternatives).items()
        if dest in shown
    }
    result = Result(
        cheapest_oneways([*outs, *(backs if cutoff else [])], cfg.oneways_max),
        ranked,
        alternatives,
        best_deals,
        bus,
        calendars,
        total,
        time.monotonic() - start,
        reports,
    )
    emit({"type": "finished", "requests": total, "seconds": round(result.seconds, 1)})
    return result
