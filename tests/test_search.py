"""Combinateur (§9) : contraintes au jour et contraintes horaires exactes."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from cheaphops.core.config import load_config, load_ground
from cheaphops.core.models import SearchParams
from cheaphops.search.candidates import Grid, candidates
from cheaphops.search.graph import UNTIMED_BADGE, assemble, chains
from cheaphops.search.model import GroundLeg, Quote, Segment

ROOT = Path(__file__).parent.parent
CONFIG = load_config(ROOT / "config.yaml", ROOT / "absent.yaml")
GROUND = load_ground(ROOT / "ground.yaml")
PEN = CONFIG.search.penalties
LT = timezone(timedelta(hours=2))  # Vilnius en novembre
IT = timezone(timedelta(hours=1))  # Bergame


def params(**kw: Any) -> SearchParams:
    base = CONFIG.search.defaults.params(date(2026, 11, 1)).model_dump()
    return SearchParams.model_validate(base | kw)


def seg(
    o: str, d: str, dep: str, hours: float = 2.5, price: int = 20, tz: timezone = LT
) -> Segment:
    start = datetime.fromisoformat(dep).replace(tzinfo=tz)
    return Segment(
        "ryanair", o, d, start.date(), Decimal(price), start, start + timedelta(hours=hours)
    )


def untimed(o: str, d: str, day: str, price: int = 20) -> Segment:
    return Segment("wizzair", o, d, date.fromisoformat(day), Decimal(price))


OUT = (seg("VNO", "BGY", "2026-11-06T08:00"),)  # vendredi, arrivée 10:30


def trip(
    ret_dep: str, p: SearchParams | None = None, out: tuple[Segment, ...] = OUT, **kw: Any
) -> Any:
    ret = (seg("BGY", "VNO", ret_dep, tz=IT),)
    return assemble(out, ret, kw.get("ground", ()), Decimal(0), p or params(), PEN)


# --- contraintes horaires exactes -------------------------------------------------------


def test_max_nights_counts_local_midnights() -> None:
    assert trip("2026-11-09T18:00").nights == 3  # ven -> lun : 3 minuits
    assert trip("2026-11-10T18:00") is None  # 4 nuits > 3


def test_min_on_site_hours() -> None:
    assert trip("2026-11-06T20:00") is None  # 9,5 h sur place < 24 h
    t = trip("2026-11-07T12:00")
    assert t is not None and t.on_site_hours == pytest.approx(26.5)


def test_min_connection_and_max_layover() -> None:
    hub_in = seg("VNO", "STN", "2026-11-06T06:00", hours=3)  # arrivée 09:00
    too_short = seg("STN", "BGY", "2026-11-06T11:00")  # 2 h < 3 h de marge self-transfer
    fine = seg("STN", "BGY", "2026-11-06T12:30")
    too_long = seg("STN", "BGY", "2026-11-07T06:00")  # 21 h > 18 h d'escale
    got = chains([[hub_in], [too_short, fine, too_long]], params())
    assert got == [(hub_in, fine)]


def test_return_deadline_weekday_and_time() -> None:
    weekend = CONFIG.search.presets["weekend"].params(date(2026, 11, 1))
    assert trip("2026-11-09T08:00", weekend) is not None  # retour lun 08:00 + 2,5 h < 12:00
    assert trip("2026-11-09T10:00", weekend) is None  # arrivée lun 12:30 > 12:00
    noon = params(return_deadline={"at": "12:00", "weekday": None})
    assert trip("2026-11-08T08:00", noon) is not None
    assert trip("2026-11-08T15:00", noon) is None


def test_blackout_overlapping_the_trip_rejects_it() -> None:
    exam = params(blackout=[{"start": "2026-11-07T10:00", "end": "2026-11-07T12:00"}])
    assert trip("2026-11-08T12:00", exam) is None
    later = params(blackout=[{"start": "2026-11-12T10:00", "end": "2026-11-12T12:00"}])
    assert trip("2026-11-08T12:00", later) is not None


def test_ground_leg_costs_and_moves_departure_from_home() -> None:
    from_kun = (seg("KUN", "BGY", "2026-11-07T01:00"),)
    leg = GroundLeg("VNO", "KUN", 210, Decimal(10))
    t = trip("2026-11-09T18:00", out=from_kun, ground=(leg,))
    assert t is not None and t.total_eur == Decimal(50) and "sol" in t.badges
    assert t.nights == 3  # départ de chez moi le 6 à 21:30 pour le vol du 7 à 01:00


def test_night_in_airport_is_penalised() -> None:
    late = (seg("VNO", "STN", "2026-11-06T20:00"), seg("STN", "BGY", "2026-11-07T07:00"))
    t = trip("2026-11-09T12:00", out=late)
    assert t is not None and "nuit en aéroport" in t.badges and "self-transfer" in t.badges
    assert t.score == t.total_eur + PEN.airport_night_eur


def test_untimed_segments_get_badge_and_no_on_site() -> None:
    t = assemble(
        (untimed("VNO", "LTN", "2026-11-06"),), (untimed("LTN", "KUN", "2026-11-08"),),
        (GroundLeg("KUN", "VNO", 210, Decimal(10)),), Decimal(0), params(), PEN,
    )  # fmt: skip
    assert t is not None and t.on_site_hours is None and UNTIMED_BADGE in t.badges
    assert "open-jaw" in t.badges and t.nights == 2


# --- candidats au niveau jour -----------------------------------------------------------


def grid(*quotes: tuple[str, str, str, int, int]) -> Grid:
    g: Grid = {}
    for src, o, d, day, price in quotes:
        g.setdefault((o, d), {})[date(2026, 11, day)] = Quote(
            src, o, d, date(2026, 11, day), Decimal(price)
        )
    return g


def run(g: Grid, p: SearchParams | None = None, keep: int = 30) -> Any:
    return candidates(g, p or params(), GROUND, Decimal("0.8"), keep, {"ryanair"}, Decimal(15))


def test_branch_and_bound_never_drops_a_pair_that_could_beat_the_kth() -> None:
    quotes = [
        ("ryanair", "VNO", d, day, 10 + 7 * i + day)
        for i, d in enumerate(("BGY", "STN", "BVA"))
        for day in (2, 4, 6)
    ]
    quotes += [
        ("ryanair", d, "VNO", day, 12 + 5 * i + day)
        for i, d in enumerate(("BGY", "STN", "BVA"))
        for day in (4, 6, 8)
    ]
    g = grid(*quotes)
    kept, pruned = run(g, keep=3)
    assert pruned > 0 and len(kept) >= 3
    every = [c for c in run(g, keep=10_000)[0]]  # sans élagage effectif
    kth = sorted(c.total for c in every)[2]
    assert {(c.out, c.ret) for c in every if c.bound <= kth} <= {(c.out, c.ret) for c in kept}


def test_untimed_source_never_in_self_transfer() -> None:
    g = grid(
        ("wizzair", "VNO", "STN", 6, 10), ("ryanair", "STN", "BGY", 6, 10),
        ("ryanair", "BGY", "VNO", 9, 10), ("wizzair", "VNO", "BGY", 6, 30),
    )  # fmt: skip
    kept, _ = run(g)
    assert kept and all(len(c.out.quotes) == 1 for c in kept if c.untimed)
    assert all(not c.untimed for c in kept if len(c.out.quotes) > 1)


def test_open_jaw_switch_and_date_level_max_nights() -> None:
    g = grid(
        ("ryanair", "VNO", "BGY", 6, 10),
        ("ryanair", "BGY", "KUN", 8, 10),
        ("ryanair", "BGY", "VNO", 12, 5),
    )
    kept, _ = run(g)
    assert [(c.ret.end, c.ret.last_day.day) for c in kept] == [("KUN", 8)]  # le 12 : 6 nuits
    assert run(g, params(allow_open_jaw=False))[0] == []
