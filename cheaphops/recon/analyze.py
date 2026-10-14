"""Partie pure de recon : repérer les réponses qui contiennent des codes IATA et des prix."""

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from cheaphops.context.compress import json_skeleton

IATA_KEY = re.compile(
    r"iata|code|origin|destination|station|airport|from|to|departure|arrival", re.I
)
PRICE_KEY = re.compile(r"price|amount|fare|value|total", re.I)
IATA = re.compile(r"^[A-Z]{3}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
NOISE_HEADERS = re.compile(
    r"^(cookie|user-agent|accept-encoding|accept-language|referer|origin|sec-|priority|connection|content-length|host)",
    re.I,
)
VISIBLE_PRICE = re.compile(
    r"(?:€\s?(\d{1,4}(?:[.,]\d{2})?))|(?:(\d{1,4}(?:[.,]\d{2})?)\s?(?:€|EUR))"
)


@dataclass(frozen=True)
class Captured:
    url: str
    method: str
    request_headers: dict[str, str]
    post_data: str | None
    status: int
    body: Any


def signals(value: Any, key: str = "") -> tuple[int, int]:
    """(nb de codes IATA, nb de montants plausibles) dans un JSON."""
    if isinstance(value, dict):
        pairs = [signals(v, k) for k, v in value.items()]
    elif isinstance(value, list):
        pairs = [signals(v, key) for v in value]
    elif isinstance(value, str) and IATA.match(value) and IATA_KEY.search(key):
        return 1, 0
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and PRICE_KEY.search(key):
        return 0, int(0 < value < 10_000)
    else:
        return 0, 0
    return sum(p[0] for p in pairs), sum(p[1] for p in pairs)


def url_template(url: str) -> str:
    parts = urlsplit(url)
    segs = [
        "{iata}" if IATA.match(s) else "{date}" if DATE.match(s) else s
        for s in parts.path.split("/")
    ]
    return f"{parts.scheme}://{parts.netloc}{'/'.join(segs)}"


def candidate(c: Captured, needs_price: bool) -> dict[str, Any] | None:
    iata, prices = signals(c.body)
    if iata == 0 or (needs_price and prices == 0):
        return None
    return {
        "url_template": url_template(c.url),
        "url": c.url,
        "method": c.method,
        "status": c.status,
        "params": dict(parse_qsl(urlsplit(c.url).query)),
        "headers": {k: v for k, v in c.request_headers.items() if not NOISE_HEADERS.match(k)},
        "post_data": c.post_data,
        "signals": {"iata": iata, "prices": prices},
        "skeleton": json_skeleton(c.body),
    }


def visible_prices(page_text: str) -> list[str]:
    return [" ".join(m.group(0).split()) for m in VISIBLE_PRICE.finditer(page_text)]
