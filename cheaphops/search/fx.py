"""Taux de change BCE (EUR de référence), mis en cache comme une réponse Explore."""

import re
from decimal import Decimal

from cheaphops.core.models import Manifest
from cheaphops.fetch.http import CtxHttp, FetchFailed

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB = Manifest.model_validate(
    {
        "source": "ecb",
        "version": 1,
        "capabilities": [],
        "allowed_domains": ["ecb.europa.eu"],
        "home_url": "https://www.ecb.europa.eu/",
        "preferred_rung": 1,
        "block_markers": [],
        "headed": False,
        "cookie_headers": {},
        "rate_limit": {"min_interval_s": 1, "jitter_s": 0},
        "status": "active",
    }
)
RATE = re.compile(r"currency=['\"]([A-Z]{3})['\"]\s+rate=['\"]([0-9.]+)['\"]")


def parse_ecb(xml: str) -> dict[str, Decimal]:
    """Unités de devise pour 1 EUR, EUR compris."""
    rates = {cur: Decimal(rate) for cur, rate in RATE.findall(xml)}
    if not rates:
        raise ValueError("no rate in ECB file")
    return rates | {"EUR": Decimal(1)}


class Fx:
    """Ne télécharge les taux qu'à la première devise autre que l'euro."""

    def __init__(self, http: CtxHttp) -> None:
        self._http = http
        self._rates: dict[str, Decimal] | None = None
        self.unavailable = 0  # montants non convertis : le tarif est écarté, pas la recherche

    async def to_eur(self, amount: Decimal, currency: str) -> Decimal | None:
        """None si le taux manque (BCE injoignable, budget épuisé, devise inconnue)."""
        if currency == "EUR":
            return amount
        try:
            if self._rates is None:
                self._rates = parse_ecb((await self._http.get(ECB_URL, freshness="explore")).text)
            return (amount / self._rates[currency]).quantize(Decimal("0.01"))
        except (FetchFailed, ValueError, KeyError):
            self.unavailable += 1
            return None
