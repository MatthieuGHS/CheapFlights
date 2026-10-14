"""Sources génériques : ajouter un site = un fichier YAML dans `lastminute/web/`.

Schéma (voir secretflying.yaml) :
  name, urls, mode (fetcher | stealthy | dynamic), adaptive, cities {nom de ville: IATA},
  extract:
    kind: selectors  item (CSS), fields {title, url: CSS avec ::text / ::attr(x)}, pattern
                     (regex à groupes origin, destination, price appliquée au titre)
    kind: json       response_url_contains (réponse JSON interceptée pendant le chargement),
                     items (chemin pointé vers la liste), fields {origin, destination, price,
                     url, when: chemins pointés dans chaque élément}
Seuls les prix en EUR sont retenus (€ dans le titre ; devise ignorée pour le JSON : à poser
dans le YAML via `currency` si la source en change).
"""

import contextlib
import json
import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from cheaphops.lastminute.fares import Deal

WEB_DIR = Path(__file__).parent / "web"


class Selectors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["selectors"]
    item: str
    fields: dict[str, str]
    pattern: str


class JsonTap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["json"]
    response_url_contains: str
    items: str
    fields: dict[str, str]


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    urls: list[str]
    mode: Literal["fetcher", "stealthy", "dynamic"]
    adaptive: bool = False
    cities: dict[str, str]
    extract: Selectors | JsonTap


def load_sources(directory: Path = WEB_DIR) -> list[Source]:
    return [
        Source.model_validate(yaml.safe_load(p.read_text()))
        for p in sorted(directory.glob("*.yaml"))
    ]


def _dig(obj: Any, path: str) -> Any:
    for key in path.split("."):
        obj = obj[int(key)] if isinstance(obj, list) else obj[key]
    return obj


def _price(raw: Any) -> Decimal | None:
    try:
        return Decimal(str(raw).replace(",", "."))
    except InvalidOperation:
        return None


def deals_from_titles(src: Source, rows: list[dict[str, str]]) -> list[Deal]:
    ex = src.extract
    assert isinstance(ex, Selectors)
    deals = []
    for row in rows:
        m = re.search(ex.pattern, row.get("title", ""))
        iata = src.cities.get(m["origin"].strip()) if m else None
        price = _price(m["price"]) if m else None
        if m and iata and price is not None and row.get("url"):
            deals.append(Deal(src.name, row["title"].strip(), iata, m["destination"].strip(),
                              price, row["url"]))  # fmt: skip
    return deals


def deals_from_json(src: Source, payload: Any) -> list[Deal]:
    ex = src.extract
    assert isinstance(ex, JsonTap)
    deals = []
    for item in _dig(payload, ex.items):
        try:
            got = {k: _dig(item, path) for k, path in ex.fields.items() if k != "when"}
            when = _dig(item, ex.fields["when"]) if "when" in ex.fields else None
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        price = _price(got.get("price"))
        origin = src.cities.get(str(got.get("origin")), str(got.get("origin")))
        if price is not None and got.get("url"):
            title = f"{origin} -> {got.get('destination')}"
            deals.append(Deal(src.name, title, origin, str(got.get("destination")), price,
                              str(got["url"]), None if when is None else str(when)))  # fmt: skip
    return deals


def fetch_source(src: Source, pause: Callable[[], None]) -> tuple[list[Deal], int]:
    """Une page par URL. Renvoie (bons plans, pages chargées)."""
    deals, sent = [], 0
    for url in src.urls:
        if sent:
            pause()
        sent += 1
        if isinstance(src.extract, JsonTap):
            deals += deals_from_json(src, _tap(src, url, src.extract))
        else:
            deals += _scrape(src, url, src.extract)
    return deals, sent


def _scrape(src: Source, url: str, ex: Selectors) -> list[Deal]:
    page = _load(src, url, None)
    rows = []
    for el in page.css(ex.item, adaptive=src.adaptive, auto_save=src.adaptive):
        rows.append({k: str(el.css(sel).get() or "") for k, sel in ex.fields.items()})
    return deals_from_titles(src, rows)


def _tap(src: Source, url: str, ex: JsonTap) -> Any:
    """Charge la page en écoutant les réponses : la première JSON dont l'URL contient
    `response_url_contains` fait foi. La page est rechargée une fois, l'écoute posée."""
    bodies: list[Any] = []

    def on_response(r: Any) -> None:
        if ex.response_url_contains in r.url:
            with contextlib.suppress(ValueError):  # réponse non JSON : on attend la suivante
                bodies.append(json.loads(r.text()))

    def act(page: Any) -> Any:
        page.on("response", on_response)
        page.reload(wait_until="networkidle")
        return page

    _load(src, url, act)
    if not bodies:
        raise LookupError(f"{src.name}: aucune réponse contenant {ex.response_url_contains!r}")
    return bodies[0]


def _load(src: Source, url: str, action: Callable[[Any], Any] | None) -> Any:
    from scrapling.fetchers import DynamicFetcher, Fetcher, StealthyFetcher

    if src.mode == "fetcher":
        Fetcher.configure(adaptive=src.adaptive)  # type: ignore[no-untyped-call]
        return Fetcher.get(url, stealthy_headers=True, timeout=30)
    fetch = StealthyFetcher.fetch if src.mode == "stealthy" else DynamicFetcher.fetch
    return fetch(url, headless=True, network_idle=True, page_action=action, timeout=60_000)
