import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cheaphops.core.config import load_config
from cheaphops.fetch.transports import CurlTransport, HttpxTransport
from cheaphops.fetch.types import HttpRequest, Transport

pytestmark = pytest.mark.anyio
CFG = load_config(Path(__file__).parent.parent / "config.yaml", Path("/nonexistent")).http


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
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
