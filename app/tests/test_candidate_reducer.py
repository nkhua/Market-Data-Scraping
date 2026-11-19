from __future__ import annotations

from datetime import datetime
from tempfile import TemporaryDirectory
from pathlib import Path

from app.research.discovery.reducer import CandidateReducer
from app.models import DiscoveryEvidence, EvidenceSourceType
from app.storage.discovery_store import DiscoveryStore
from app.storage.journal import TradeJournal
from app.storage.sqlite_store import SQLiteStore


def test_candidate_reducer_merges_evidence_and_scores_candidates() -> None:
    with TemporaryDirectory() as temp_dir:
        store = SQLiteStore(str(Path(temp_dir) / "test.sqlite3"))
        reducer = CandidateReducer(
            max_candidates=10,
            source_weights={"news": 1.0, "earnings": 0.8, "mover": 1.1},
            discovery_store=DiscoveryStore(store),
            journal=TradeJournal(store),
        )

        evidence_items = [
            DiscoveryEvidence(
                symbol="AAPL",
                source_type=EvidenceSourceType.NEWS,
                provider_name="news_stub",
                trigger_reason="Headline matched growth query",
                summary="Apple demand commentary improved",
                observed_at=datetime.utcnow(),
                relevance_score=0.9,
            ),
            DiscoveryEvidence(
                symbol="AAPL",
                source_type=EvidenceSourceType.EARNINGS,
                provider_name="earnings_stub",
                trigger_reason="Upcoming earnings event",
                summary="Apple earnings date approaching",
                observed_at=datetime.utcnow(),
                relevance_score=0.7,
                metadata={"earnings_date": "2026-05-01", "timing": "post_market"},
            ),
            DiscoveryEvidence(
                symbol="MSFT",
                source_type=EvidenceSourceType.NEWS,
                provider_name="news_stub",
                trigger_reason="Headline matched cloud query",
                summary="Microsoft cloud checks improved",
                observed_at=datetime.utcnow(),
                relevance_score=0.5,
            ),
        ]

        reduced = reducer.reduce(evidence_items)

        assert len(reduced) == 2
        assert reduced[0].symbol == "AAPL"
        assert len(reduced[0].evidence) == 2
        assert reduced[0].earnings_event is not None
        assert reduced[0].headlines[0].headline == "Apple demand commentary improved"
