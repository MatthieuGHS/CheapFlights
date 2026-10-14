"""Outils des tests de contrat : un Ctx dont le réseau sert des fixtures, jamais le live."""

import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

from cheaphops.core.config import Config, load_config
from cheaphops.core.ctx import Ctx
from cheaphops.core.db import connect
from cheaphops.core.models import Manifest
from cheaphops.fetch.http import CtxHttp, Throttle
from cheaphops.fetch.types import FetchResult, HttpRequest

ROOT = Path(__file__).parent.parent.parent
TODAY = date(2026, 10, 14)  # date des captures recon : les fixtures restent valides ensuite
JSON = (("content-type", "application/json"),)


class FixtureTransport:
    """`route(req)` renvoie le chemin de la fixture à servir, ou None pour une 404."""

    follows_redirects = False

    def __init__(self, route: Callable[[HttpRequest], Path | None]) -> None:
        self.route = route
        self.sent: list[HttpRequest] = []

    async def send(self, req: HttpRequest) -> FetchResult:
        self.sent.append(req)
        path = self.route(req)
        if path is None:
            return FetchResult(req.url, 404, JSON, "{}", 1)
        kind = "text/html" if path.suffix == ".html" else "application/json"
        return FetchResult(req.url, 200, (("content-type", kind),), path.read_text(), 1)

    async def aclose(self) -> None:
        pass


async def _no_sleep(_: float) -> None:
    pass


def fixture_ctx(manifest: Manifest, transport: FixtureTransport) -> Ctx:
    config: Config = load_config(ROOT / "config.yaml", ROOT / "absent.yaml")
    throttle = Throttle(sleep=_no_sleep)
    http = CtxHttp(
        connect(":memory:"),
        manifest,
        config.http,
        throttle,
        transports=dict.fromkeys((1, 2, 3, 4), transport),
        sleep=_no_sleep,
    )
    return Ctx(config, http, logging.getLogger("test"), "test", TODAY)
