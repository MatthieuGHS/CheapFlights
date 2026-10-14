"""Smoke test live d'une recette : routes, un mois de calendrier, une journée de vols.
Usage : uv run python scripts/smoke.py ryanair VNO BGY 2026-11"""

import asyncio
import sys
from datetime import date

from cheaphops.core.config import load_config
from cheaphops.core.ctx import make_ctx
from cheaphops.core.db import connect
from cheaphops.core.log import setup_logging
from cheaphops.fetch.http import FetchFailed, Throttle
from cheaphops.recipes.registry import load


async def main(source: str, o: str, d: str, month: str) -> None:
    config = load_config()
    setup_logging(config.log_level)
    conn = connect(config.db_path)
    loaded = load(source)
    ctx = make_ctx(config, conn, loaded.manifest, Throttle(), "smoke", date.today())
    before = conn.execute(
        "SELECT coalesce(sum(successes + failures), 0) FROM fetch_stats"
    ).fetchone()[0]
    async with ctx.http:
        routes = await loaded.recipe.routes(ctx, o)
        print(f"routes {o}: {len(routes)} -> {routes}")
        fares = await loaded.recipe.calendar(ctx, o, d, date.fromisoformat(month + "-01"))
        print(f"calendar {o}-{d} {month}: {[(f.day.isoformat(), str(f.price)) for f in fares]}")
        if fares and "day_flights" in loaded.manifest.capabilities:
            for f in await loaded.recipe.day_flights(ctx, o, d, fares[0].day):
                print(f"  {f.flight_no} {f.departure} -> {f.arrival} {f.price}")
        if fares:
            print(f"  {loaded.recipe.booking_url(o, d, fares[0].day)}")
    after = conn.execute(
        "SELECT coalesce(sum(successes + failures), 0) FROM fetch_stats"
    ).fetchone()[0]
    rungs = conn.execute(
        "SELECT rung, successes, failures, browser_requests FROM fetch_stats WHERE source = ?",
        (source,),
    ).fetchall()
    print(f"requêtes de scraping : {after - before}")
    print(f"stats (rung, succès, échecs, ressources navigateur) : {[tuple(r) for r in rungs]}")


if __name__ == "__main__":
    try:
        asyncio.run(main(*sys.argv[1:5]))
    except FetchFailed as e:
        body = e.result.text[:500] if e.result else ""
        sys.exit(f"échec : {e}\n{body}")
