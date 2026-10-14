import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cheaphops.core.config import load_config
from cheaphops.core.models import Manifest
from cheaphops.fetch.transports import BrowserTransport, CurlTransport, HttpxTransport
from cheaphops.fetch.types import HttpRequest, Transport, TransportError

pytestmark = pytest.mark.anyio
MANIFEST = Manifest.model_validate({
    "source": "ryanair", "version": 1, "allowed_domains": ["ryanair.com"],
    "home_url": "https://www.ryanair.com/", "block_markers": [], "cookie_headers": {},
    "preferred_rung": 3, "rate_limit": {"min_interval_s": 1.5, "jitter_s": 1.0},
})  # fmt: skip
CFG = load_config(Path(__file__).parent.parent / "config.yaml", Path("/nonexistent")).http


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/headers":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(dict(self.headers)).encode().lower())
            return
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", "a=1")
        self.send_header("Set-Cookie", "b=2")
        self.end_headers()
        self.wfile.write(b'{"path": "%s"}' % self.path.encode())

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def base() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(params=["httpx", "curl"])
def transport(request: pytest.FixtureRequest) -> Transport:
    return HttpxTransport(CFG) if request.param == "httpx" else CurlTransport(CFG)


async def test_get_keeps_repeated_headers(base: str, transport: Transport) -> None:
    r = await transport.send(HttpRequest.build("GET", f"{base}/x", params={"d": "BGY"}))
    await transport.aclose()
    assert r.status == 200 and r.json() == {"path": "/x?d=BGY"}
    assert [v for k, v in r.headers if k.lower() == "set-cookie"] == ["a=1", "b=2"]


async def test_post_sends_json_body(base: str, transport: Transport) -> None:
    r = await transport.send(HttpRequest.build("POST", f"{base}/p", json_body={"a": 1}))
    await transport.aclose()
    assert r.json() == {"a": 1}


async def test_redirect_not_followed(base: str, transport: Transport) -> None:
    r = await transport.send(HttpRequest.build("GET", f"{base}/redirect"))
    await transport.aclose()
    assert (r.status, r.header("location")) == (302, "/elsewhere")


async def test_browser_rung_fetches_from_the_page(base: str, tmp_path: Path) -> None:
    manifest = MANIFEST
    # model_copy ne revalide pas : le manifeste exige https, le serveur de test est en http local
    local = manifest.model_copy(
        update={"source": "local", "home_url": f"{base}/home", "cookie_headers": {"x-csrf": "tok"}}
    )
    t = BrowserTransport(CFG.model_copy(update={"browser_dir": tmp_path}), local)
    try:
        got = await t.send(HttpRequest.build("GET", f"{base}/x", params={"d": "BGY"}))
        posted = await t.send(HttpRequest.build("POST", f"{base}/p", json_body={"a": 1}))
        page = t._page
        assert page is not None
        await page.context.add_cookies([{"name": "tok", "value": "abc", "url": base}])
        echoed = await t.send(HttpRequest.build("GET", f"{base}/headers"))
    finally:
        await t.aclose()
    assert (got.status, got.rung, got.json()) == (200, 4, {"path": "/x?d=BGY"})
    assert posted.json() == {"a": 1}
    assert echoed.json()["x-csrf"] == "abc"  # recopié du cookie, comme le jeton CSRF de Wizz
    assert (got.browser_requests, posted.browser_requests) == (1, 0)  # la page /home, une fois


async def test_browser_rung_retries_page_load_without_relaunching(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    launches: list[str] = []
    gotos: list[str] = []

    class Page:
        def on(self, event: str, handler: object) -> None:
            pass

        async def goto(self, url: str, **_: object) -> None:  # même signature utile que Page.goto
            gotos.append(url)
            if len(gotos) == 1:
                raise TimeoutError("goto timeout")

        async def evaluate(self, js: str, args: list[object]) -> dict[str, object]:
            return {"status": 200, "url": args[0], "headers": [], "text": "{}"}

    class Context:
        async def new_page(self) -> Page:
            return Page()

        async def close(self) -> None:
            pass

    class Chromium:
        async def launch_persistent_context(self, path: str, headless: bool) -> Context:
            launches.append(path)
            return Context()

    class Driver:
        chromium = Chromium()

        async def stop(self) -> None:
            pass

    class Starter:
        async def start(self) -> Driver:
            launches.append("driver")
            return Driver()

    monkeypatch.setattr("cheaphops.fetch.transports.async_playwright", Starter)
    manifest = MANIFEST
    t = BrowserTransport(CFG.model_copy(update={"browser_dir": tmp_path}), manifest)
    req = HttpRequest.build("GET", "https://www.ryanair.com/api/x")
    with pytest.raises(TransportError):
        await t.send(req)
    assert (await t.send(req)).status == 200
    assert len(launches) == 2 and len(gotos) == 2  # un driver, un profil ; seul goto est rejoué
