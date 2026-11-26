"""Cache disque des réponses brutes des compagnies : une recherche relancée dans l'heure ne
repaie pas les mêmes requêtes (budget libre pour d'autres routes, moins de risque de blocage)."""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from cheaphops.core.config import ROOT

DIR = ROOT / "data" / "cache"
# shortcut: réglé une fois par recherche depuis la config (run.py) ; un seul process, une
# recherche à la fois. Passer en paramètre si plusieurs recherches tournent en parallèle.
TTL_S = 0  # 0 : cache coupé (défaut, donc jamais actif dans les tests)


def _path(parts: tuple[Any, ...]) -> Path:
    digest = hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()
    return DIR / f"{digest}.json"


def get(*parts: Any) -> Any:
    """La réponse gardée pour cette clé si elle a moins de TTL_S secondes, sinon None."""
    if TTL_S <= 0:
        return None
    try:
        body = json.loads(_path(parts).read_text())
        return body["value"] if time.time() - body["at"] < TTL_S else None
    except (OSError, ValueError, KeyError, TypeError):  # absente ou abîmée : on refait la requête
        return None


def put(value: Any, *parts: Any) -> None:
    if TTL_S <= 0:
        return
    path = _path(parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{time.monotonic_ns()}.tmp")  # threads : un fichier temporaire chacun
    tmp.write_text(json.dumps({"at": time.time(), "value": value}))
    tmp.replace(path)
