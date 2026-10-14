import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).parent / "migrations"


def connect(path: Path | str) -> sqlite3.Connection:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)  # autocommit ; transactions explicites
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Applique les fichiers NNN_*.sql plus récents que PRAGMA user_version, chacun atomiquement."""
    current: int = conn.execute("PRAGMA user_version").fetchone()[0]
    files = sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
    if len({f.name[:3] for f in files}) != len(files):
        raise RuntimeError(f"duplicate migration number in {MIGRATIONS}")
    for file in files:
        version = int(file.name[:3])
        if version > current:
            try:
                conn.executescript(
                    f"BEGIN;\n{file.read_text()}\nPRAGMA user_version = {version};\nCOMMIT;"
                )
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
            current = version
    return current
