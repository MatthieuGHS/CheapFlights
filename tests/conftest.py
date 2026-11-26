import pytest

from cheaphops.lastminute import cache, sources


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """run() active le cache depuis config.yaml : jamais le vrai data/cache pendant les tests."""
    monkeypatch.setattr(cache, "DIR", tmp_path / "cache")
    monkeypatch.setattr(cache, "TTL_S", 0)


@pytest.fixture(autouse=True)
def _offline_http_sources(monkeypatch):  # type: ignore[no-untyped-def]
    """airBaltic et Kiwi sont actifs dans config.yaml : un test qui les veut les remplace."""
    monkeypatch.setattr(sources, "airbaltic", lambda *a: ([], 0))
    monkeypatch.setattr(sources, "kiwi", lambda *a: ([], 0))
