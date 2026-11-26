from datetime import date, time, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, model_validator

from cheaphops.core.models import Iata, Model, Price

ROOT = Path(__file__).resolve().parents[2]  # racine du dépôt, quel que soit le dossier courant


class Google(Model):
    enabled: bool  # désactivé par défaut : 24+ requêtes pour un échantillon de hubs
    """Google Flights ne sait pas « partir vers n'importe où » : une requête = un aller simple
    origine -> destination à une date. On échantillonne donc des destinations de hubs."""

    destinations: list[Iata]
    dates: Annotated[int, Field(ge=1)]  # dates échantillonnées, réparties dans la fenêtre


class Airbaltic(Model):
    enabled: bool
    requests: Annotated[int, Field(ge=1)]  # max par recherche : allers des routes, puis retours


class Kiwi(Model):
    enabled: bool
    returns: Annotated[int, Field(ge=0)]  # destinations « n'importe où » dont on cherche le retour


class Period(Model):
    """Plage de dates choisie dans le calendrier : aller et retour y tombent tous les deux."""

    start: date
    end: date

    @model_validator(mode="after")
    def _ordered(self) -> "Period":
        if self.end < self.start:
            raise ValueError(f"plage {self.start} -> {self.end} : la fin précède le début")
        return self


def _merge_periods(periods: list[Period]) -> list[Period]:
    """Triées, et fusionnées si elles se touchent : deux plages contiguës n'en font qu'une."""
    out: list[Period] = []
    for p in sorted(periods, key=lambda p: p.start):
        if out and p.start <= out[-1].end + timedelta(days=1):
            out[-1] = Period(start=out[-1].start, end=max(out[-1].end, p.end))
        else:
            out.append(p)
    return out


class LastMinute(Model):
    origins: Annotated[list[Iata], Field(min_length=1)]
    days: Annotated[int, Field(ge=0, le=60)]  # départs de J+0 à J+days (sans `periods`)
    periods: list[Period]  # plages choisies au calendrier ; vide : mode « J+0 à J+days »
    # aéroports visés ; vide : n'importe où. Borné : chaque cible coûte des requêtes par origine
    destinations: Annotated[list[Iata], Field(max_length=10)]
    connections: bool  # vols avec une escale (billets séparés) via les hubs les moins chers
    connection_min_hours: Annotated[float, Field(ge=1)]  # escale minimale, même aéroport, même jour
    cache_minutes: Annotated[int, Field(ge=0)]  # réponses des compagnies réutilisées ; 0 : coupé
    max_nights: Annotated[int, Field(ge=0)]
    weekend: bool  # départ vendredi/samedi, retour dimanche ou lundi avant `weekend_return_before`
    weekend_return_before: time  # heure locale d'arrivée du retour du lundi
    top: Annotated[int, Field(ge=1)]
    optional_origins: list[Iata]  # villes voisines, avec bus depuis le domicile (ground.yaml)
    oneways_max: Annotated[int, Field(ge=1)]  # allers simples gardés pour la vue « allers simples »
    alternatives: Annotated[
        int, Field(ge=1)
    ]  # dates proposées par destination (option « tout voir »)
    verify_routes: Annotated[int, Field(ge=0)]  # routes d'agrégateurs vérifiées chez la compagnie
    wizz_routes: Annotated[int, Field(ge=0)]  # routes Wizz dont on lit le farechart
    pause_s: tuple[float, float]  # pause aléatoire entre deux requêtes d'une même source
    request_budget: Annotated[int, Field(ge=1)]
    google: Google
    airbaltic: Airbaltic  # API du site : prix par jour sur un an, une requête par route et sens
    kiwi: Kiwi  # agrégateur : compagnies hors Ryanair/Wizz et vols avec escale vendus par Kiwi

    @model_validator(mode="before")
    @classmethod
    def _normalize_periods(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("periods"):
            periods = [Period.model_validate(p) for p in data["periods"]]
            data = data | {"periods": _merge_periods(periods)}
        return data


class Config(Model):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    lastminute: LastMinute


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def with_overrides(base: LastMinute, update: dict[str, Any]) -> LastMinute:
    """Réglages modifiés (CLI, UI), revalidés : `model_copy` laisserait passer days=100."""
    return LastMinute.model_validate(_merge(base.model_dump(), update))


def _read(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")
    return data


def load_config(path: Path = ROOT / "config.yaml", local: Path | None = None) -> Config:
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


def load_ground(path: Path = ROOT / "ground.yaml") -> Ground:
    return Ground.model_validate(_read(path))
