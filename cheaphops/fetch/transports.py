"""Les quatre rungs de la fetch ladder (§7), du moins cher au plus cher.

1. httpx
2. curl_cffi, empreinte TLS d'un vrai navigateur
3. cookies amorcés par le navigateur furtif de Scrapling (StealthyFetcher), puis curl_cffi
4. navigateur complet (Chromium furtif patchright), requêtes faites depuis la page (fetch JS)

Scrapling `Fetcher` n'est pas un rung : il repose sur curl_cffi, comme le rung 2.
"""

import asyncio
import dataclasses
from typing import Any
from urllib.parse import unquote

import curl_cffi
import httpx
from curl_cffi.requests import AsyncSession

# patchright : API de Playwright, Chromium sans les fuites d'automatisation (CDP) que Kasada repère
from patchright.async_api import BrowserContext, Page, Playwright, async_playwright

from cheaphops.core.config import HttpConfig
from cheaphops.core.models import Manifest
from cheaphops.fetch.types import FetchResult, HttpRequest, Transport, TransportError


class HttpxTransport:
    follows_redirects = False

    def __init__(self, cfg: HttpConfig) -> None:
        self._client = httpx.AsyncClient(timeout=cfg.timeout_s, follow_redirects=False)

    async def send(self, req: HttpRequest) -> FetchResult:
        try:
            r = await self._client.request(
                req.method, req.url, headers=list(req.headers), content=req.body
            )
        except httpx.HTTPError as e:
            raise TransportError(f"{type(e).__name__}: {e}") from e
        return FetchResult(str(r.url), r.status_code, tuple(r.headers.multi_items()), r.text, 1)

    async def aclose(self) -> None:
        await self._client.aclose()


class CurlTransport:
    follows_redirects = False

    def __init__(
        self, cfg: HttpConfig, rung: int = 2, cookies: dict[str, str] | None = None
    ) -> None:
        self._rung = rung
        self._session: AsyncSession[Any] = AsyncSession(
            impersonate=cfg.impersonate, timeout=cfg.timeout_s, cookies=cookies
        )

    async def send(self, req: HttpRequest) -> FetchResult:
        try:
            r = await self._session.request(
                req.method,  # type: ignore[arg-type]
                req.url,
                headers=list(req.headers),
                content=req.body,
                allow_redirects=False,
            )
        except curl_cffi.CurlError as e:
            raise TransportError(f"CurlError: {e}") from e
        headers = tuple((k, v or "") for k, v in r.headers.multi_items())
        return FetchResult(str(r.url), r.status_code, headers, r.text, self._rung)

    async def aclose(self) -> None:
        await self._session.close()


class StealthCookieTransport:
    """Rung 3 : une visite de `home_url` par le navigateur furtif fournit les cookies, réutilisés
    ensuite par curl_cffi (avec l'UA de son profil `impersonate`) pour toute la session."""

    follows_redirects = False

    def __init__(self, cfg: HttpConfig, manifest: Manifest) -> None:
        self._cfg, self._manifest = cfg, manifest
        self._curl: CurlTransport | None = None
        self._lock = asyncio.Lock()  # un seul amorçage même si plusieurs envois arrivent ensemble
        self._browser_requests = 0

    async def send(self, req: HttpRequest) -> FetchResult:
        async with self._lock:
            if self._curl is None:
                self._curl = await self._bootstrap()
        result = await self._curl.send(req)
        loaded, self._browser_requests = self._browser_requests, 0  # page d'amorçage, une fois
        return dataclasses.replace(result, browser_requests=loaded)

    async def _bootstrap(self) -> CurlTransport:
        from scrapling.fetchers import StealthyFetcher  # import lourd : seulement si le rung sert

        try:
            page = await StealthyFetcher.async_fetch(
                self._manifest.home_url,
                page_setup=lambda page: page.on("request", self._count),
                headless=True,  # jamais de fenêtre visible
                solve_cloudflare=False,  # §2.3 : aucun contournement de CAPTCHA
                disable_resources=True,
                timeout=self._cfg.timeout_s * 1000,
            )
        except Exception as e:  # Scrapling remonte des erreurs Playwright variées
            raise TransportError(f"stealth bootstrap: {e}") from e
        raw: Any = page.cookies  # tuple de dicts Playwright (async) ou dict selon le chemin
        cookies = dict(raw) if isinstance(raw, dict) else {c["name"]: c["value"] for c in raw}
        return CurlTransport(self._cfg, rung=3, cookies=cookies)

    async def aclose(self) -> None:
        if self._curl is not None:
            await self._curl.aclose()

    def _count(self, _: Any) -> None:
        self._browser_requests += 1


_FETCH_JS = """async ([url, method, headers, body]) => {
  const r = await fetch(url, {method, headers, body, credentials: "include"});
  return {status: r.status, url: r.url, headers: [...r.headers.entries()], text: await r.text()};
}"""


class BrowserTransport:
    """Rung 4 : Chromium furtif avec profil persistant ; les requêtes partent de la page
    elle-même, avec ses cookies, son empreinte et les en-têtes ajoutés par le SDK anti-bot."""

    follows_redirects = True

    def __init__(self, cfg: HttpConfig, manifest: Manifest) -> None:
        self._cfg, self._manifest = cfg, manifest
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None
        self._page: Page | None = None
        self._lock = asyncio.Lock()
        # requêtes de la page elle-même (chargement, XHR du site), hors URL que nous demandons ;
        # les préflights CORS (OPTIONS) de nos POST visent notre URL et ne sont donc pas comptés
        self._browser_requests = 0
        self._target = ""

    async def send(self, req: HttpRequest) -> FetchResult:
        try:
            async with self._lock:
                page = self._page or await self._open()
            body = req.body.decode() if req.body is not None else None
            sent = dict(req.headers) | await self._cookie_headers(req.url)
            self._target = req.url
            out = await page.evaluate(_FETCH_JS, [req.url, req.method, sent, body])
        except Exception as e:  # erreurs Playwright : navigateur, réseau, JS
            raise TransportError(f"browser: {e}") from e
        loaded, self._browser_requests = self._browser_requests, 0
        headers = tuple((k, v) for k, v in out["headers"])
        return FetchResult(
            out["url"], out["status"], headers, out["text"], 4, browser_requests=loaded
        )

    async def _cookie_headers(self, url: str) -> dict[str, str]:
        """En-têtes recopiés de cookies (CSRF double-submit), lus dans le contexte du navigateur."""
        if not self._manifest.cookie_headers or self._ctx is None:
            return {}
        jar = {c["name"]: unquote(c["value"]) for c in await self._ctx.cookies(url)}
        wanted = self._manifest.cookie_headers.items()
        return {header: jar[cookie] for header, cookie in wanted if cookie in jar}

    async def _open(self) -> Page:
        """Après un échec de chargement, seul `goto` est rejoué : relancer le navigateur sur un
        profil persistant encore ouvert échouerait (profil verrouillé)."""
        self._pw = self._pw or await async_playwright().start()
        self._ctx = self._ctx or await self._pw.chromium.launch_persistent_context(
            str(self._cfg.browser_dir / self._manifest.source),
            headless=True,  # jamais de fenêtre visible
        )
        page = await self._ctx.new_page()

        def count(request: Any) -> None:
            if request.url != self._target:
                self._browser_requests += 1

        page.on("request", count)
        await page.goto(self._manifest.home_url, timeout=self._cfg.timeout_s * 1000)
        self._page = page  # seulement une fois la page chargée, avec les cookies du site
        return page

    async def aclose(self) -> None:
        if self._ctx is not None:
            await self._ctx.close()
        if self._pw is not None:
            await self._pw.stop()


def default_transports(cfg: HttpConfig, manifest: Manifest) -> dict[int, Transport]:
    return {
        1: HttpxTransport(cfg),
        2: CurlTransport(cfg),
        3: StealthCookieTransport(cfg, manifest),
        4: BrowserTransport(cfg, manifest),
    }
