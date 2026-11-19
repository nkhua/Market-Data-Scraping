from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime

from app.research.discovery.service import DiscoveryService
from app.models import DiscoveryContext, DiscoveryEvidence, EvidenceSourceType
from app.storage.discovery_store import DiscoveryStore
from app.storage.journal import TradeJournal
from app.storage.sqlite_store import SQLiteStore


class FixtureDiscoveryProvider:
    name = "fixture_discovery"
    source_type = EvidenceSourceType.NEWS

    def discover(self, context: DiscoveryContext) -> list[DiscoveryEvidence]:
        return [
            DiscoveryEvidence(
                symbol=symbol,
                source_type=EvidenceSourceType.NEWS,
                provider_name=self.name,
                trigger_reason="Fixture headline discovery hit",
                summary=f"Fixture discovery summary for {symbol}",
                observed_at=datetime.utcnow(),
                relevance_score=max(context.headline_min_relevance_score, 0.75),
                metadata={"mode": context.mode},
            )
            for symbol in context.base_universe_symbols
        ]


def test_discovery_service_persists_evidence_rows() -> None:
    with TemporaryDirectory() as temp_dir:
        store = SQLiteStore(str(Path(temp_dir) / "test.sqlite3"))
        service = DiscoveryService(
            providers=[FixtureDiscoveryProvider()],
            discovery_store=DiscoveryStore(store),
            journal=TradeJournal(store),
        )

        items = service.discover(
            DiscoveryContext(
                mode="watchlist_anchored",
                base_universe_symbols=["AAPL", "NVDA"],
                headline_min_relevance_score=0.7,
            )
        )

        with store.connect() as conn:
            evidence_count = conn.execute("SELECT COUNT(*) FROM discovery_evidence").fetchone()[0]

        assert len(items) == 2
        assert evidence_count == 2
