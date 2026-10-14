"""python -m cheaphops.recon <url> --goal "..." : capture le trafic d'une page et garde les
réponses JSON qui contiennent des codes IATA (et des prix, sauf pour l'objectif `routes`)."""

import argparse
import asyncio
import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from patchright.async_api import async_playwright as stealth_playwright
from playwright.async_api import async_playwright

from cheaphops.fetch.http import registrable_domain
from cheaphops.recon.analyze import Captured, candidate, visible_prices

SKIPPED_RESOURCES = {"image", "media", "font"}  # scraping respectueux : rien d'inutile


async def capture(
    url: str, headed: bool, wait_s: float, third_party: bool, clicks: list[str], stealth: bool
) -> tuple[list[Captured], str, int, str]:
    captured: list[Captured] = []
    tasks: list[asyncio.Task[None]] = []
    sent = 0

    # Any : objets Playwright ou patchright selon --stealth, même API
    async def keep(resp: Any) -> None:
        if "json" not in (resp.headers.get("content-type") or ""):
            return
        try:
            body = await resp.json()
        except Exception:  # corps vide, tronqué ou pas vraiment du JSON
            return
        req = resp.request
        headers = await req.all_headers()
        try:
            post = req.post_data
        except UnicodeDecodeError:  # corps binaire (capteur anti-bot…) : pas une API de données
            post = None
        captured.append(Captured(resp.url, req.method, headers, post, resp.status, body))

    def count(_: Any) -> None:
        nonlocal sent
        sent += 1

    site = registrable_domain(url)

    async def route(r: Any) -> None:
        foreign = not third_party and registrable_domain(r.request.url) != site
        if foreign or r.request.resource_type in SKIPPED_RESOURCES:
            await r.abort()
        else:
            await r.continue_()

    # patchright : même API que Playwright, Chromium durci contre la détection (moteur du rung 3)
    async with stealth_playwright() if stealth else async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed)
        page = await browser.new_page(locale="en-GB")
        await page.route("**/*", route)
        page.on("request", count)
        page.on("response", lambda r: tasks.append(asyncio.ensure_future(keep(r))))
        doc = await page.goto(url, wait_until="networkidle", timeout=60_000)
        document = f"HTTP {doc.status if doc else '?'} {page.url}"  # mur anti-bot : statut, URL
        for label in clicks:  # scénario minimal : bandeau cookies, bouton « rechercher »…
            await page.get_by_text(label, exact=True).first.click(timeout=10_000)
            await page.wait_for_load_state("networkidle")
        # headed : fermer la fenêtre termine la capture, sinon `--wait` secondes. Exception : le
        # timeout n'a pas la même classe selon Playwright / patchright
        with contextlib.suppress(Exception):
            await page.wait_for_event("close", timeout=wait_s * 1000)
        text = "" if page.is_closed() else await page.inner_text("body")
        # une réponse illisible ne doit jamais faire perdre toute la capture (navigation manuelle)
        for err in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(err, Exception):
                print(f"réponse ignorée : {type(err).__name__}: {err}", file=sys.stderr)
        if browser.is_connected():
            await browser.close()
    return captured, text, sent, document


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url")
    ap.add_argument("--goal", required=True, help="ex. calendar, day_flights, routes")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument(
        "--wait",
        type=float,
        default=3.0,
        help="secondes max après le chargement (headed : fermer la fenêtre termine plus tôt)",
    )
    ap.add_argument(
        "--click", action="append", default=[], help="texte exact à cliquer, dans l'ordre"
    )
    ap.add_argument("--stealth", action="store_true", help="Chromium furtif (patchright)")
    ap.add_argument("--third-party", action="store_true", help="ne pas bloquer les autres domaines")
    args = ap.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    out: Path = args.out or Path("data/recon") / f"{urlsplit(args.url).hostname}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    captured, text, sent, document = asyncio.run(
        capture(args.url, args.headed, args.wait, args.third_party, args.click, args.stealth)
    )
    needs_price = "routes" not in args.goal.lower()
    found = []
    for i, c in enumerate(captured):
        name = f"resp_{i:02d}.json"  # toutes les réponses JSON : un recon de plus coûte plus cher
        (out / name).write_text(json.dumps(c.body, ensure_ascii=False, indent=1))
        if (cand := candidate(c, needs_price)) is not None:
            found.append(cand | {"response_file": name})

    (out / "candidates.json").write_text(json.dumps(found, ensure_ascii=False, indent=1))
    (out / "page.txt").write_text(text)
    meta = {
        "url": args.url,
        "goal": args.goal,
        "captured_at": stamp,
        "document": document,
        "requests_sent": sent,
        "json_urls": {f"resp_{i:02d}.json": c.url[:200] for i, c in enumerate(captured)},
        "visible_prices": visible_prices(text)[:50],
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"{out} : {len(found)} candidates / {len(captured)} JSON, {sent} requêtes envoyées")
    for f in found:
        print(f"  {f['method']} {f['url_template'][:120]}  {f['signals']}")
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
