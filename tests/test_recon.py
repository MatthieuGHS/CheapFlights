from cheaphops.context.compress import json_skeleton
from cheaphops.recon.analyze import Captured, candidate, signals, url_template, visible_prices

FARES = {
    "outbound": {"fares": [{"day": "2026-11-06", "price": {"value": 19.99}, "arrival": "BGY"}]}
}


def test_signals_need_iata_under_airport_key_and_price_under_price_key() -> None:
    assert signals(FARES) == (1, 1)
    assert signals({"currency": "EUR", "count": 12}) == (0, 0)


def test_candidate_filters_by_goal() -> None:
    routes = Captured("https://x.com/api/routes/VNO", "GET", {}, None, 200, [{"iataCode": "BGY"}])
    assert candidate(routes, needs_price=True) is None
    c = candidate(routes, needs_price=False)
    assert c is not None and c["url_template"] == "https://x.com/api/routes/{iata}"


def test_candidate_drops_noise_headers_keeps_api_ones() -> None:
    headers = {"cookie": "s=1", "user-agent": "x", "x-api-key": "k", "content-type": "a/json"}
    c = candidate(Captured("https://x.com/f?d=1", "POST", headers, "{}", 200, FARES), True)
    assert c is not None
    assert c["headers"] == {"x-api-key": "k", "content-type": "a/json"}
    assert c["params"] == {"d": "1"}


def test_url_template_and_skeleton() -> None:
    assert url_template("https://a.com/v4/VNO/BGY/2026-11-01/x") == (
        "https://a.com/v4/{iata}/{iata}/{date}/x"
    )
    assert json_skeleton({"a": [1, 2, 3], "s": "x" * 50}) == {
        "a": ["num 1", "… 3 items"],
        "s": f"str {'x' * 40!r}…",
    }


def test_visible_prices() -> None:
    assert visible_prices("from €19.99 or 25,00 EUR") == ["€19.99", "25,00 EUR"]


def test_capture_follows_new_tabs_and_reads_page_text() -> None:
    import asyncio
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from cheaphops.recon.__main__ import capture

    class Site(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            api = self.path.startswith("/api")
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if api else "text/html")
            self.end_headers()
            if api:
                self.wfile.write(b'{"to": "BGY", "price": 12}')
            elif self.path == "/":  # les résultats s'ouvrent dans un nouvel onglet, comme Wizz
                self.wfile.write(b"<script>window.open('/results')</script>")
            else:
                self.wfile.write(b"<p>EUR 12.00</p><script>fetch('/api')</script>")

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        captured, text, _, document = asyncio.run(capture(url, False, 3, False, [], False))
    finally:
        server.shutdown()
    assert [c.body for c in captured] == [{"to": "BGY", "price": 12}]
    assert text == "EUR 12.00" and document.startswith("HTTP 200")
