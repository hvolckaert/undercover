"""The UnderCover database: SQLite, seeded from data/ on first use."""

import json
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_DB = ROOT / "backend" / "undercover.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    body TEXT NOT NULL,
    decision TEXT,
    sign_off TEXT,
    thread_id TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    run_id TEXT
);
CREATE TABLE IF NOT EXISTS steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
    claim_id TEXT PRIMARY KEY,
    amount REAL NOT NULL,
    paid_at TEXT NOT NULL
);
"""


def db_path() -> Path:
    """Return the database file, from UNDERCOVER_DB or the default."""
    return Path(os.getenv("UNDERCOVER_DB", str(DEFAULT_DB)))


def load(name: str) -> Any:
    """Load one JSON file from data/."""
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def seed(conn: sqlite3.Connection) -> None:
    """Load the queue and the reference records from data/."""
    plans = load("plans.json")
    records = [
        ("company", "company", load("company.json")),
        *(("policy", p["policy_id"], p) for p in load("policies.json")),
        *(("customer", c["customer_id"], c) for c in load("customers.json")),
        *(("handler", h["handler_id"], h) for h in load("handlers.json")),
        *(("plan", p["plan"], p) for p in plans["plans"]),
        *(("add_on", a["add_on"], a) for a in plans["add_ons"]),
        ("deductible", "applies_to", plans["deductible_applies_to"]),
    ]
    conn.executemany(
        "INSERT INTO records (kind, id, body) VALUES (?, ?, ?)",
        [(kind, id_, json.dumps(body)) for kind, id_, body in records],
    )
    conn.executemany(
        "INSERT INTO claims (claim_id, status, body) VALUES (?, 'waiting', ?)",
        [(c["claim_id"], json.dumps(c)) for c in load("claims.json")],
    )


def connect() -> sqlite3.Connection:
    """Open the database, creating and seeding it if it is new."""
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0:
        seed(conn)
        conn.commit()
    return conn


def reseed() -> None:
    """Drop every table and seed the database again from data/."""
    conn = connect()
    conn.executescript(
        "DROP TABLE records; DROP TABLE claims; DROP TABLE steps; DROP TABLE payments;"
    )
    conn.close()
    connect().close()


def get_db() -> Iterator[sqlite3.Connection]:
    """Give a request its own connection, committed at the end."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def record(conn: sqlite3.Connection, kind: str, id_: str) -> Any:
    """Return one reference record, or None if there is none."""
    row = conn.execute(
        "SELECT body FROM records WHERE kind = ? AND id = ?", (kind, id_)
    ).fetchone()
    return json.loads(row["body"]) if row else None


def records(conn: sqlite3.Connection, kind: str) -> list[Any]:
    """Return every reference record of one kind."""
    rows = conn.execute(
        "SELECT body FROM records WHERE kind = ? ORDER BY id", (kind,)
    ).fetchall()
    return [json.loads(row["body"]) for row in rows]


if __name__ == "__main__":
    reseed()
    print(f"Reseeded {db_path()}")
