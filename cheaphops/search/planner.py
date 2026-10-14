"""Budget de requêtes de scraping d'une recherche (§10.4, heuristique de phase 1)."""


class Budget:
    """Accorde le réseau requête par requête, jusqu'au plafond de la phase en cours : l'Explore
    laisse une réserve au Verify. Le cache, servi avant toute demande, reste gratuit.
    Une montée de rung renvoie la même requête sans redemander : l'accord vaut pour la requête.
    shortcut: arrêt net au plafond ; un bandit sur l'historique des prix (ex-phase 5) répartirait
    mieux les requêtes entre routes"""

    def __init__(self, limit: int, verify_reserve: float) -> None:
        self.limit = limit
        self.cap = int(limit * (1 - verify_reserve))  # plafond de l'Explore, relevé au Verify
        self.spent = 0

    def allow(self) -> bool:
        if self.spent >= self.cap:
            return False
        self.spent += 1
        return True

    def start_verify(self) -> None:
        self.cap = self.limit

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit
