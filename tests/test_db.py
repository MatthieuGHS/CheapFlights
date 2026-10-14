import sqlite3
from pathlib import Path

import pytest

from cheaphops.core.db import MIGRATIONS, connect, migrate


def test_fresh_db_is_migrated_and_rerun_is_noop(tmp_path: Path) -> None:
    latest = max(int(f.name[:3]) for f in MIGRATIONS.glob("*.sql"))
    conn = connect(tmp_path / "sub" / "x.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == latest
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"http_cache", "fetch_stats"} <= tables
    conn.execute("INSERT INTO fetch_stats (source, rung) VALUES ('x', 1)")
    conn.close()

    conn = connect(tmp_path / "sub" / "x.db")
    assert migrate(conn) == latest
    assert conn.execute("SELECT count(*) FROM fetch_stats").fetchone()[0] == 1


def test_failed_migration_is_rolled_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "001_ok.sql").write_text("CREATE TABLE a (x);")
    (tmp_path / "002_bad.sql").write_text("CREATE TABLE b (x);\nNOT SQL;")
    monkeypatch.setattr("cheaphops.core.db.MIGRATIONS", tmp_path)
    conn = sqlite3.connect(":memory:", isolation_level=None)
    with pytest.raises(sqlite3.Error):
        migrate(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master")} == {"a"}


def test_fts5_available() -> None:
    # Les mémoires épisodique et leçons (phase 3) reposent sur FTS5.
    conn = connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
    conn.execute("INSERT INTO t VALUES ('403 GET /api/x')")
    assert conn.execute("SELECT count(*) FROM t WHERE t MATCH 'api'").fetchone()[0] == 1


def test_duplicate_migration_number_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "001_a.sql").write_text("CREATE TABLE a (x);")
    (tmp_path / "001_b.sql").write_text("CREATE TABLE b (x);")
    monkeypatch.setattr("cheaphops.core.db.MIGRATIONS", tmp_path)
    with pytest.raises(RuntimeError, match="duplicate"):
        migrate(sqlite3.connect(":memory:", isolation_level=None))
