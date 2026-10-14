"""Classification déterministe des réponses (§7) et choix du rung de départ."""

from enum import StrEnum

from cheaphops.core.config import HttpConfig
from cheaphops.fetch.types import FetchResult

RUNGS = (1, 2, 3, 4)


class Outcome(StrEnum):
    OK = "ok"
    BLOCKED = "blocked"  # anti-bot : monter d'un rung
    CAPTCHA = "captcha"  # source bloquée avec backoff, jamais résolu
    RATE_LIMITED = "rate_limited"  # 429 : backoff exponentiel, même rung
    FAILED = "failed"  # 404, 5xx… : rien à gagner à changer de rung


def classify(r: FetchResult, cfg: HttpConfig, source_markers: list[str]) -> Outcome:
    """`source_markers` : signatures de refus propres à une source (manifeste), ex. le
    `409 Availability declined` de Ryanair."""
    ok = 200 <= r.status < 300
    is_json = "json" in (r.header("content-type") or "")
    body = "" if ok and is_json else r.text[:50_000].lower()  # données servies : jamais un mur
    if any(m.lower() in body for m in cfg.captcha_markers):
        return Outcome.CAPTCHA
    if r.status == 429:
        return Outcome.RATE_LIMITED
    markers = [*cfg.block_markers, *source_markers]
    if r.status in (401, 403) or any(m.lower() in body for m in markers):
        return Outcome.BLOCKED
    return Outcome.OK if ok else Outcome.FAILED


def start_rung(stats: dict[int, tuple[int, int]], preferred: int) -> int:
    """Rung au meilleur taux de succès lissé (s+1)/(n+2) ; un rung jamais essayé vaut 0.5.
    Égalité : le rung préféré du manifeste, puis le moins cher.
    """
    # shortcut: heuristique déterministe ; Thompson sampling (Beta) prévu en phase 5

    def score(r: int) -> tuple[float, bool, int]:
        s, f = stats.get(r, (0, 0))
        return ((s + 1) / (s + f + 2), r == preferred, -r)

    return max(RUNGS, key=score)
