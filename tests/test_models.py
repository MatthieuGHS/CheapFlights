from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from cheaphops.core.models import (
    Blackout,
    DayFare,
    Flight,
    GroundEdge,
    Manifest,
    RateLimit,
    RecipeStatus,
)

T0 = datetime(2026, 11, 6, 6, 0, tzinfo=UTC)


def flight(**kw: object) -> Flight:
    base: dict[str, object] = dict(
        source="ryanair", flight_no="FR1", origin="VNO", destination="BGY",
        departure=T0, arrival=T0 + timedelta(hours=2), price="19.99", currency="EUR",
    )  # fmt: skip
    return Flight.model_validate(base | kw)


def test_valid_flight_parses_price_as_decimal() -> None:
    assert flight().price == Decimal("19.99")


@pytest.mark.parametrize(
    "kw",
    [
        {"origin": "vno"},
        {"origin": "VNOX"},
        {"price": "-1"},
        {"currency": "eur"},
        {"arrival": T0},
        {"departure": datetime(2026, 11, 6, 6, 0)},  # sans fuseau
    ],
)
def test_invalid_flight_rejected(kw: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        flight(**kw)


def test_models_are_immutable() -> None:
    fare = DayFare(
        origin="VNO", destination="BGY", day=date(2026, 11, 6), price=Decimal(9), currency="EUR"
    )
    with pytest.raises(ValidationError):
        fare.price = Decimal(1)  # type: ignore[misc]


def test_blackout_and_ground_edge_invariants() -> None:
    with pytest.raises(ValidationError):
        Blackout(start=datetime(2026, 12, 2), end=datetime(2026, 12, 1))
    with pytest.raises(ValidationError):
        GroundEdge(a="VNO", b="VNO", duration_min=1, cost_eur=Decimal(0), margin_min=0)


@pytest.mark.parametrize("domain", ["com", "Ryanair.com", "ryanair.com/", ".ryanair.com", ""])
def test_manifest_rejects_domains_that_widen_the_allowlist(domain: str) -> None:
    with pytest.raises(ValidationError):
        Manifest(
            source="x", version=1, capabilities={"calendar"}, allowed_domains=[domain],
            preferred_rung=1, rate_limit=RateLimit(min_interval_s=1, jitter_s=0),
            status=RecipeStatus.DRAFT,
        )  # fmt: skip
