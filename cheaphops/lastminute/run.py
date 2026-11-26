"""Recherche « dernière minute partout » : départs de J+0 à J+N depuis les origines, vers
n'importe quelle destination.

Étape 1 (en parallèle) : Ryanair, Wizz, Google, airBaltic, Kiwi et les sources YAML.
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
from datetime import time as time_of_day
from decimal import Decimal
from typing import Any

from ryanair import Ryanair

from cheaphops.core.config import Ground, LastMinute
from cheaphops.lastminute import airports, cache, generic, sources
from cheaphops.lastminute.fares import (
    Bus,
    Calendar,
    Deal,
    Fare,
    RoundTrip,
    Window,
    best_per_destination,
    bundled_roundtrips,
    by_destination,
    calendar_for,
    cheapest_oneways,
    connections,
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
class PeriodResult:
    """Les aller-retours d'une plage : aller et retour y tombent tous les deux."""

    start: date
    end: date
    roundtrips: list[RoundTrip]  # la meilleure combinaison par destination
    alternatives: dict[str, list[RoundTrip]]  # toutes les dates des destinations affichées
    calendars: dict[str, Calendar]  # prix par jour (aller et retour) des destinations affichées


@dataclass
class Result:
    oneways: list[Fare]
    periods: list[PeriodResult]
    deals: list[Deal]  # bons plans sans date
    bus: dict[str, Bus]  # bus depuis le domicile par aéroport d'origine (info)
    cities: dict[str, str]  # code IATA -> ville, pour les aéroports affichés
    requests: int
    seconds: float
    sources: dict[str, SourceReport] = field(default_factory=dict)


HORIZON_DAYS = 60  # plages au-delà refusées : le budget de requêtes s'étalerait trop
RESERVE_STEP2 = 25  # requêtes laissées par l'étape 1 à la vérification et aux retours
RESERVE_RETURNS = 20  # requêtes laissées par la vérification aux retours manquants
HUBS, HUB_DAYS = 6, 3  # correspondances : hubs explorés, jours d'arrivée lus par hub
CONNECTION_DESTS = 20  # destinations via un hub dont on cherche le retour


def _connection_reserve(cfg: LastMinute, months: int) -> int:
    """Requêtes gardées pour les correspondances : jours de hub, vols vers le hub, calendriers
    hub -> chaque origine sur chaque mois."""
    if not cfg.connections:
        return 0
    return HUBS * HUB_DAYS + CONNECTION_DESTS + HUBS * len(cfg.origins) * months


log = logging.getLogger("cheaphops.lastminute")


async def _none() -> list[Fare]:
    return []


def windows_for(cfg: LastMinute, today: date) -> list[Window]:
    """Une fenêtre par plage du calendrier ; sans plage, une seule : départ de J+0 à J+days,
    retour jusqu'à `max_nights` plus tard. Lève ValueError pour une plage passée ou trop loin."""
    if not cfg.periods:
        d1 = today + timedelta(days=cfg.days)
        return [Window(today, d1 + timedelta(days=cfg.max_nights), d1)]
    limit = today + timedelta(days=HORIZON_DAYS)
    for p in cfg.periods:
        if p.start < today or p.end > limit:
            raise ValueError(f"plage {p.start} -> {p.end} hors de {today} -> {limit}")
    return [Window(p.start, p.end, p.end) for p in cfg.periods]


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


def _out_days(windows: list[Window], weekend: bool) -> list[date]:
    """Jours où un départ est possible, triés (vendredis et samedis seuls en mode week-end)."""
    days = {w.start + timedelta(i) for w in windows for i in range((w.last_out - w.start).days + 1)}
    return sorted(d for d in days if not weekend or d.weekday() in (4, 5))


def _back_days(windows: list[Window], outs: list[date], cfg: LastMinute) -> list[date]:
    """Jours de retour qui forment un aller-retour avec l'un des départs `outs` : 1 à
    `max_nights` nuits plus tard, dans la même plage (dimanche ou lundi en mode week-end)."""
    days = {
        d + timedelta(k)
        for d in outs
        for k in range(1, cfg.max_nights + 1)
        for w in windows
        if w.allows_out(d) and w.contains(d + timedelta(k))
    }
    return sorted(d for d in days if not cfg.weekend or d.weekday() in (6, 0))


def _ry_windows(days: list[date]) -> list[tuple[date, date]]:
    """Plages interrogées sur oneWayFares (une requête par plage et par aéroport, le moins cher
    par destination) : les jours de départ consécutifs, par tranches de 10 jours au plus."""
    out: list[tuple[date, date]] = []
    for d in days:
        lo, hi = out[-1] if out else (d, d)
        if out and hi == d - timedelta(1) and (d - lo).days < sources.RYANAIR_SLICE_DAYS:
            out[-1] = (lo, d)
        else:
            out.append((d, d))
    return out


def _months(d0: date, last: date) -> list[date]:
    months, cur = [], d0.replace(day=1)
    while cur <= last:
        months.append(cur)
        cur = (cur + timedelta(days=32)).replace(day=1)
    return months


def _weekend_leg(f: Fare, cfg: LastMinute) -> bool:
    return weekend_out(f) or weekend_back(f, cfg.weekend_return_before)[0]


def _in_window(d: Deal, windows: list[Window], cfg: LastMinute) -> bool:
    """Un bon plan daté part dans une plage et y revient en `max_nights` ; sans date, gardé."""
    if d.day is None:
        return True
    back, day = d.back, d.day
    nights_ok = back is None or (back - day).days <= cfg.max_nights
    return nights_ok and any(
        w.allows_out(day) and (back is None or w.contains(back)) for w in windows
    )


def _extra_cost(cfg: LastMinute, windows: int, aim: list[str]) -> int:
    """Requêtes réservées à airBaltic et Kiwi : plafond airBaltic, et par plage, Kiwi n'importe
    où (+ retours) ou aller et retour par cible."""
    ab = 0
    if cfg.airbaltic.enabled:
        routes = len(cfg.origins) * len(aim) if aim else cfg.airbaltic.requests
        ab = min(cfg.airbaltic.requests, 1 + 2 * routes)
    kiwi = windows * (2 * len(aim) if aim else 1 + cfg.kiwi.returns) if cfg.kiwi.enabled else 0
    return ab + kiwi


def _plan(
    cfg: LastMinute, slices: int, windows: int, months: int = 1, extra: int = 0
) -> tuple[int, list[str], int]:
    """Budget de l'étape 1 : (routes Wizz, destinations Google, dates Google). Ryanair et Wizz
    d'abord (leur coût est connu), Google prend ce qu'il reste ; les routes Wizz se réduisent si
    la période est longue (`windows` farecharts par route)."""
    n = len(cfg.origins)
    room = cfg.request_budget - n * slices - RESERVE_STEP2 - (1 + n) - extra
    room -= _connection_reserve(cfg, months)
    wizz_routes = max(min(cfg.wizz_routes, room // windows), 0)
    g_dests, g_dates = cfg.google.destinations, cfg.google.dates
    g_left = room - wizz_routes * windows if cfg.google.enabled else 0
    while n * len(g_dests) * g_dates > g_left and g_dates > 1:
        g_dates -= 1
    return wizz_routes, g_dests[: max(g_left, 0) // max(n * g_dates, 1)], g_dates


def _plan_aimed(
    cfg: LastMinute,
    aim: list[str],
    pairs: int,
    months: int,
    charts: int,
    slices: int,
    extra: int = 0,
) -> tuple[int, int, list[str], int]:
    """Budget de l'étape 1 en mode cibles : (paires Ryanair, paires Wizz, cibles Google, dates
    Google). Ryanair d'abord (prix jour par jour réels), puis Wizz, Google prend le reste."""
    n = len(cfg.origins)
    room = cfg.request_budget - RESERVE_STEP2 - extra
    if cfg.connections:  # recherche des hubs « n'importe où » et correspondances
        room -= n * slices + _connection_reserve(cfg, months)
    ry = min(pairs, max(room, 0) // (2 * months))
    room -= ry * 2 * months
    wz = min(pairs, max(room - 1, 0) // charts)
    room -= wz * charts + 1
    g_dates = cfg.google.dates
    while 2 * n * len(aim) * g_dates > room and g_dates > 1:
        g_dates -= 1
    return ry, wz, aim[: max(room, 0) // (2 * n * g_dates)], g_dates


def _pick_verifications(
    targets: dict[tuple[str, str, str], Decimal], left: int, limit: int, costs: dict[str, int]
) -> dict[str, list[tuple[str, str]]]:
    """Routes à vérifier par compagnie, les moins chères d'abord, dans `left` requêtes."""
    todo: dict[str, list[tuple[str, str]]] = {"ryanair": [], "wizzair": []}
    for (home, other, kind), _price in sorted(targets.items(), key=lambda kv: kv[1]):
        if len(todo["ryanair"]) + len(todo["wizzair"]) >= limit or costs[kind] > left:
            continue
        todo[kind].append((home, other))
        left -= costs[kind]
    return todo


def _missing_returns(
    outs: list[Fare], backs: list[Fare], origins: set[str], limit: int
) -> list[Fare]:
    """Allers dont la destination n'a aucun retour connu, un par destination, les moins chers
    d'abord. Wizz donne ses retours dans le farechart et un prix indicatif ne vaut pas une
    requête : ceux-là sont exclus."""
    covered = {b.origin for b in backs}
    cheapest: dict[str, Fare] = {}
    for f in sorted(outs, key=lambda f: f.price):
        if f.destination not in origins and f.destination not in covered:
            cheapest.setdefault(f.destination, f)
    # une correspondance a déjà son retour par le hub : pas de requête « retour direct » pour elle
    picks = [
        f
        for f in cheapest.values()
        if f.source not in ("wizzair", "airbaltic") and not f.indicative and not f.legs
    ]
    return picks[: max(limit, 0)]


def _hub_days(firsts: list[Fare]) -> list[tuple[str, date]]:
    """(hub, jour d'arrivée) à explorer : les premiers vols les moins chers, `HUBS` hubs au plus
    et `HUB_DAYS` jours par hub, le moins cher d'abord."""
    chosen: dict[str, list[date]] = {}
    for f in sorted(firsts, key=lambda f: f.price):
        if f.arrival is None or (f.destination not in chosen and len(chosen) >= HUBS):
            continue
        days = chosen.setdefault(f.destination, [])
        if f.arrival.date() not in days and len(days) < HUB_DAYS:
            days.append(f.arrival.date())
    return [(h, d) for h, days in chosen.items() for d in days]


def _sample(days: list[date], n: int) -> list[date]:
    """`n` jours répartis régulièrement parmi `days` (triés)."""
    last = len(days) - 1
    return sorted({days[round(i * last / max(n - 1, 1))] for i in range(n)}) if days else []


async def run(
    cfg: LastMinute,
    ground: Ground,
    today: date,
    emit: Emit = lambda e: None,
    fx: Fx | None = None,
) -> Result:
    start = time.monotonic()
    windows = windows_for(cfg, today)
    spans = [(w.start, w.end) for w in windows]
    d0, last = windows[0].start, windows[-1].end  # enveloppe : les sources la couvrent
    out_days = _out_days(windows, cfg.weekend)
    origins = set(cfg.origins)
    bus = {
        o: Bus(ground.buses[o].cost_eur, ground.buses[o].duration_min)
        for o in origins
        if o in ground.buses
    }  # information seulement : jamais dans les totaux
    reports: dict[str, SourceReport] = {}
    modes: dict[str, str] = {}
    rates = fx if fx is not None else await asyncio.to_thread(load_fx)
    cache.TTL_S = cfg.cache_minutes * 60

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

    ry_windows = _ry_windows(out_days)
    charts = len(sources.farechart_centers_for(spans))
    months = sorted({m for a, b in spans for m in _months(a, b)})
    aim = list(dict.fromkeys(cfg.destinations))  # vide : n'importe où
    pairs = [(o, t) for o in cfg.origins for t in aim if o != t]
    extra = _extra_cost(cfg, len(windows), aim)
    if aim:  # routes connues : prix jour par jour sur chacune, pas de découverte
        ry_pairs, wizz_routes, g_dests, g_dates = _plan_aimed(
            cfg, aim, len(pairs), len(months), charts, len(ry_windows), extra
        )
    else:
        ry_pairs = 0
        wizz_routes, g_dests, g_dates = _plan(cfg, len(ry_windows), charts, len(months), extra)
    if not cfg.google.enabled:
        g_dests = []

    api = Ryanair(currency="EUR")
    verified: set[tuple[str, str, str]] = set()  # routes dont le prix vient de la compagnie

    def ry_calendars(routes: list[tuple[str, str]]) -> tuple[list[Fare], int]:
        fares, sent = [], 0
        for home, other in routes:
            try:
                for o, d in ((home, other), (other, home)):
                    got, n_req = sources.ryanair_calendar(api, o, d, months, d0, last, pause)
                    fares += got
                    sent += n_req
                    pause()
            except Exception as e:  # route absente chez Ryanair (404) : on passe à la suivante
                log.info("calendrier Ryanair %s-%s: %s", home, other, e)
                sent += 1  # la requête refusée est partie quand même
                continue
            verified.add((home, other, "ryanair"))
        return fares, sent

    def wz_routes(routes: list[tuple[str, str]]) -> tuple[list[Fare], int]:
        got, sent = sources.wizz(cfg.origins, spans, len(routes), pause, rates, routes)
        # une réponse bloquée (403, 429) ne renvoie rien : la route reste indicative
        verified.update(r for f in got if (r := _route(f, origins, "wizzair")))
        return got, sent

    def google_job() -> tuple[list[Fare], int]:
        got, sent = sources.google(cfg.origins, g_dests, _sample(out_days, g_dates), pause)
        if aim:  # Google ne connaît que l'aller simple : les retours depuis les cibles aussi
            back_days = _back_days(windows, _sample(out_days, g_dates), cfg)
            back, n = sources.google(g_dests, cfg.origins, _sample(back_days, g_dates), pause)
            got, sent = got + back, sent + n
        return got, sent

    def ry_out() -> tuple[list[Fare], int]:
        fares, first = [], True
        for o in cfg.origins:
            for lo, hi in ry_windows:
                if not first:
                    pause()
                first = False
                fares += sources.ryanair(api, o, lo, hi)
        return fares, api.num_queries

    def ry_step1() -> tuple[list[Fare], int]:
        got, sent = ry_calendars(pairs[:ry_pairs]) if aim else ([], 0)
        if not aim:
            return ry_out()
        if cfg.connections:  # en mode cibles, seulement pour trouver des hubs
            try:
                more, n = ry_out()
            except Exception as e:  # les calendriers des cibles restent valables
                log.info("Ryanair, recherche des hubs : %s", e)
            else:
                got, sent = got + more, sent + n
        return got, sent

    web_fares: list[Fare] = []

    async def web_all() -> list[Deal]:
        """Sources YAML : une à la fois (chacune peut ouvrir un navigateur)."""
        deals: list[Deal] = []
        for src in generic.load_sources():

            def one(src: generic.Source = src) -> tuple[list[Deal], int]:
                got, fares, pages, mode = generic.run_source(
                    src, rates, (d0, max(w.last_out for w in windows), cfg.max_nights, cfg.origins)
                )
                web_fares.extend(fares)
                reports[f"web:{src.name}"].fares += len(fares)
                modes[src.name] = mode
                return got, pages

            got = await call(f"web:{src.name}", one)
            if src.name in modes:
                reports[f"web:{src.name}"].mode = modes[src.name]
            deals += [d for d in got if d.origin in origins and _in_window(d, windows, cfg)]
        return deals

    ry, wz, gg, ab, kw, deals = await asyncio.gather(
        call("ryanair", ry_step1),
        call("wizzair", (lambda: wz_routes(pairs[:wizz_routes])) if aim else lambda: sources.wizz(
            cfg.origins, spans, wizz_routes, pause, rates)),
        call("google", google_job) if g_dests else _none(),
        call("airbaltic", lambda: sources.airbaltic(
            cfg.origins, aim, spans, cfg.airbaltic.requests, pause))
        if cfg.airbaltic.enabled else _none(),
        call("kiwi", lambda: sources.kiwi(cfg.origins, aim, spans, cfg.kiwi.returns, pause))
        if cfg.kiwi.enabled else _none(),
        web_all(),
    )  # fmt: skip
    if aim:  # les agrégateurs cherchent partout : on ne garde que les cibles
        deals = [d for d in deals if d.destination in aim]

    # VNO et KUN forment une zone MAC chez Wizz : un même vol sort des deux farecharts
    def in_windows(f: Fare) -> bool:
        return any(w.contains(f.day) for w in windows)

    def wanted(f: Fare) -> bool:
        return in_windows(f) and (not aim or f.destination in aim or f.origin in aim)

    pool = [f for f in dedupe([*ry, *wz, *gg, *ab, *kw, *web_fares]) if wanted(f)]

    # Vérification : les agrégateurs découvrent des routes, le prix vient de la compagnie.
    # Pour chaque route Ryanair ou Wizz trouvée par un agrégateur, calendrier réel sur toute la
    # fenêtre, dans les deux sens ; il remplace les prix de l'agrégateur.
    dated_deals = [d for d in deals if d.day is not None and d.back is not None]
    used = sum(r.requests for r in reports.values())
    if cfg.weekend:  # pas de requête de calendrier pour une route vue seulement un mardi
        pool_hint = [f for f in pool if not f.indicative or _weekend_leg(f, cfg)]
        deal_hint = [d for d in dated_deals if d.day and d.day.weekday() in (4, 5)]
    else:
        pool_hint, deal_hint = pool, dated_deals
    targets = {
        r: p for r, p in _targets(pool_hint, deal_hint, origins).items() if r not in verified
    }
    costs = {"ryanair": 2 * len(months), "wizzair": charts + 1}
    todo = _pick_verifications(
        targets,
        cfg.request_budget - used - RESERVE_RETURNS - _connection_reserve(cfg, len(months)),
        cfg.verify_routes,
        costs,
    )

    async def connect_step(
        ry: list[Fare], outs: list[Fare], cutoff: time_of_day | None
    ) -> tuple[list[Fare], list[Fare]]:
        """Allers avec une escale : depuis les hubs les moins chers à atteindre, tous les vols du
        jour d'arrivée (vers les cibles en mode cibles). Retour par le même hub : vol vers le hub
        puis calendrier hub -> domicile, même jour."""
        gap = timedelta(hours=cfg.connection_min_hours)
        firsts = [
            f for f in ry
            if f.origin in origins and f.destination not in origins and f.arrival is not None
            and any(w.allows_out(f.day) for w in windows) and (cutoff is None or weekend_out(f))
        ]  # fmt: skip
        left = cfg.request_budget - sum(r.requests for r in reports.values()) - RESERVE_RETURNS
        hub_days = _hub_days(firsts)[: max(left, 0)]

        def hub_out() -> tuple[list[Fare], int]:
            got, before = [], api.num_queries
            for i, (hub, day) in enumerate(hub_days):
                if i:
                    pause()
                got += sources.ryanair(api, hub, day, day)
            return got, api.num_queries - before

        seconds = await call("ryanair", hub_out) if hub_days else []
        direct = {f.destination for f in outs}
        seconds = [
            s for s in seconds
            if s.destination not in origins and s.destination not in direct
            and (not aim or s.destination in aim)
        ]  # fmt: skip
        via = [c for c in connections(firsts, seconds, gap) if in_windows(c)]
        best: dict[str, Fare] = {}
        for c in sorted(via, key=lambda c: c.price):
            best.setdefault(c.destination, c)
        # retours : 1 requête par destination, plus les calendriers de chaque nouveau hub,
        # dans ce qui reste du budget
        left = cfg.request_budget - sum(r.requests for r in reports.values()) - RESERVE_RETURNS
        legs: list[Fare] = []
        hubs: list[str] = []
        for c in list(best.values())[:CONNECTION_DESTS]:
            hub = c.legs[0].destination
            cost = 1 + (0 if hub in hubs else len(cfg.origins) * len(months))
            if cost <= left:
                legs.append(c)
                hubs += [] if hub in hubs else [hub]
                left -= cost

        def hub_back() -> tuple[list[Fare], int]:
            got, before = [], api.num_queries
            for c in legs:  # le vol destination -> hub le moins cher dans les nuits permises
                end = next(w.end for w in windows if w.allows_out(c.day))
                span = min(c.day + timedelta(days=cfg.max_nights), end)
                hub = c.legs[0].destination
                try:
                    got += [
                        f
                        for f in sources.ryanair(api, c.destination, c.day, span)
                        if f.destination == hub
                    ]
                except Exception as e:  # une destination en échec n'annule pas les autres
                    log.info("Ryanair %s -> %s : %s", c.destination, hub, e)
                pause()
            sent = api.num_queries - before  # oneWayFares : les réponses en cache ne comptent pas
            for hub in hubs:
                for home in cfg.origins:
                    try:
                        cal, n_req = sources.ryanair_calendar(
                            api, hub, home, months, d0, last, pause
                        )
                    except Exception as e:  # pas de vol hub -> cet aéroport
                        log.info("calendrier Ryanair %s-%s: %s", hub, home, e)
                        sent += 1  # la requête refusée est partie quand même
                        continue
                    got += cal
                    sent += n_req
            return got, sent

        back = await call("ryanair", hub_back) if legs else []
        to_hub = [f for f in back if f.destination in hubs]
        home = [f for f in back if f.destination in origins and in_windows(f)]
        # les vols hub -> domicile servent aussi de retours directs aux allers vers le hub
        direct_home = [f for f in home if not aim or f.origin in aim]  # le hub n'est pas visé
        via_backs = [*direct_home, *(b for b in connections(to_hub, home, gap) if in_windows(b))]
        if cutoff is not None:
            via_backs = [b for b in via_backs if weekend_back(b, cutoff)[0]]
        return via, via_backs

    vr, vw = await asyncio.gather(
        call("ryanair", lambda: ry_calendars(todo["ryanair"])) if todo["ryanair"] else _none(),
        call("wizzair", lambda: wz_routes(todo["wizzair"])) if todo["wizzair"] else _none(),
    )
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
        pool = dedupe([*pool, *vr, *vw])
        pool = [f for f in pool if wanted(f)]
    outs = [f for f in pool if f.origin in origins and any(w.allows_out(f.day) for w in windows)]
    backs = [f for f in pool if f.destination in origins]
    cutoff = cfg.weekend_return_before if cfg.weekend else None
    if cutoff is not None:
        outs = [f for f in outs if weekend_out(f)]
        backs = [b for b in backs if weekend_back(b, cutoff)[0]]
    for f in outs:
        reports.setdefault(
            f.source if f.source in reports else f"web:{f.source}", SourceReport()
        ).in_window += 1

    if cfg.connections:
        via, via_backs = await connect_step(ry, outs, cutoff)
        outs += via
        backs = dedupe([*backs, *via_backs])
        pool = [*pool, *via, *via_backs]  # pour les mini-calendriers

    # Étape 2 : les allers simples de toutes les sources se combinent déjà entre eux ; il reste à
    # chercher chez Ryanair (1 requête chacune) le retour des destinations qui n'en ont aucun.
    used = sum(r.requests for r in reports.values())
    picks: list[Fare] = []
    for w in windows:  # une même destination peut manquer de retour dans chaque plage
        picks += _missing_returns(
            [f for f in outs if w.allows_out(f.day)],
            [b for b in backs if w.contains(b.day)],
            origins,
            cfg.request_budget - used - len(picks),
        )
    if picks:
        before = api.num_queries

        def ry_back() -> tuple[list[Fare], int]:
            fares = []
            for i, p in enumerate(picks):
                if i:
                    pause()
                end = next(w.end for w in windows if w.allows_out(p.day))
                span = min(p.day + timedelta(days=cfg.max_nights), end)
                fares += [x for x in sources.ryanair(api, p.destination, p.day, span)
                          if x.destination in origins]  # fmt: skip
            return fares, api.num_queries - before

        backs += await call("ryanair", ry_back)
        if cutoff is not None:  # les retours cherchés après le filtre doivent le respecter aussi
            backs = [b for b in backs if weekend_back(b, cutoff)[0]]

    total = sum(r.requests for r in reports.values())
    undated = {
        (d.origin, d.destination, d.price): d for d in deals if d.day is None or d.back is None
    }
    best_deals = sorted(undated.values(), key=lambda d: d.price)[: cfg.top]
    periods = []
    for w in windows:  # aller et retour dans la même plage
        trips = roundtrips(
            [f for f in outs if w.allows_out(f.day)],
            [b for b in backs if w.contains(b.day)],
            cfg.max_nights, bus, cutoff,
        )  # fmt: skip
        in_w = [
            d
            for d in dated_deals
            if d.day and d.back and w.allows_out(d.day) and w.contains(d.back)
        ]
        trips += bundled_roundtrips(in_w, origins, cfg.max_nights, bus, cutoff)
        ranked = best_per_destination(trips)[: cfg.top]
        shown = {t.out.destination for t in ranked}
        w_pool = [f for f in pool if w.contains(f.day)]
        periods.append(PeriodResult(
            w.start, w.end, ranked,
            {d: g for d, g in by_destination(trips, cfg.alternatives).items() if d in shown},
            {dest: calendar_for(dest, w_pool, origins) for dest in shown},
        ))  # fmt: skip
    oneways = cheapest_oneways([*outs, *(backs if cutoff else [])], cfg.oneways_max)
    legs = [
        *oneways,
        *(f for p in periods for g in p.alternatives.values() for t in g for f in (t.out, t.back)),
    ]
    codes = {c for f in legs for c in (f.origin, f.destination)}
    codes |= {c for d in best_deals for c in (d.origin, d.destination)}
    names = airports.cities()
    result = Result(
        oneways,
        periods,
        best_deals,
        bus,
        {c: names[c] for c in codes if c in names},
        total,
        time.monotonic() - start,
        reports,
    )
    emit({"type": "finished", "requests": total, "seconds": round(result.seconds, 1)})
    return result
