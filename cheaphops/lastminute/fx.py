"""Taux de change BCE (EUR de référence), cache fichier de 24 h."""

import json
import re
import time
from decimal import Decimal
from pathlib import Path

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
TTL_S = 24 * 3600
CACHE = Path("data/fx.json")
RATE = re.compile(r"currency=['\"]([A-Z]{3})['\"]\s+rate=['\"]([0-9.]+)['\"]")


class Fx:
    def __init__(self, rates: dict[str, Decimal]) -> None:
        self._rates = rates | {"EUR": Decimal(1)}

    def to_eur(self, amount: Decimal, currency: str) -> Decimal | None:
        """None si la devise est inconnue : le montant est écarté, pas la recherche."""
        rate = self._rates.get(currency)
        return None if rate is None else (amount / rate).quantize(Decimal("0.01"))


def parse_ecb(xml: str) -> dict[str, Decimal]:
    rates = {cur: Decimal(rate) for cur, rate in RATE.findall(xml)}
    if not rates:
        raise ValueError("no rate in ECB file")
    return rates


def load_fx(cache: Path = CACHE, now: float | None = None) -> Fx:
    """Cache valide : aucune requête. Sinon un GET (Scrapling), puis écriture du cache ; si la
    BCE est injoignable, un cache périmé vaut mieux que rien."""
    now = time.time() if now is None else now
    stale: dict[str, str] | None = None
    if cache.exists():
        saved = json.loads(cache.read_text())
        stale = saved["rates"]
        if now - saved["at"] < TTL_S:
            return Fx({k: Decimal(v) for k, v in saved["rates"].items()})
    try:
        from scrapling.fetchers import Fetcher

        rates = parse_ecb(str(Fetcher.get(ECB_URL, timeout=20).body.decode()))
    except Exception:
        if stale is None:
            raise
        return Fx({k: Decimal(v) for k, v in stale.items()})
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"at": now, "rates": {k: str(v) for k, v in rates.items()}}))
    return Fx(rates)
