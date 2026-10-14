from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Iata = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Domain = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Price = Annotated[Decimal, Field(ge=0)]


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())


class RateLimit(Model):
    min_interval_s: Annotated[float, Field(gt=0)]
    jitter_s: Annotated[float, Field(ge=0)]


class Manifest(Model):
    source: str
    version: Annotated[int, Field(ge=1)]
    allowed_domains: Annotated[list[Domain], Field(min_length=1)]
    home_url: Annotated[str, StringConstraints(pattern=r"^https://")]  # amorce des rungs 3-4
    block_markers: list[str]  # refus anti-bot propres à la source, en plus de ceux de la config
    cookie_headers: dict[str, str]  # en-tête -> cookie à recopier (CSRF double-submit), rung 4
    preferred_rung: Annotated[int, Field(ge=1, le=4)]
    rate_limit: RateLimit
