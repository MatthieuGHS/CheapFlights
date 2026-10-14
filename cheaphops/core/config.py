from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field

from cheaphops.core.models import Iata, Model, Price


class Google(Model):
    enabled: bool  # désactivé par défaut : 24+ requêtes pour un échantillon de hubs
    """Google Flights ne sait pas « partir vers n'importe où » : une requête = un aller simple
    origine -> destination à une date. On échantillonne donc des destinations de hubs."""

    destinations: list[Iata]
    dates: Annotated[int, Field(ge=1)]  # dates échantillonnées, réparties dans la fenêtre


class LastMinute(Model):
    origins: Annotated[list[Iata], Field(min_length=1)]
    days: Annotated[int, Field(ge=0, le=60)]  # départs de J+0 à J+days
    max_nights: Annotated[int, Field(ge=0)]
    top: Annotated[int, Field(ge=1)]
    optional_origins: list[Iata]  # villes voisines, avec bus depuis le domicile (ground.yaml)
    return_below_eur: Annotated[float, Field(ge=0)]  # retours cherchés si l'aller coûte moins
    wizz_routes: Annotated[int, Field(ge=0)]  # routes Wizz dont on lit le farechart
    pause_s: tuple[float, float]  # pause aléatoire entre deux requêtes d'une même source
    request_budget: Annotated[int, Field(ge=1)]
    google: Google


class Config(Model):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
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


class GroundBus(Model):
    cost_eur: Price
    duration_min: Annotated[int, Field(gt=0)]


class Ground(Model):
    home: Iata
    buses: dict[Iata, GroundBus]

    def cost(self, airport: str) -> Decimal:
        """Bus aller simple depuis le domicile ; 0 pour le domicile lui-même."""
        return self.buses[airport].cost_eur if airport in self.buses else Decimal(0)


def load_ground(path: Path = Path("ground.yaml")) -> Ground:
    return Ground.model_validate(_read(path))
