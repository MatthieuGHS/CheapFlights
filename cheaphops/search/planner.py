"""Budget de requêtes de scraping d'une recherche (§10.4, heuristique de phase 1)."""

from cheaphops.fetch.http import CtxHttp


class Budget:
    """Compte les requêtes réellement envoyées (le cache est gratuit) et ferme le réseau au
    plafond de la phase en cours : l'Explore laisse une réserve au Verify.
    shortcut: arrêt net au plafond ; un bandit sur l'historique des prix (ex-phase 5) répartirait
    mieux les requêtes entre routes"""

    def __init__(self, limit: int, verify_reserve: float) -> None:
        self.limit = limit
        self.cap = int(limit * (1 - verify_reserve))  # plafond de l'Explore, relevé au Verify
        self.clients: list[CtxHttp] = []

    @property
    def spent(self) -> int:
        return sum(c.sent for c in self.clients)

    def allow(self) -> bool:
        return self.spent < self.cap

    def start_verify(self) -> None:
        self.cap = self.limit

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit
