import logging
import sqlite3
from dataclasses import dataclass
from datetime import date

from cheaphops.core.config import Config
from cheaphops.core.models import Manifest
from cheaphops.fetch.http import CtxHttp, Throttle


@dataclass(frozen=True)
class Ctx:
    """Ce qu'une recette reçoit. Elle n'a pas d'autre accès au réseau que `http`."""

    config: Config
    http: CtxHttp
    log: logging.Logger
    run_id: str
    today: date  # date du run : une recette ne demande jamais de dates passées


def make_ctx(
    config: Config,
    http_conn: sqlite3.Connection,
    manifest: Manifest,
    throttle: Throttle,
    run_id: str,
    today: date,
) -> Ctx:
    http = CtxHttp(http_conn, manifest, config.http, throttle)
    return Ctx(config, http, logging.getLogger(f"cheaphops.{manifest.source}"), run_id, today)
