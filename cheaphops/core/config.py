from pathlib import Path
from typing import Annotated, Any, Self

import yaml
from pydantic import Field, model_validator

from cheaphops.core.models import GroundEdge, Iata, Model, Price, SearchDefaults


class HttpConfig(Model):
    timeout_s: Annotated[float, Field(gt=0)]
    vary_headers: list[str]  # headers qui changent la réponse : ils entrent dans la clé de cache
    explore_ttl_s: Annotated[int, Field(ge=0)]
    verify_ttl_s: Annotated[int, Field(ge=0)]


class ModelPrice(Model):
    """USD par million de tokens."""

    input: Price
    output: Price
    cache_read: Price
    cache_write: Price


class LlmCaps(Model):
    per_run_usd: Price
    pathfinder_run_usd: Price
    total_usd: Price

    @model_validator(mode="after")
    def _pathfinder_above_run(self) -> Self:
        if self.pathfinder_run_usd < self.per_run_usd:
            raise ValueError("pathfinder_run_usd must be >= per_run_usd")
        return self


class ModelRole(Model):
    model_id: str | None  # None tant que scripts/bedrock_check.py n'a pas été lancé
    price: ModelPrice


class LlmConfig(Model):
    region: str
    profile: str | None
    fast: ModelRole
    strong: ModelRole
    caps: LlmCaps


class SearchConfig(Model):
    defaults: SearchDefaults
    bound_slack: Annotated[float, Field(gt=0, le=1)]
    presets: dict[str, dict[str, Any]]

    @model_validator(mode="after")
    def _presets_valid(self) -> Self:
        for name in self.presets:
            self.preset(name)
        return self

    def preset(self, name: str) -> SearchDefaults:
        return SearchDefaults.model_validate(self.defaults.model_dump() | self.presets[name])


class Config(Model):
    db_path: Path
    log_level: str
    http: HttpConfig
    llm: LlmConfig
    search: SearchConfig


class MetroConfig(Model):
    radius_km: Annotated[float, Field(gt=0)]
    transfer_cost_eur: Price
    transfer_min: Annotated[int, Field(ge=0)]
    overrides: dict[str, list[Iata]]  # nom de métropole -> aéroports, prioritaire sur le rayon


class GroundConfig(Model):
    edges: list[GroundEdge]
    metro: MetroConfig

    @model_validator(mode="after")
    def _unique_pairs(self) -> Self:
        pairs = [frozenset((e.a, e.b)) for e in self.edges]
        if len(pairs) != len(set(pairs)):
            raise ValueError("duplicate ground edge (edges are bidirectional)")
        return self


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


def load_config(
    path: Path = Path("config.yaml"), local: Path = Path("config.local.yaml")
) -> Config:
    """config.yaml, puis les overrides de l'UI (config.local.yaml) par-dessus s'il existe."""
    data = _read(path)
    if local.exists():
        data = _merge(data, _read(local))
    return Config.model_validate(data)


def load_ground(path: Path = Path("ground.yaml")) -> GroundConfig:
    return GroundConfig.model_validate(_read(path))
