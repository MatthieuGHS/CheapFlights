"""Budget de requêtes de scraping d'une recherche (§10.4, heuristique de phase 1)."""

from collections.abc import Iterable

from cheaphops.fetch.http import CtxHttp


class Budget:
    """Compte les requêtes réellement envoyées (les réponses servies par le cache sont gratuites).
    shortcut: arrêt net au plafond ; bandit sur l'historique des prix prévu en phase 5 (en pause)"""

    def __init__(self, limit: int, clients: Iterable[CtxHttp]) -> None:
        self.limit = limit
        self._clients = list(clients)

    @property
    def spent(self) -> int:
        return sum(c.sent for c in self._clients)

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit
