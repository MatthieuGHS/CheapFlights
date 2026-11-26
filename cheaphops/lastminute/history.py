"""Historique local : le top 10 de chaque recherche, écrit sur disque pour garder les liens."""

import json
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder

from cheaphops.core.config import ROOT, LastMinute
from cheaphops.lastminute.run import Result

HISTORY = ROOT / "data" / "history"
KEEP = 10
ID = re.compile(r"[0-9a-f]{12}")


def top(r: Result, n: int = KEEP) -> Result:
    """Le résultat coupé à `n` par catégorie, même forme : l'UI l'affiche comme une recherche."""
    periods = []
    for p in r.periods:
        shown = {t.out.destination for t in p.roundtrips[:n]}
        periods.append(replace(
            p,
            roundtrips=p.roundtrips[:n],
            alternatives={d: g for d, g in p.alternatives.items() if d in shown},
            calendars={d: c for d, c in p.calendars.items() if d in shown},
        ))  # fmt: skip
    return replace(r, oneways=r.oneways[:n], periods=periods, deals=r.deals[:n])


def save(
    run_id: str, at: datetime, params: LastMinute, result: Result, directory: Path = HISTORY
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{at:%Y%m%d-%H%M%S}-{run_id}.json"
    body = jsonable_encoder({"id": run_id, "at": at, "params": params, "result": top(result)})
    tmp = path.with_suffix(".tmp")  # écrit puis renommé : jamais de fichier à moitié écrit
    tmp.write_text(json.dumps(body, ensure_ascii=False))
    tmp.replace(path)
    return path


def entries(directory: Path = HISTORY) -> list[dict[str, Any]]:
    """Résumés, la plus récente d'abord ; un fichier illisible est ignoré, pas fatal."""
    out = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            body = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        p, r = body["params"], body["result"]
        totals = [
            t["out"]["price"] + t["back"]["price"] for q in r["periods"] for t in q["roundtrips"]
        ]
        out.append({
            "id": body["id"], "at": body["at"], "origins": p["origins"], "days": p["days"],
            "periods": p["periods"], "weekend": p["weekend"], "best": min(totals, default=None),
            "count": len(totals),
        })  # fmt: skip
    return out


def load(run_id: str, directory: Path = HISTORY) -> dict[str, Any] | None:
    if not ID.fullmatch(run_id):  # l'id finit dans un nom de fichier : rien d'autre ne passe
        return None
    path = next(directory.glob(f"*-{run_id}.json"), None)
    return json.loads(path.read_text()) if path else None
