"""SQLite 快照存储。"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get("OVEN_DB_PATH", os.path.join(os.getcwd(), "data", "oven.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    status_text TEXT NOT NULL,
    objective_sum INTEGER,
    optimal INTEGER,
    elapsed_ms INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def save_snapshot(name: str, request: Dict[str, Any], result: Dict[str, Any]) -> int:
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = json.dumps(
        {"request": request, "result": result}, ensure_ascii=False
    )
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO snapshots
               (name, status, status_text, objective_sum, optimal,
                elapsed_ms, payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                result.get("status"),
                result.get("status_text"),
                result.get("objective_sum"),
                None if result.get("optimal") is None else int(bool(result["optimal"])),
                result.get("elapsed_ms", 0),
                payload,
                created_at,
            ),
        )
        return int(cur.lastrowid)


def list_snapshots(limit: int = 100) -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT id, name, status, status_text, objective_sum,
                      optimal, elapsed_ms, created_at
               FROM snapshots ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["optimal"] = None if d["optimal"] is None else bool(d["optimal"])
        out.append(d)
    return out


def get_snapshot(snapshot_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["optimal"] = None if d["optimal"] is None else bool(d["optimal"])
    d["payload"] = json.loads(d["payload"])
    return d


def delete_snapshot(snapshot_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
        return cur.rowcount > 0
