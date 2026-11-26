"""Table des aéroports de l'app, construite par scripts/build_airports.py (OurAirports pour les
aéroports, Wikidata pour la ville desservie, en français)."""

import gzip
import json
from functools import cache
from pathlib import Path
from typing import Any

TABLE = Path(__file__).with_name("airports.json")


@cache
def table() -> list[dict[str, Any]]:
    """Sans fichier lisible, liste vide : l'UI affiche alors les codes et rien n'est refusé."""
    try:
        rows = json.loads(TABLE.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and "iata" in r and "city" in r]


@cache
def cities() -> dict[str, str]:
    return {a["iata"]: a["city"] for a in table()}


@cache
def table_gzip() -> bytes:
    """La table compressée une fois (≈ 150 Ko au lieu de 590) pour l'UI."""
    return gzip.compress(json.dumps(table(), ensure_ascii=False).encode())


def unknown(codes: list[str]) -> list[str]:
    """Codes absents de la table (faute de frappe) ; aucun si la table manque."""
    known = cities()
    return [c for c in codes if known and c not in known]
