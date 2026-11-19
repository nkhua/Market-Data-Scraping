from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from app.models import (
    CandidateSignal,
    DiscoveryEvidence,
    EarningsEvent,
    EvidenceSourceType,
    HeadlineItem,
    MonitorTrigger,
    ResearchItem,
    TriggerType,
)
from app.storage.discovery_store import DiscoveryStore
from app.storage.journal import TradeJournal


class CandidateReducer:
    def __init__(
        self,
        max_candidates: int,
        source_weights: dict[str, float],
        discovery_store: DiscoveryStore,
        journal: TradeJournal,
        logger: logging.Logger | None = None,
    ) -> None:
        self.max_candidates = max_candidates
        self.source_weights = defaultdict(lambda: 1.0, source_weights)
        self.discovery_store = discovery_store
        self.journal = journal
        self.logger = logger or logging.getLogger("trading_bot.reducer")

    def reduce(self, evidence_items: list[DiscoveryEvidence]) -> list[CandidateSignal]:
        candidates: dict[str, CandidateSignal] = {}
        for item in evidence_items:
            candidate = candidates.get(item.symbol)
            if candidate is None:
                candidate = CandidateSignal(symbol=item.symbol)
                candidates[item.symbol] = candidate
            else:
                self.logger.info("Candidate merged for %s via %s", item.symbol, item.source_type.value)

            candidate.evidence.append(item)
            candidate.triggers.append(self._build_trigger(item))
            candidate.monitor_notes.append(item.trigger_reason)
            candidate.urgency_score += item.relevance_score * self.source_weights[item.source_type.value]
            self._apply_evidence(candidate, item)

        reduced = sorted(candidates.values(), key=lambda item: item.urgency_score, reverse=True)
        reduced = reduced[: self.max_candidates]
        for candidate in reduced:
            row_id = self.discovery_store.save_candidate(candidate)
            self.journal.log_discovered_candidate(
                candidate.symbol,
                candidate.model_dump(mode="json") | {"discovered_candidate_id": row_id},
            )
        return reduced

    def _build_trigger(self, evidence: DiscoveryEvidence) -> MonitorTrigger:
        trigger_map = {
            EvidenceSourceType.NEWS: TriggerType.HEADLINE,
            EvidenceSourceType.EARNINGS: TriggerType.EARNINGS_APPROACHING,
            EvidenceSourceType.MOVER: TriggerType.PRICE_MOVE,
            EvidenceSourceType.VOLATILITY: TriggerType.VOLATILITY_EXPANSION,
            EvidenceSourceType.FILING: TriggerType.RESEARCH,
            EvidenceSourceType.CATALYST: TriggerType.RESEARCH,
        }
        return MonitorTrigger(
            symbol=evidence.symbol,
            trigger_type=trigger_map[evidence.source_type],
            reason=evidence.trigger_reason,
            strength=evidence.relevance_score,
            metadata=evidence.metadata | {"provider_name": evidence.provider_name, "summary": evidence.summary},
        )

    def _apply_evidence(self, candidate: CandidateSignal, evidence: DiscoveryEvidence) -> None:
        if evidence.source_type == EvidenceSourceType.NEWS:
            candidate.headlines.append(
                HeadlineItem(
                    symbol=evidence.symbol,
                    headline=evidence.summary,
                    source=evidence.provider_name,
                    published_at=evidence.observed_at,
                    relevance_score=evidence.relevance_score,
                )
            )
        elif evidence.source_type == EvidenceSourceType.EARNINGS:
            earnings_date = evidence.metadata.get("earnings_date")
            if isinstance(earnings_date, str):
                candidate.earnings_event = EarningsEvent(
                    symbol=evidence.symbol,
                    earnings_date=date.fromisoformat(earnings_date),
                    timing=str(evidence.metadata.get("timing", "unknown")),
                )
        elif evidence.source_type in {EvidenceSourceType.MOVER, EvidenceSourceType.VOLATILITY}:
            candidate.volatility_context[evidence.source_type.value] = evidence.metadata or {"summary": evidence.summary}
        elif evidence.source_type in {EvidenceSourceType.FILING, EvidenceSourceType.CATALYST}:
            candidate.research_items.append(
                ResearchItem(
                    symbol=evidence.symbol,
                    summary=evidence.summary,
                    source=evidence.provider_name,
                    published_at=evidence.observed_at,
                    relevance_score=evidence.relevance_score,
                )
            )
            candidate.catalyst_notes.append(evidence.summary)
