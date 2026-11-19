from __future__ import annotations

import logging
from dataclasses import dataclass

from app.claude.decision_service import ClaudeDecisionService
from app.models import AssetClass, ResearchDecision, ResearchDecisionStatus
from app.research.evidence import EquityEvidenceService
from app.research.providers import (
    InstrumentUniverseBuilder,
    PortfolioContextProvider,
    ResearchMarketDataProvider,
    ResearchNewsProvider,
)
from app.research.risk import ResearchRiskGate
from app.research.scanners import AssetScanner, UnsupportedAssetScanner
from app.storage.research_store import ResearchStore


@dataclass
class MultiAssetResearchPipeline:
    universe_builders: list[InstrumentUniverseBuilder]
    market_data_provider: ResearchMarketDataProvider
    news_provider: ResearchNewsProvider
    portfolio_context_provider: PortfolioContextProvider
    scanners: dict[AssetClass, AssetScanner]
    risk_gate: ResearchRiskGate
    claude_decision_service: ClaudeDecisionService
    research_store: ResearchStore
    logger: logging.Logger
    max_candidates_for_claude: int = 10
    equity_evidence_service: EquityEvidenceService | None = None

    def run(self) -> list[ResearchDecision]:
        decisions: list[ResearchDecision] = []
        instruments = []
        claude_candidates_sent = 0
        portfolio_context = self.portfolio_context_provider.get_context()
        self.research_store.log_portfolio_snapshot(portfolio_context)
        for builder in self.universe_builders:
            built = builder.build()
            builder_name = getattr(builder, "name", builder.asset_class.value)
            self.logger.info("Universe builder produced %s %s instrument(s)", len(built), builder_name)
            instruments.extend(built)

        unique_instruments = {}
        for instrument in instruments:
            unique_instruments.setdefault((instrument.asset_class, instrument.symbol), instrument)
        instruments = list(unique_instruments.values())
        self.logger.info("Research universe contains %s unique instrument(s)", len(instruments))

        for instrument in instruments:
            self.research_store.log_instrument_scan(instrument)
            market_data = self.market_data_provider.get_market_data(instrument)
            news_result = self.news_provider.get_news_for_instrument(instrument)
            market_data = market_data.model_copy(
                update={
                    "news_status": news_result.status,
                    "news_reason": news_result.reason,
                    "news_catalysts": news_result.catalysts,
                }
            )
            self.research_store.log_news_catalysts(instrument, news_result.model_dump(mode="json"))
            scanner = self.scanners.get(instrument.asset_class, UnsupportedAssetScanner(instrument.asset_class))
            candidate = scanner.scan(instrument, market_data)
            candidate.portfolio_context = portfolio_context
            decision = self.risk_gate.evaluate(candidate)

            if decision.status == ResearchDecisionStatus.READY_FOR_CLAUDE:
                if claude_candidates_sent >= self.max_candidates_for_claude:
                    decision = ResearchDecision(
                        status=ResearchDecisionStatus.REJECTED,
                        instrument=instrument,
                        candidate=candidate,
                        reasons=["Candidate held because Claude research capacity was reached"],
                    )
                else:
                    claude_candidates_sent += 1
                    try:
                        if self.equity_evidence_service and instrument.asset_class == AssetClass.STOCK:
                            candidate.evidence = self.equity_evidence_service.collect(candidate)
                        analysis = self.claude_decision_service.review(candidate)
                    except Exception as exc:  # noqa: BLE001
                        decision = ResearchDecision(
                            status=ResearchDecisionStatus.REJECTED,
                            instrument=instrument,
                            candidate=candidate,
                            reasons=[f"Claude research unavailable: {exc}"],
                        )
                    else:
                        decision.claude_analysis = analysis
                        decision.status = ResearchDecisionStatus.ANALYZED
                        self.research_store.log_claude_analysis(instrument, analysis)

            self.research_store.log_signal(candidate)
            self.research_store.log_research_decision(decision)
            decisions.append(decision)
        return decisions
