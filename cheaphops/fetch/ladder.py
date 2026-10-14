"""Classification déterministe des réponses (§7) et choix du rung de départ."""

from enum import StrEnum

from cheaphops.core.config import HttpConfig
from cheaphops.fetch.types import FetchResult

RUNGS = (1, 2, 3, 4)
WALL_MAX = 100_000  # taille au-delà de laquelle une page 2xx n'est pas un mur anti-bot


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
    # Une réponse 2xx en JSON, ou une vraie page (au-delà de WALL_MAX caractères), est servie :
    # un mur anti-bot est une petite page. On lit alors tout le corps, pas un préfixe.
    served = ok and (is_json or len(r.text) > WALL_MAX)
    body = "" if served else r.text.lower()
    if any(m.lower() in body for m in cfg.captcha_markers):
        return Outcome.CAPTCHA
    # avant le 429 : certains anti-bots (Kasada) répondent 429 avec une page de défi
    if any(m.lower() in body for m in [*cfg.block_markers, *source_markers]):
        return Outcome.BLOCKED
    if r.status == 429:
        return Outcome.RATE_LIMITED
    if r.status in (401, 403):
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
