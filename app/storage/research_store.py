from __future__ import annotations

from app.models import ClaudeResearchOutput, ResearchCandidate, ResearchDecision, TradableInstrument
from app.storage.sqlite_store import SQLiteStore


class ResearchStore:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def log_instrument_scan(self, instrument: TradableInstrument) -> int:
        return self.store.insert_record(
            "instrument_scans",
            instrument.symbol,
            instrument.asset_class.value,
            instrument.model_dump(mode="json"),
        )

    def log_signal(self, candidate: ResearchCandidate) -> int:
        return self.store.insert_record(
            "research_signals",
            candidate.instrument.symbol,
            candidate.asset_class.value,
            candidate.model_dump(mode="json"),
        )

    def log_news_catalysts(self, instrument: TradableInstrument, payload: dict[str, object]) -> int:
        return self.store.insert_record(
            "news_catalysts",
            instrument.symbol,
            instrument.asset_class.value,
            payload,
        )

    def log_claude_analysis(self, instrument: TradableInstrument, analysis: ClaudeResearchOutput) -> int:
        return self.store.insert_record(
            "claude_analysis",
            instrument.symbol,
            instrument.asset_class.value,
            analysis.model_dump(mode="json"),
        )

    def log_research_decision(self, decision: ResearchDecision) -> int:
        return self.store.insert_record(
            "risk_decisions",
            decision.instrument.symbol,
            decision.instrument.asset_class.value,
            decision.model_dump(mode="json"),
        )

    def log_portfolio_snapshot(self, payload: dict[str, object]) -> int:
        return self.store.insert_record(
            "portfolio_snapshots",
            None,
            None,
            payload,
        )
