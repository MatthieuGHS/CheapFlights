import pytest

from cheaphops.lastminute import cache


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """run() active le cache depuis config.yaml : jamais le vrai data/cache pendant les tests."""
    monkeypatch.setattr(cache, "DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "TTL_S", 0)
