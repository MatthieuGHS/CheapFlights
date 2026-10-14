"""Sources génériques : ajouter un site = un fichier YAML dans `lastminute/web/`.

Tout passe par Scrapling : un `Spider` construit depuis le YAML (crawl des listes puis des
articles), lancé d'abord en `fetcher` ; si la page est bloquée ou ne donne rien, relancé en
`stealthy` puis en `dynamic`. Le mode qui a marché est rapporté.

Schéma (voir secretflying.yaml) :
  name, urls, mode (mode de départ), adaptive, cities {nom de ville: IATA}
  crawl:   follow (CSS des liens à suivre depuis chaque page de départ), max_pages
  extract:
    kind: selectors  item (CSS), fields {title, url: CSS avec ::text / ::attr(x)}, pattern
    kind: rss        pattern  (appliquée au titre puis à la description)
    kind: json       response_url_contains (réponse XHR capturée pendant le chargement),
                     items (chemin pointé), fields {origin, destination, price, url, ...}
  pattern : regex à groupes nommés origin, destination, price (montant avec devise)
"""

import contextlib
import json
import re
from collections.abc import AsyncGenerator, Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

import yaml
from pydantic import BaseModel, ConfigDict

from cheaphops.lastminute.fares import Deal
from cheaphops.lastminute.fx import Fx

WEB_DIR = Path(__file__).parent / "web"
MODES = ("fetcher", "stealthy", "dynamic")
SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "zł": "PLN", "Kč": "CZK", "kr": "SEK"}
MONEY = re.compile(
    r"(?P<pre>€|\$|£|[A-Z]{3})?\s*(?P<amt>\d[\d., ]*)\s*(?P<post>€|zł|Kč|[A-Z]{3}\b)?"
)


class Selectors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["selectors"]
    item: str
    fields: dict[str, str]
    pattern: str


class Rss(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["rss"]
    pattern: str


class JsonTap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["json"]
    response_url_contains: str
    items: str
    fields: dict[str, str]
    currency: str = "EUR"


class Crawl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    follow: str
    max_pages: int = 10


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    urls: list[str]
    mode: Literal["fetcher", "stealthy", "dynamic"] = "fetcher"
    adaptive: bool = False
    cities: dict[str, str]
    crawl: Crawl | None = None
    extract: Selectors | Rss | JsonTap


def load_sources(directory: Path = WEB_DIR) -> list[Source]:
    paths = sorted(directory.glob("*.yaml"))
    return [Source.model_validate(yaml.safe_load(p.read_text())) for p in paths]


def parse_money(text: str, default: str = "EUR") -> tuple[Decimal, str] | None:
    """« €66 », « $663 CAD », « 1 299 zł », « 49,90 EUR » -> (montant, devise ISO)."""
    m = MONEY.search(text)
    if not m:
        return None
    raw = m["amt"].strip().rstrip(".,").replace(" ", "")
    if "," in raw and "." in raw:
        sep = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if sep == "," else ",", "").replace(sep, ".")
    elif "," in raw:
        raw = raw.replace(",", "") if re.search(r",\d{3}$", raw) else raw.replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    post = m["post"] or ""
    cur = (post if len(post) == 3 and post.isupper() else None) or SYMBOLS.get(post)
    cur = cur or SYMBOLS.get(m["pre"] or "") or m["pre"]
    return amount, (cur or default)


def _dig(obj: Any, path: str) -> Any:
    for key in path.split("."):
        obj = obj[int(key)] if isinstance(obj, list) else obj[key]
    return obj


def deals_from_rows(src: Source, rows: list[dict[str, str]], fx: Fx) -> list[Deal]:
    """Lignes {title, url, text} -> bons plans : trajet et prix extraits par `pattern`, origine
    gardée si c'est l'une de `cities`, prix converti en EUR."""
    pattern = src.extract.pattern if isinstance(src.extract, Selectors | Rss) else ""
    deals = []
    for row in rows:
        m = next(
            (
                m
                for t in (row.get("title", ""), row.get("text", ""))
                if (m := re.search(pattern, t))
            ),
            None,
        )
        if not m or not row.get("url"):
            continue
        origin = src.cities.get(m["origin"].strip())
        money = parse_money(m["price"])
        eur = fx.to_eur(money[0], money[1]) if money else None
        if origin and eur is not None:
            deals.append(Deal(src.name, row["title"].strip(), origin, m["destination"].strip(),
                              eur, row["url"]))  # fmt: skip
    return deals


def deals_from_json(src: Source, payload: Any, fx: Fx) -> list[Deal]:
    ex = src.extract
    assert isinstance(ex, JsonTap)
    deals = []
    for item in _dig(payload, ex.items):
        try:
            got = {k: _dig(item, path) for k, path in ex.fields.items()}
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        money = parse_money(str(got.get("price")), ex.currency)
        eur = fx.to_eur(money[0], money[1]) if money else None
        origin = src.cities.get(str(got.get("origin")), str(got.get("origin")))
        if eur is not None and got.get("url"):
            when = got.get("when")
            deals.append(Deal(src.name, f"{origin} -> {got.get('destination')}", origin,
                              str(got.get("destination")), eur, str(got["url"]),
                              None if when is None else str(when)))  # fmt: skip
    return deals


def rows_from_rss(body: bytes) -> list[dict[str, str]]:
    root = ElementTree.fromstring(body)
    rows = []
    for it in list(root.iter("item")) + list(root.iter("{http://www.w3.org/2005/Atom}entry")):
        link = it.findtext("link") or ""
        if not link:  # Atom : <link href="…"/>
            el = it.find("{http://www.w3.org/2005/Atom}link")
            link = el.get("href", "") if el is not None else ""
        title = it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or ""
        text = it.findtext("description") or it.findtext("{http://www.w3.org/2005/Atom}summary")
        rows.append({"title": title, "url": link, "text": text or ""})
    return rows


def _spider(src: Source, mode: str) -> Any:
    from scrapling.fetchers import AsyncDynamicSession, AsyncStealthySession, FetcherSession
    from scrapling.spiders import Spider

    tap = src.extract if isinstance(src.extract, JsonTap) else None
    xhr = re.escape(tap.response_url_contains) if tap else None

    class Generic(Spider):
        name = src.name
        start_urls = src.urls
        concurrent_requests = 2
        download_delay = 1.0
        logging_level = 40

        def configure_sessions(self, manager: Any) -> None:
            if mode == "fetcher":
                manager.add("s", FetcherSession(impersonate="chrome", stealthy_headers=True))
            else:
                cls = AsyncStealthySession if mode == "stealthy" else AsyncDynamicSession
                kw: dict[str, Any] = {"headless": True, "network_idle": True}
                if xhr:
                    kw["capture_xhr"] = f".*{xhr}.*"
                manager.add("s", cls(**kw))

        async def parse(self, response: Any) -> AsyncGenerator[Any, None]:
            ex = src.extract
            if isinstance(ex, JsonTap):
                for x in response.captured_xhr:
                    with contextlib.suppress(ValueError):
                        yield {"json": json.loads(x.body)}
                return
            if isinstance(ex, Rss):
                for row in rows_from_rss(response.body):
                    yield row
            else:
                for el in response.css(ex.item, adaptive=src.adaptive, auto_save=src.adaptive):
                    row = {k: str(el.css(sel).get() or "") for k, sel in ex.fields.items()}
                    row["text"] = el.get_all_text()
                    if row.get("url"):
                        row["url"] = response.urljoin(row["url"])
                    yield row
            if src.crawl and not response.meta.get("depth"):
                links = response.css(src.crawl.follow + "::attr(href)").getall()
                for href in list(dict.fromkeys(links))[: src.crawl.max_pages]:
                    yield response.follow(href, meta={"depth": 1})

    return Generic()


def run_source(src: Source, fx: Fx) -> tuple[list[Deal], int, str]:
    """(bons plans, pages demandées, mode qui a marché). Lève LookupError si aucun mode ne livre."""
    start = MODES.index(src.mode)
    last: Exception | None = None
    for mode in MODES[start:]:
        try:
            result = _spider(src, mode).start()
        except Exception as e:
            last = e
            continue
        pages = result.stats.requests_count
        if isinstance(src.extract, JsonTap):
            deals = []
            for item in result.items:
                with contextlib.suppress(KeyError, TypeError, IndexError):
                    deals += deals_from_json(src, item["json"], fx)
        else:
            deals = deals_from_rows(src, [dict(i) for i in result.items], fx)
        if deals:
            return deals, pages, mode
    raise LookupError(f"{src.name}: aucun mode ne livre ({last or 'pages vides ou bloquées'})")


def fetch_source(src: Source, pause: Callable[[], None], fx: Fx) -> tuple[list[Deal], int, str]:
    return run_source(src, fx)
