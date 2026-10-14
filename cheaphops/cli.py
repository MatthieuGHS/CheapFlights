"""cheaphops search : lance une recherche et affiche le top-K."""

import argparse
import asyncio
import sys
from datetime import date, timedelta
from typing import Any

from cheaphops.core.config import load_config, load_ground
from cheaphops.core.db import connect
from cheaphops.core.log import setup_logging
from cheaphops.core.models import SearchParams
from cheaphops.search.engine import Event, run_search
from cheaphops.search.model import Segment, Trip


def build_params(args: argparse.Namespace, today: date) -> SearchParams:
    config = load_config()
    defaults = config.search.presets[args.preset] if args.preset else config.search.defaults
    params = defaults.params(today)
    update: dict[str, Any] = {}
    if args.origins:
        update["origins"] = args.origins.split(",")
    if args.weeks:
        update["date_to"] = params.date_from + timedelta(weeks=args.weeks)
    if args.top:
        update["top_k"] = args.top
    return SearchParams.model_validate(params.model_dump() | update)


def _when(s: Segment) -> str:
    if s.departure and s.arrival:
        return f"{s.departure:%a %d/%m %H:%M} -> {s.arrival:%H:%M}"
    return f"{s.day:%a %d/%m} (horaire inconnu)"


def render(trips: list[Trip]) -> str:
    head = f"{'#':>2}  {'dest':4} {'total €':>8} {'score':>8}  {'dates':13} {'nuits':>5}"
    lines = [f"{head} {'sur place':>9}  badges"]
    for i, t in enumerate(trips, 1):
        dates = f"{t.outbound[0].day:%d/%m}-{t.inbound[-1].day:%d/%m}"
        site = f"{t.on_site_hours:.0f} h" if t.on_site_hours is not None else "?"
        lines.append(
            f"{i:>2}  {t.destination:4} {t.total_eur:>8} {t.score:>8}  {dates:13} {t.nights:>5} "
            f"{site:>9}  {', '.join(t.badges)}"
        )
        for g in t.ground:
            lines.append(
                f"      sol  {g.origin}->{g.destination}  {g.duration_min} min  {g.cost_eur} €"
            )
        for s in (*t.outbound, *t.inbound):
            lines.append(
                f"      {s.source:8} {s.flight_no or '':7} {s.origin}->{s.destination}  "
                f"{_when(s):28} {s.price_eur:>7} €  {s.booking_url or ''}"
            )
    return "\n".join(lines)


def progress(e: Event) -> None:
    print(" ".join(f"{k}={v}" for k, v in e.items()), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cheaphops")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("search", help="cherche les voyages les moins chers")
    s.add_argument("--preset", help="preset de config.yaml (ex. weekend)")
    s.add_argument("--origins", help="ex. VNO,KUN,RIX")
    s.add_argument("--weeks", type=int, help="fenêtre de départ en semaines")
    s.add_argument("--top", type=int, help="nombre de résultats")
    s.add_argument("--budget", type=int, help="requêtes de scraping max (défaut : config)")
    args = ap.parse_args(argv)

    config = load_config()
    if args.budget is not None:
        search = config.search.model_copy(update={"request_budget": args.budget})
        config = config.model_copy(update={"search": search})
    setup_logging(config.log_level)
    today = date.today()
    params = build_params(args, today)
    result = asyncio.run(
        run_search(params, config, load_ground(), connect(config.db_path), today, progress)
    )
    print(render(result.trips))
    note = " (budget épuisé)" if result.budget_exhausted else ""
    print(
        f"\n{len(result.trips)} voyages, {result.candidates} candidats, {result.pruned} paires "
        f"écartées par la borne, {result.requests} requêtes de scraping{note}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
