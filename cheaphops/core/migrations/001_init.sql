CREATE TABLE http_cache (
    key        TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    status     INTEGER NOT NULL,
    headers    TEXT NOT NULL,  -- JSON
    body       TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE TABLE fetch_stats (
    source          TEXT NOT NULL,
    rung            INTEGER NOT NULL,
    successes       INTEGER NOT NULL DEFAULT 0,
    failures        INTEGER NOT NULL DEFAULT 0,
    total_latency_s REAL NOT NULL DEFAULT 0,
    last_failure    TEXT,
    last_failure_at REAL,
    PRIMARY KEY (source, rung)
);
