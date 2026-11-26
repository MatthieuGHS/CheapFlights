"""Construit cheaphops/lastminute/airports.json, la table des aéroports de l'app.

Sources :
- OurAirports (domaine public), téléchargé : aéroports à vols réguliers, code IATA, nom, pays,
  position ;
- scripts/wikidata.json, extrait figé de Wikidata (CC0) : pour chaque aéroport, les villes
  desservies (P931, en français, la plus peuplée d'abord) et leurs noms dans d'autres langues.
  OurAirports ne donne que la commune (« Orio al Serio » pour BGY, « Segrate » pour LIN).
  Extrait une fois (requêtes SPARQL sur P238 -> P931, lieux habités, libellés fr puis
  en/de/it/es/pl) et gardé ici : le service est trop instable pour en dépendre à chaque fois.

Usage : uv run python scripts/build_airports.py
"""

import csv
import io
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"
HERE = Path(__file__).resolve().parent
WIKIDATA = HERE / "wikidata.json"
OUT = HERE.parent / "cheaphops" / "lastminute" / "airports.json"
SIZES = {"large_airport": "L", "medium_airport": "M", "small_airport": "S"}


def commune(municipality: str) -> str:
    """« Paris (Roissy-en-France, Val-d'Oise) » -> « Paris »."""
    return re.sub(r"\s*\(.*\)$", "", municipality).strip()


# agglomérations et régions que Wikidata range aussi parmi les villes desservies
AREA = re.compile(
    r"(?i)communaut|agglom|m[ée]tropol|tricit|aire urbaine|r[ée]gion|comt[ée]|district|^grand "
)


def fold(s: str) -> str:
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().casefold()


def pick_city(served: list[str], local: str) -> str | None:
    """La ville affichée parmi les villes desservies (la plus peuplée d'abord) :
    1. sans les agglomérations ni les régions ; s'il n'y a que ça, aucune : la commune d'OurAirports
       vaudra mieux (OAK : Oakland, pas « région de la baie de San Francisco ») ;
    2. sans un nom qui en contient un autre (« communauté urbaine de Copenhague ») ;
    3. la commune d'OurAirports si elle y est (GDN : Gdańsk, pas « Tricité ») ;
    4. sinon la plus peuplée (BGY : Bergame)."""
    cities = [c for c in served if not AREA.search(c)]
    if not cities:
        return None
    cities = [c for c in cities if not any(o != c and fold(o) in fold(c) for o in cities)] or cities
    same = [c for c in cities if fold(c) == fold(local)]
    return (same or cities)[0]


def build(airports_csv: str, wikidata: dict[str, dict[str, list[str]]]) -> list[dict[str, object]]:
    rank = {"L": 0, "M": 1, "S": 2}
    best: dict[str, dict[str, object]] = {}
    for r in csv.DictReader(io.StringIO(airports_csv)):
        code, size = r["iata_code"], SIZES.get(r["type"])
        if not (size and r["scheduled_service"] == "yes" and re.fullmatch(r"[A-Z]{3}", code)):
            continue
        wd = wikidata.get(code, {})
        served, names = wd.get("served", []), wd.get("names", [])
        local = commune(r["municipality"])
        city = pick_city(served, local) or local or r["name"]
        keywords = (k.strip() for k in r["keywords"].split(","))
        alt = {*served, local, *keywords, *names} - {city, ""}
        row = {
            "iata": code, "city": city, "name": r["name"], "country": r["iso_country"],
            "lat": round(float(r["latitude_deg"]), 3), "lon": round(float(r["longitude_deg"]), 3),
            "size": size, "alt": sorted(alt),
        }  # fmt: skip
        old = best.get(code)
        if old is None or rank[size] < rank[str(old["size"])]:
            best[code] = row
    return sorted(best.values(), key=lambda a: str(a["iata"]))


def main() -> None:
    req = urllib.request.Request(OURAIRPORTS, headers={"User-Agent": "cheaphops-airports-build"})
    with urllib.request.urlopen(req, timeout=120) as r:
        airports_csv = r.read().decode("utf8")
    wikidata = json.loads(WIKIDATA.read_text(encoding="utf8"))
    table = build(airports_csv, wikidata)
    OUT.write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"{len(table)} aéroports -> {OUT}")


if __name__ == "__main__":
    main()
