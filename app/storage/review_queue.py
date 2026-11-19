from __future__ import annotations

from app.models import ReviewQueueItem
from app.storage.sqlite_store import SQLiteStore


class ReviewQueue:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def enqueue(self, item: ReviewQueueItem) -> int:
        return self.store.enqueue_review(item.symbol, item.model_dump(mode="json"))

    def fetch_pending(self, limit: int = 100) -> list[dict[str, object]]:
        return self.store.fetch_pending_reviews(limit=limit)
