CREATE TABLE source_state (
    source        TEXT PRIMARY KEY,
    strikes       INTEGER NOT NULL DEFAULT 0,  -- blocages consécutifs, pour le backoff exponentiel
    blocked_until REAL,
    reason        TEXT
);

ALTER TABLE http_cache ADD COLUMN rung INTEGER NOT NULL DEFAULT 1;
