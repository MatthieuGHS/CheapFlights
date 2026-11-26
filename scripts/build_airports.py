"""Construit cheaphops/lastminute/airports.json, la table des aéroports de l'app.

Sources ouvertes, téléchargées à chaque construction :
- OurAirports (domaine public) : aéroports à vols réguliers, code IATA, nom, pays, position ;
- Wikidata (CC0) : la ville desservie (P931), en français. OurAirports ne donne que la commune
  (« Orio al Serio » pour BGY, « Segrate » pour LIN).

Usage : uv run python scripts/build_airports.py  (environ 2 minutes, surtout Wikidata)
"""

import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data/airports.csv"
WIKIDATA = "https://query.wikidata.org/sparql"
OUT = Path(__file__).resolve().parents[1] / "cheaphops" / "lastminute" / "airports.json"
AGENT = "cheaphops-airports-build/1.0"
SIZES = {"large_airport": "L", "medium_airport": "M", "small_airport": "S"}
# villes desservies, lieux habités seulement (sinon « Lombardie » pour MXP)
SERVED = """SELECT ?iata ?cityLabel ?pop WHERE {
  ?a wdt:P238 ?iata; wdt:P931 ?city.
  FILTER EXISTS { ?city wdt:P31/wdt:P279* wd:Q486972 }
  OPTIONAL { ?city wdt:P1082 ?pop }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en,mul". }
}"""


def fetch(url: str, accept: str = "text/csv", tries: int = 4) -> str:
    """Wikidata coupe parfois cette requête lourde (504) ou limite le débit (429) : reprises
    espacées, au rythme demandé par le serveur."""
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": accept})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return str(r.read().decode("utf8"))
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 30 * (attempt + 1)
            print(f"  {e.code}, nouvel essai dans {wait} s…")
            time.sleep(wait)
    raise AssertionError("unreachable")


def served_cities(text: str) -> dict[str, list[str]]:
    """IATA -> villes desservies, la plus peuplée d'abord ; un libellé resté « Q123 » est écarté."""
    found: dict[str, dict[str, float]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        city = row["cityLabel"]
        if re.fullmatch(r"Q\d+", city):
            continue
        pops = found.setdefault(row["iata"], {})
        pops[city] = max(pops.get(city, 0.0), float(row["pop"] or 0))
    return {k: sorted(v, key=lambda c: -v[c]) for k, v in found.items()}


def commune(municipality: str) -> str:
    """« Paris (Roissy-en-France, Val-d'Oise) » -> « Paris »."""
    return re.sub(r"\s*\(.*\)$", "", municipality).strip()


def build(airports_csv: str, cities: dict[str, list[str]]) -> list[dict[str, object]]:
    rank = {"L": 0, "M": 1, "S": 2}
    best: dict[str, dict[str, object]] = {}
    for r in csv.DictReader(io.StringIO(airports_csv)):
        code, size = r["iata_code"], SIZES.get(r["type"])
        if not (size and r["scheduled_service"] == "yes" and re.fullmatch(r"[A-Z]{3}", code)):
            continue
        served = cities.get(code, [])
        local = commune(r["municipality"])
        city = served[0] if served else local or r["name"]
        alt = {*served[1:], local, *(k.strip() for k in r["keywords"].split(","))} - {city, ""}
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
    print("OurAirports…")
    airports_csv = fetch(OURAIRPORTS)
    print("Wikidata (villes desservies)…")
    cities = served_cities(fetch(f"{WIKIDATA}?{urllib.parse.urlencode({'query': SERVED})}"))
    table = build(airports_csv, cities)
    OUT.write_text(json.dumps(table, ensure_ascii=False, separators=(",", ":")) + "\n")
    named = sum(1 for a in table if a["iata"] in cities)
    print(f"{len(table)} aéroports ({named} avec ville Wikidata) -> {OUT}")


if __name__ == "__main__":
    main()
