"""SQLite-backed StateStore (WAL). Atomic, crash-safe, single source of truth.

Synchronous sqlite calls are wrapped in ``asyncio.to_thread`` so they never
block the event loop. Volume is tiny (one row per rule, append-only incidents).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from gaa.domain.models import AlertStatus, Incident, RuleState, Severity, TimeWindow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rule_state (
    name             TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    condition_since  REAL,
    firing_since     REAL,
    last_value       REAL,
    last_notified_at REAL,
    window_start     REAL,
    window_end       REAL
);
CREATE TABLE IF NOT EXISTS incidents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name    TEXT NOT NULL,
    title        TEXT NOT NULL,
    severity     TEXT NOT NULL,
    fired_at     REAL NOT NULL,
    resolved_at  REAL,
    value        REAL,
    summary      TEXT,
    likely_cause TEXT,
    remediation  TEXT,
    confidence   TEXT,
    dashboard_url TEXT,
    thread_id    TEXT,
    screenshot   BLOB
);
CREATE INDEX IF NOT EXISTS idx_incidents_rule ON incidents(rule_name, fired_at);
CREATE TABLE IF NOT EXISTS anomaly_state (
    name             TEXT PRIMARY KEY,
    last_verdict     TEXT NOT NULL,
    last_notified_at REAL
);
"""


class SqliteStore:
    """Implements StateStore."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = asyncio.Lock()

    def close(self) -> None:
        self._conn.close()

    # --- rule state -----------------------------------------------------

    async def get_state(self, rule_name: str) -> RuleState | None:
        row = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT * FROM rule_state WHERE name = ?", (rule_name,)
            ).fetchone()
        )
        return _row_to_state(row) if row else None

    async def put_state(self, state: RuleState) -> None:
        async with self._lock:
            await asyncio.to_thread(self._put_state_sync, state)

    def _put_state_sync(self, state: RuleState) -> None:
        self._conn.execute(
            """
            INSERT INTO rule_state
                (name, status, condition_since, firing_since, last_value,
                 last_notified_at, window_start, window_end)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
                status=excluded.status,
                condition_since=excluded.condition_since,
                firing_since=excluded.firing_since,
                last_value=excluded.last_value,
                last_notified_at=excluded.last_notified_at,
                window_start=excluded.window_start,
                window_end=excluded.window_end
            """,
            (
                state.name,
                state.status.value,
                state.condition_since,
                state.firing_since,
                state.last_value,
                state.last_notified_at,
                state.window.start if state.window else None,
                state.window.end if state.window else None,
            ),
        )
        self._conn.commit()

    async def list_states(self) -> tuple[RuleState, ...]:
        rows = await asyncio.to_thread(
            lambda: self._conn.execute("SELECT * FROM rule_state").fetchall()
        )
        return tuple(_row_to_state(r) for r in rows)

    # --- incidents ------------------------------------------------------

    async def record_incident(self, incident: Incident, screenshot: bytes | None = None) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._record_incident_sync, incident, screenshot)

    def _record_incident_sync(self, incident: Incident, screenshot: bytes | None) -> int:
        cursor = self._conn.execute(
            """
            INSERT INTO incidents
                (rule_name, title, severity, fired_at, resolved_at, value,
                 summary, likely_cause, remediation, confidence, dashboard_url, screenshot)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                incident.rule_name,
                incident.title,
                incident.severity.value,
                incident.fired_at,
                incident.resolved_at,
                incident.value,
                incident.summary,
                incident.likely_cause,
                json.dumps(list(incident.remediation)),
                incident.confidence,
                incident.dashboard_url,
                screenshot,
            ),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    async def resolve_incident(self, incident_id: int, resolved_at: float) -> None:
        async with self._lock:
            await asyncio.to_thread(
                lambda: self._conn.execute(
                    "UPDATE incidents SET resolved_at = ? WHERE id = ?",
                    (resolved_at, incident_id),
                )
            )
            await asyncio.to_thread(self._conn.commit)

    async def list_incidents(self, limit: int = 50) -> tuple[Incident, ...]:
        rows = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT * FROM incidents ORDER BY fired_at DESC LIMIT ?", (limit,)
            ).fetchall()
        )
        return tuple(_row_to_incident(r) for r in rows)

    async def get_incident(self, incident_id: int) -> Incident | None:
        row = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
        )
        return _row_to_incident(row) if row else None

    async def get_screenshot(self, incident_id: int) -> bytes | None:
        row = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT screenshot FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
        )
        return row["screenshot"] if row and row["screenshot"] else None

    async def open_incident_id(self, rule_name: str) -> int | None:
        row = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT id FROM incidents WHERE rule_name = ? AND resolved_at IS NULL "
                "ORDER BY fired_at DESC LIMIT 1",
                (rule_name,),
            ).fetchone()
        )
        return int(row["id"]) if row else None

    async def get_anomaly_state(self, name: str) -> tuple[str, float | None] | None:
        row = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT last_verdict, last_notified_at FROM anomaly_state WHERE name = ?", (name,)
            ).fetchone()
        )
        return (row["last_verdict"], row["last_notified_at"]) if row else None

    async def set_anomaly_state(self, name: str, verdict: str, last_notified_at: float | None) -> None:
        async with self._lock:
            await asyncio.to_thread(
                lambda: self._conn.execute(
                    """
                    INSERT INTO anomaly_state (name, last_verdict, last_notified_at)
                    VALUES (?,?,?)
                    ON CONFLICT(name) DO UPDATE SET
                        last_verdict=excluded.last_verdict,
                        last_notified_at=excluded.last_notified_at
                    """,
                    (name, verdict, last_notified_at),
                )
            )
            await asyncio.to_thread(self._conn.commit)

    async def count_recent(self, rule_name: str, since: float) -> int:
        row = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT COUNT(*) AS c FROM incidents WHERE rule_name = ? AND fired_at >= ?",
                (rule_name, since),
            ).fetchone()
        )
        return int(row["c"])

    async def set_incident_thread(self, incident_id: int, thread_id: str) -> None:
        async with self._lock:
            await asyncio.to_thread(
                lambda: self._conn.execute(
                    "UPDATE incidents SET thread_id = ? WHERE id = ?", (thread_id, incident_id)
                )
            )
            await asyncio.to_thread(self._conn.commit)

    async def get_incident_by_thread(self, thread_id: str) -> Incident | None:
        row = await asyncio.to_thread(
            lambda: self._conn.execute(
                "SELECT * FROM incidents WHERE thread_id = ? ORDER BY fired_at DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        )
        return _row_to_incident(row) if row else None


def _row_to_state(row: sqlite3.Row) -> RuleState:
    window = None
    if row["window_start"] is not None and row["window_end"] is not None:
        window = TimeWindow(start=row["window_start"], end=row["window_end"])
    return RuleState(
        name=row["name"],
        status=AlertStatus(row["status"]),
        condition_since=row["condition_since"],
        firing_since=row["firing_since"],
        last_value=row["last_value"],
        last_notified_at=row["last_notified_at"],
        window=window,
    )


def _row_to_incident(row: sqlite3.Row) -> Incident:
    return Incident(
        id=row["id"],
        rule_name=row["rule_name"],
        title=row["title"],
        severity=Severity(row["severity"]),
        fired_at=row["fired_at"],
        resolved_at=row["resolved_at"],
        value=row["value"],
        summary=row["summary"] or "",
        likely_cause=row["likely_cause"] or "",
        remediation=tuple(json.loads(row["remediation"] or "[]")),
        confidence=row["confidence"] or "",
        dashboard_url=row["dashboard_url"] or "",
        thread_id=row["thread_id"] or "",
        has_screenshot=row["screenshot"] is not None,
    )
