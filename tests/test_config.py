from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from cheaphops.core.config import load_config, load_ground

ROOT = Path(__file__).parent.parent


def test_repo_config_matches_spec_defaults() -> None:
    cfg = load_config(ROOT / "config.yaml", ROOT / "absent.yaml")
    p = cfg.search.defaults.params(date(2026, 10, 14))
    assert p.origins == ["VNO", "KUN", "RIX"]
    assert (p.date_from, p.date_to) == (date(2026, 10, 15), date(2026, 12, 10))
    assert (p.max_nights, p.min_on_site_hours, p.min_connection_hours) == (3, 24, 3)
    assert (p.max_layover_hours, p.max_stops_per_direction, p.top_k) == (18, 1, 30)
    assert p.allow_self_transfer and p.allow_open_jaw
    assert p.return_deadline is None and p.max_total_price is None and p.blackout == []
    assert cfg.search.bound_slack == 0.8
    assert cfg.llm.region == "eu-north-1"
    assert cfg.llm.caps.pathfinder_run_usd > cfg.llm.caps.per_run_usd


def test_weekend_preset_overrides_defaults() -> None:
    cfg = load_config(ROOT / "config.yaml", ROOT / "absent.yaml")
    w = cfg.search.preset("weekend")
    assert w.depart_weekdays == [4, 5] and w.return_weekdays == [6, 0]
    assert w.return_deadline is not None
    assert (w.return_deadline.at, w.return_deadline.weekday) == (time(12, 0), 0)
    assert w.max_nights == 3


def test_local_overrides_merge_without_touching_config_yaml(tmp_path: Path) -> None:
    base = (ROOT / "config.yaml").read_text()
    (tmp_path / "config.yaml").write_text(base)
    local = tmp_path / "config.local.yaml"
    local.write_text("search:\n  defaults:\n    max_nights: 5\nllm:\n  caps:\n    total_usd: 10\n")
    cfg = load_config(tmp_path / "config.yaml", local)
    assert cfg.search.defaults.max_nights == 5
    assert cfg.search.defaults.top_k == 30
    assert cfg.llm.caps.total_usd == Decimal(10)
    assert (tmp_path / "config.yaml").read_text() == base


def test_invalid_preset_rejected_at_load(tmp_path: Path) -> None:
    local = tmp_path / "local.yaml"
    local.write_text("search:\n  presets:\n    bad: {max_nights: -1}\n")
    with pytest.raises(ValidationError):
        load_config(ROOT / "config.yaml", local)


def test_pathfinder_cap_below_run_cap_rejected(tmp_path: Path) -> None:
    local = tmp_path / "local.yaml"
    local.write_text("llm:\n  caps:\n    pathfinder_run_usd: 0.1\n")
    with pytest.raises(ValidationError, match="pathfinder_run_usd"):
        load_config(ROOT / "config.yaml", local)


def test_unknown_key_rejected(tmp_path: Path) -> None:
    local = tmp_path / "local.yaml"
    local.write_text("search:\n  defaults:\n    max_night: 2\n")
    with pytest.raises(ValidationError, match="max_night"):
        load_config(ROOT / "config.yaml", local)


def test_repo_ground_config() -> None:
    g = load_ground(ROOT / "ground.yaml")
    pairs = {frozenset((e.a, e.b)) for e in g.edges}
    assert pairs == {frozenset(p) for p in [("VNO", "KUN"), ("VNO", "RIX"), ("KUN", "RIX")]}
    assert "BGY" in g.metro.overrides["Milan"]


def test_duplicate_ground_edge_rejected(tmp_path: Path) -> None:
    f = tmp_path / "ground.yaml"
    f.write_text(
        "edges:\n"
        "  - {a: VNO, b: KUN, duration_min: 90, cost_eur: 10, margin_min: 60}\n"
        "  - {a: KUN, b: VNO, duration_min: 90, cost_eur: 10, margin_min: 60}\n"
        "metro: {radius_km: 60, transfer_cost_eur: 15, transfer_min: 90, overrides: {}}\n"
    )
    with pytest.raises(ValidationError, match="duplicate"):
        load_ground(f)
