from __future__ import annotations

from dataclasses import dataclass

from app.research.filters.event_filters import EventFilter
from app.research.filters.liquidity_filters import LiquidityFilter
from app.research.filters.technical_filters import TechnicalFilter
from app.models import CandidateSignal, FilterDecision


@dataclass
class RoutedCandidate:
    candidate: CandidateSignal
    decisions: dict[str, FilterDecision]

    @property
    def passed(self) -> bool:
        return all(decision.passed for decision in self.decisions.values())

    @property
    def rejection_reasons(self) -> list[str]:
        reasons: list[str] = []
        for name, decision in self.decisions.items():
            reasons.extend(f"{name}: {reason}" for reason in decision.reasons)
        return reasons


class CandidateRouter:
    def __init__(
        self,
        liquidity_filter: LiquidityFilter,
        event_filter: EventFilter,
        technical_filter: TechnicalFilter,
    ) -> None:
        self.liquidity_filter = liquidity_filter
        self.event_filter = event_filter
        self.technical_filter = technical_filter

    def route(self, candidate: CandidateSignal) -> RoutedCandidate:
        decisions = {
            "liquidity": self.liquidity_filter.evaluate(candidate.price_snapshot),
            "event": self.event_filter.evaluate(candidate.earnings_event),
            "technical": self.technical_filter.evaluate(candidate),
        }
        return RoutedCandidate(candidate=candidate, decisions=decisions)
