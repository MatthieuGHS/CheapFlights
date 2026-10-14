from decimal import Decimal

import pytest

from cheaphops.search.fx import parse_ecb

XML = """<Cube time='2026-10-14'><Cube currency='USD' rate='1.0785'/>
<Cube currency='GBP' rate='0.8500'/></Cube>"""


def test_parse_ecb_includes_eur() -> None:
    rates = parse_ecb(XML)
    assert rates["GBP"] == Decimal("0.8500") and rates["EUR"] == 1


def test_parse_ecb_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_ecb("<html>maintenance</html>")
