from decimal import Decimal

import pytest

from cheaphops.search.fx import parse_ecb

pytestmark = pytest.mark.anyio

XML = """<Cube time='2026-10-14'><Cube currency='USD' rate='1.0785'/>
<Cube currency='GBP' rate='0.8500'/></Cube>"""


def test_parse_ecb_includes_eur() -> None:
    rates = parse_ecb(XML)
    assert rates["GBP"] == Decimal("0.8500") and rates["EUR"] == 1


def test_parse_ecb_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_ecb("<html>maintenance</html>")


async def test_missing_rate_skips_the_fare_not_the_search() -> None:
    from cheaphops.search.fx import Fx

    class Offline:
        async def get(self, *args: object, **kwargs: object) -> object:
            from cheaphops.fetch.http import BudgetExhausted

            raise BudgetExhausted("ecb", "budget", None)

    fx = Fx(Offline())  # type: ignore[arg-type]
    assert await fx.to_eur(Decimal(10), "EUR") == 10
    assert await fx.to_eur(Decimal(10), "GBP") is None and fx.unavailable == 1
