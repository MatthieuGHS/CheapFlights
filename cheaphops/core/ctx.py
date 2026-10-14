import logging
from dataclasses import dataclass

from cheaphops.core.config import Config
from cheaphops.fetch.http import CtxHttp


@dataclass(frozen=True)
class Ctx:
    """Ce qu'une recette reçoit. Elle n'a pas d'autre accès au réseau que `http`."""

    config: Config
    http: CtxHttp
    log: logging.Logger
    run_id: str
