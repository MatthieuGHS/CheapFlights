"""Code IATA -> ville, depuis la base OurAirports livrée avec ryanair-py (noms en anglais)."""

import csv
import io
from functools import cache
from importlib.resources import files


@cache
def cities() -> dict[str, str]:
    """Aéroports à vols réguliers seulement : un même code peut aussi désigner un aérodrome. Sans
    le fichier (ryanair-py changé), dictionnaire vide : l'UI affiche alors le code."""
    try:
        text = (files("ryanair") / "airports.csv").read_text(encoding="utf8")
    except (OSError, ModuleNotFoundError):
        return {}
    out: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text)):
        code, city = row["iata_code"], row["municipality"]
        if code and city and row["scheduled_service"] == "yes":
            out.setdefault(code, city)
    return out
