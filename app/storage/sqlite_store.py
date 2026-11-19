from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    symbol TEXT,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovered_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    urgency_score REAL NOT NULL,
                    evidence_count INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for table_name in [
                "instrument_scans",
                "news_catalysts",
                "research_signals",
                "claude_analysis",
                "risk_decisions",
                "proposed_trades",
                "submitted_orders",
                "portfolio_snapshots",
                "broker_responses",
                "errors",
            ]:
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT,
                        asset_class TEXT,
                        payload TEXT NOT NULL,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

    def insert_event(self, event_type: str, symbol: str | None, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO trade_journal (event_type, symbol, payload) VALUES (?, ?, ?)",
                (event_type, symbol, json.dumps(payload, default=str)),
            )

    def fetch_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, event_type, symbol, payload, created_at
                FROM trade_journal
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "event_type": row[1],
                "symbol": row[2],
                "payload": json.loads(row[3]),
                "created_at": row[4],
            }
            for row in rows
        ]

    def enqueue_review(self, symbol: str, payload: dict[str, Any]) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO review_queue (symbol, payload) VALUES (?, ?)",
                (symbol, json.dumps(payload, default=str)),
            )
            return int(cursor.lastrowid)

    def fetch_pending_reviews(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, status, payload, created_at
                FROM review_queue
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "symbol": row[1],
                "status": row[2],
                "payload": json.loads(row[3]),
                "created_at": row[4],
            }
            for row in rows
        ]

    def insert_discovery_evidence(
        self,
        symbol: str,
        source_type: str,
        provider_name: str,
        observed_at: str,
        trigger_reason: str,
        payload: dict[str, Any],
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO discovery_evidence (
                    symbol, source_type, provider_name, observed_at, trigger_reason, payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    source_type,
                    provider_name,
                    observed_at,
                    trigger_reason,
                    json.dumps(payload, default=str),
                ),
            )
            return int(cursor.lastrowid)

    def insert_discovered_candidate(
        self,
        symbol: str,
        urgency_score: float,
        evidence_count: int,
        payload: dict[str, Any],
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO discovered_candidates (
                    symbol, urgency_score, evidence_count, payload
                ) VALUES (?, ?, ?, ?)
                """,
                (symbol, urgency_score, evidence_count, json.dumps(payload, default=str)),
            )
            return int(cursor.lastrowid)

    def insert_record(
        self,
        table_name: str,
        symbol: str | None,
        asset_class: str | None,
        payload: dict[str, Any],
    ) -> int:
        allowed_tables = {
            "instrument_scans",
            "news_catalysts",
            "research_signals",
            "claude_analysis",
            "risk_decisions",
            "proposed_trades",
            "submitted_orders",
            "portfolio_snapshots",
            "broker_responses",
            "errors",
        }
        if table_name not in allowed_tables:
            raise ValueError(f"Unsupported table name: {table_name}")
        with self.connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO {table_name} (symbol, asset_class, payload) VALUES (?, ?, ?)",
                (symbol, asset_class, json.dumps(payload, default=str)),
            )
            return int(cursor.lastrowid)
