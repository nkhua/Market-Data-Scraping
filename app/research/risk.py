from __future__ import annotations

from datetime import datetime, timedelta

from app.models import AssetClass, DataStatus, ResearchCandidate, ResearchDecision, ResearchDecisionStatus


class ResearchRiskGate:
    def __init__(
        self,
        allowed_asset_classes: list[AssetClass],
        max_data_age_seconds: int,
        min_liquidity_threshold: float,
        allow_shorting: bool,
        allow_naked_options: bool,
    ) -> None:
        self.allowed_asset_classes = set(allowed_asset_classes)
        self.max_data_age_seconds = max_data_age_seconds
        self.min_liquidity_threshold = min_liquidity_threshold
        self.allow_shorting = allow_shorting
        self.allow_naked_options = allow_naked_options

    def evaluate(self, candidate: ResearchCandidate) -> ResearchDecision:
        reasons: list[str] = []
        instrument = candidate.instrument
        market_data = candidate.market_data_summary

        if instrument.asset_class not in self.allowed_asset_classes:
            reasons.append(f"Asset class {instrument.asset_class.value!r} is not enabled")
        if instrument.broker_provider != "IBKR":
            reasons.append("Broker provider is not IBKR")
        if not instrument.is_tradeable:
            reasons.append("Instrument is marked not tradeable")
        if market_data.status != DataStatus.AVAILABLE:
            reasons.append(market_data.reason or "Market data unavailable")
        elif not market_data.as_of:
            reasons.append("Market data timestamp missing")
        elif datetime.utcnow() - market_data.as_of > timedelta(seconds=self.max_data_age_seconds):
            reasons.append("Market data is stale")
        if not candidate.liquidity.acceptable or candidate.liquidity.score < self.min_liquidity_threshold:
            reasons.append("Liquidity is not acceptable")
        if instrument.contract_details.get("requires_news_context") and not market_data.news_catalysts:
            reasons.append("News-focused candidate requires real news context")

        if instrument.asset_class == AssetClass.OPTION:
            self._validate_option(candidate, reasons)
        elif instrument.asset_class == AssetClass.FUTURE:
            self._validate_future(candidate, reasons)
        elif instrument.asset_class in {AssetClass.FOREX, AssetClass.CRYPTO, AssetClass.BOND}:
            reasons.append(f"Asset class {instrument.asset_class.value!r} has no enabled validator yet")

        return ResearchDecision(
            status=ResearchDecisionStatus.REJECTED if reasons else ResearchDecisionStatus.READY_FOR_CLAUDE,
            instrument=instrument,
            candidate=candidate,
            reasons=reasons,
        )

    def _validate_option(self, candidate: ResearchCandidate, reasons: list[str]) -> None:
        defined_risk = bool(candidate.known_risks.get("defined_risk"))
        naked = bool(candidate.known_risks.get("naked_options"))
        if naked and not self.allow_naked_options:
            reasons.append("Naked options are not allowed")
        if not defined_risk:
            reasons.append("Options require a known max loss or defined-risk structure")

    @staticmethod
    def _validate_future(candidate: ResearchCandidate, reasons: list[str]) -> None:
        margin_requirement = candidate.known_risks.get("margin_requirement")
        expiry = candidate.known_risks.get("expiry")
        if margin_requirement is None:
            reasons.append("Futures require margin requirement data")
        if not expiry:
            reasons.append("Futures require expiry/rollover data")
