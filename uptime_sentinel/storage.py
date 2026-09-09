"""
SQLite persistence for check history.

Why SQLite and not JSON-lines: SLA math needs range queries ("all checks for
service X in the last 24h") and this keeps that as real SQL instead of
hand-rolled filtering, while still being a single file with zero external
services to stand up -- important for a project someone should be able to
clone and run in under a minute.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .monitor import CheckResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT NOT NULL,
    check_type TEXT NOT NULL,
    ok INTEGER NOT NULL,
    status_code INTEGER,
    latency_ms REAL NOT NULL,
    error TEXT,
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checks_service_ts ON checks (service, timestamp);
"""


class Store:
    """Thin wrapper around a sqlite3 connection scoped to one db file."""

    def __init__(self, db_path: str = "data/uptime_sentinel.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save(self, result: CheckResult) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO checks (service, check_type, ok, status_code, latency_ms, error, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                result.to_row(),
            )

    def save_many(self, results: list[CheckResult]) -> None:
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO checks (service, check_type, ok, status_code, latency_ms, error, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [r.to_row() for r in results],
            )

    def history(self, service: str, since_ts: Optional[float] = None) -> list[dict]:
        query = "SELECT service, check_type, ok, status_code, latency_ms, error, timestamp FROM checks WHERE service = ?"
        params: list = [service]
        if since_ts is not None:
            query += " AND timestamp >= ?"
            params.append(since_ts)
        query += " ORDER BY timestamp ASC"

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [_normalize(dict(r)) for r in rows]

    def services(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT service FROM checks ORDER BY service").fetchall()
            return [r[0] for r in rows]

    def latest(self, service: str) -> Optional[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT service, check_type, ok, status_code, latency_ms, error, timestamp "
                "FROM checks WHERE service = ? ORDER BY timestamp DESC LIMIT 1",
                (service,),
            ).fetchone()
            return _normalize(dict(row)) if row else None


def _normalize(row: dict) -> dict:
    """sqlite3 has no native bool -- INTEGER 0/1 comes back as Python int, not bool.
    `x is True`/`is False` checks elsewhere (report.py) need a real bool, so fix it up
    once here rather than relying on every caller to remember to coerce it."""
    row["ok"] = bool(row["ok"])
    return row
