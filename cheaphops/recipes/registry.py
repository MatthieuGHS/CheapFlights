"""Chargement des recettes : `cheaphops/recipes/<source>/v<N>/{manifest.yaml, recipe.py}`.
La version retenue est la plus haute dont le statut est `active`."""

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from cheaphops.core.models import Manifest, RecipeStatus

RECIPES_DIR = Path(__file__).parent


@dataclass(frozen=True)
class LoadedRecipe:
    manifest: Manifest
    recipe: Any  # n'implémente que les Protocols de base.py listés dans manifest.capabilities


def _versions(source: str) -> list[tuple[int, Path]]:
    dirs = (RECIPES_DIR / source).glob("v[0-9]*")
    return sorted(((int(d.name[1:]), d) for d in dirs if d.is_dir()), reverse=True)


def load(source: str) -> LoadedRecipe:
    for version, path in _versions(source):
        manifest = Manifest.model_validate(yaml.safe_load((path / "manifest.yaml").read_text()))
        if manifest.status is RecipeStatus.ACTIVE:
            module = importlib.import_module(f"cheaphops.recipes.{source}.v{version}.recipe")
            return LoadedRecipe(manifest, module.Recipe())
    raise LookupError(f"no active recipe for {source}")


def active_sources() -> list[str]:
    return sorted(d.name for d in RECIPES_DIR.iterdir() if d.is_dir() and _versions(d.name))
