"""Exploration courte d'un site : fetcher, puis stealthy, puis dynamic (le premier qui livre
une vraie page s'arrête là). Écrit le HTML dans data/probe/ et renvoie un résumé."""

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

OUT = Path("data/probe")
WALLS = [
    "captcha", "cf-chl", "just a moment", "access denied", "pardon our interruption",
    "px-captcha", "datadome", "incapsula", "are you a robot", "unusual traffic", "kasada",
    "attention required", "request blocked", "enable javascript and cookies",
]  # fmt: skip
PRICE = re.compile(r"(?:€|EUR|zł|PLN|Kč|\$)\s?\d|\d\s?(?:€|EUR|zł|PLN)")


def _wall(status: int, text: str) -> str | None:
    if status in (401, 403, 407, 429, 503):
        return f"HTTP {status}"
    low = text[:60000].lower()
    for w in WALLS:
        if w in low and len(text) < 120_000:
            return w
    return None


def _summary(mode: str, page: Any, url: str) -> dict[str, Any]:
    text = page.html_content or ""
    title = (page.css("title::text").get() or "").strip()[:80]
    xhr = [
        {"url": str(x.url)[:140], "bytes": len(x.body or b""), "status": x.status}
        for x in (getattr(page, "captured_xhr", None) or [])
        if b"{" in (x.body or b"")[:5] or b"[" in (x.body or b"")[:5]
    ]
    return {
        "url": url, "mode": mode, "status": page.status, "bytes": len(text), "title": title,
        "wall": _wall(page.status, text), "prices": len(PRICE.findall(text)),
        "links": len(page.css("a")), "xhr_json": xhr[:8],
    }  # fmt: skip


def probe(url: str, modes: tuple[str, ...] = ("fetcher", "stealthy", "dynamic")) -> dict[str, Any]:
    from scrapling.fetchers import DynamicFetcher, Fetcher, StealthyFetcher

    OUT.mkdir(parents=True, exist_ok=True)
    slug = hashlib.sha1(url.encode()).hexdigest()[:10]
    tried: list[dict[str, Any]] = []
    for mode in modes:
        t = time.monotonic()
        try:
            if mode == "fetcher":
                page = Fetcher.get(url, stealthy_headers=True, timeout=25)
            elif mode == "stealthy":
                page = StealthyFetcher.fetch(
                    url, headless=True, network_idle=True, timeout=60_000, capture_xhr=r".*"
                )
            else:
                page = DynamicFetcher.fetch(
                    url, headless=True, network_idle=True, timeout=60_000, capture_xhr=r".*"
                )
            s = _summary(mode, page, url)
            (OUT / f"{slug}.{mode}.html").write_text(page.html_content or "")
        except Exception as e:
            s = {"url": url, "mode": mode, "error": f"{type(e).__name__}: {str(e)[:100]}"}
        s["seconds"] = round(time.monotonic() - t, 1)
        s["file"] = f"{slug}.{mode}.html"
        tried.append(s)
        if not s.get("error") and not s.get("wall") and s["status"] == 200 and s["bytes"] > 4000:
            break
    best = tried[-1]
    best["tried"] = [t["mode"] for t in tried]
    return best


def main(argv: list[str]) -> None:
    urls = [u for u in argv if u.startswith("http")] or [
        line.split()[0] for line in sys.stdin if line.startswith("http")
    ]
    with ThreadPoolExecutor(5) as ex:
        for r in ex.map(probe, urls):
            print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
