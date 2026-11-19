from __future__ import annotations

from typing import Any

from app.storage.sqlite_store import SQLiteStore


class TradeJournal:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def log_signal(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("signal", symbol, payload)

    def log_filter_result(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("filter_result", symbol, payload)

    def log_analyst_review(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("analyst_review", symbol, payload)

    def log_discovery_evidence(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("discovery_evidence", symbol, payload)

    def log_discovered_candidate(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("discovered_candidate", symbol, payload)

    def log_order_approval(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("order_approval", symbol, payload)

    def log_order_rejection(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("order_rejection", symbol, payload)

    def log_order_submission(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("order_submission", symbol, payload)

    def log_fill(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("fill", symbol, payload)

    def log_exit(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("exit", symbol, payload)

    def log_review_queue(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("review_queue", symbol, payload)

    def log_autonomy_decision(self, symbol: str, payload: dict[str, Any]) -> None:
        self.store.insert_event("autonomy_decision", symbol, payload)
