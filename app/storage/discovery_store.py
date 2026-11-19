from __future__ import annotations

from app.models import CandidateSignal, DiscoveryEvidence
from app.storage.sqlite_store import SQLiteStore


class DiscoveryStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def save_evidence(self, evidence: DiscoveryEvidence) -> int:
        return self.store.insert_discovery_evidence(
            symbol=evidence.symbol,
            source_type=evidence.source_type.value,
            provider_name=evidence.provider_name,
            observed_at=evidence.observed_at.isoformat(),
            trigger_reason=evidence.trigger_reason,
            payload=evidence.model_dump(mode="json"),
        )

    def save_candidate(self, candidate: CandidateSignal) -> int:
        return self.store.insert_discovered_candidate(
            symbol=candidate.symbol,
            urgency_score=candidate.urgency_score,
            evidence_count=len(candidate.evidence),
            payload=candidate.model_dump(mode="json"),
        )
