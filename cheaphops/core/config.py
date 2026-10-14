from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field

from cheaphops.core.models import Iata, Model


class HttpConfig(Model):
    timeout_s: Annotated[float, Field(gt=0)]
    vary_headers: list[str]  # headers qui changent la réponse : ils entrent dans la clé de cache
    explore_ttl_s: Annotated[int, Field(ge=0)]
    verify_ttl_s: Annotated[int, Field(ge=0)]
    max_attempts: Annotated[int, Field(ge=1)]
    rate_limited_backoff_s: Annotated[float, Field(gt=0)]  # 429 : doublé à chaque essai
    blocked_backoff_s: Annotated[float, Field(gt=0)]  # source bloquée : doublé à chaque blocage
    block_markers: list[str]  # corps de réponse d'un mur anti-bot -> monter d'un rung
    captcha_markers: list[str]  # CAPTCHA -> source bloquée, jamais résolu
    impersonate: str  # profil TLS curl_cffi des rungs 2 et 3
    browser_dir: Path  # profils persistants du rung 4


class Google(Model):
    """Google Flights ne sait pas « partir vers n'importe où » : une requête = un aller simple
    origine -> destination à une date. On échantillonne donc des destinations de hubs."""

    destinations: list[Iata]
    dates: Annotated[int, Field(ge=1)]  # dates échantillonnées, réparties dans la fenêtre


class LastMinute(Model):
    origins: Annotated[list[Iata], Field(min_length=1)]
    days: Annotated[int, Field(ge=0)]  # départs de J+0 à J+days
    max_nights: Annotated[int, Field(ge=0)]
    top: Annotated[int, Field(ge=1)]
    return_candidates: Annotated[int, Field(ge=0)]  # destinations dont on cherche le retour
    request_budget: Annotated[int, Field(ge=1)]
    google: Google


class Config(Model):
    db_path: Path
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    http: HttpConfig
    lastminute: LastMinute


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def load_config(path: Path = Path("config.yaml"), local: Path | None = None) -> Config:
    """config.yaml, puis les overrides de l'UI (config.local.yaml voisin) par-dessus s'il existe."""
    data = _read(path)
    local = local or path.with_name("config.local.yaml")
    if local.exists():
        data = _merge(data, _read(local))
    return Config.model_validate(data)
