"""python -m cheaphops.recon <url> --goal "..." : capture le trafic d'une page et garde les
réponses JSON qui contiennent des codes IATA (et des prix, sauf pour l'objectif `routes`)."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import Request, Response, Route, async_playwright

from cheaphops.recon.analyze import Captured, candidate, visible_prices

SKIPPED_RESOURCES = {"image", "media", "font"}  # scraping respectueux : rien d'inutile


async def capture(url: str, headed: bool, wait_s: float) -> tuple[list[Captured], str, int]:
    captured: list[Captured] = []
    tasks: list[asyncio.Task[None]] = []
    sent = 0

    async def keep(resp: Response) -> None:
        if "json" not in (resp.headers.get("content-type") or ""):
            return
        try:
            body = await resp.json()
        except Exception:  # corps vide, tronqué ou pas vraiment du JSON
            return
        req = resp.request
        headers = await req.all_headers()
        captured.append(Captured(resp.url, req.method, headers, req.post_data, resp.status, body))

    def count(_: Request) -> None:
        nonlocal sent
        sent += 1

    async def route(r: Route) -> None:
        if r.request.resource_type in SKIPPED_RESOURCES:
            await r.abort()
        else:
            await r.continue_()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        page = await browser.new_page(locale="en-GB")
        await page.route("**/*", route)
        page.on("request", count)
        page.on("response", lambda r: tasks.append(asyncio.ensure_future(keep(r))))
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(wait_s * 1000)  # mode headed : le temps de naviguer à la main
        text = await page.inner_text("body")
        await asyncio.gather(*tasks)
        await browser.close()
    return captured, text, sent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url")
    ap.add_argument("--goal", required=True, help="ex. calendar, day_flights, routes")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--wait", type=float, default=3.0, help="secondes après le chargement")
    args = ap.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out: Path = args.out or Path("data/recon") / f"{urlsplit(args.url).hostname}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    captured, text, sent = asyncio.run(capture(args.url, args.headed, args.wait))
    needs_price = "routes" not in args.goal.lower()
    found = []
    for i, c in enumerate(captured):
        cand = candidate(c, needs_price)
        if cand is None:
            continue
        cand["response_file"] = f"resp_{i:02d}.json"
        (out / cand["response_file"]).write_text(json.dumps(c.body, ensure_ascii=False, indent=1))
        found.append(cand)

    (out / "candidates.json").write_text(json.dumps(found, ensure_ascii=False, indent=1))
    (out / "page.txt").write_text(text)
    meta = {
        "url": args.url,
        "goal": args.goal,
        "captured_at": stamp,
        "requests_sent": sent,
        "json_responses": len(captured),
        "visible_prices": visible_prices(text)[:50],
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"{out} : {len(found)} candidates / {len(captured)} JSON, {sent} requêtes envoyées")
    for f in found:
        print(f"  {f['method']} {f['url_template']}  {f['signals']}")
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
