from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models import AssetClass, DataStatus, LiquidityProfile, MarketDataSummary, ResearchCandidate, TradableInstrument


class AssetScanner(Protocol):
    asset_class: AssetClass

    def scan(self, instrument: TradableInstrument, market_data: MarketDataSummary) -> ResearchCandidate:
        ...


@dataclass
class EquityEtfScanner:
    asset_class: AssetClass
    min_liquidity_score: float

    def scan(self, instrument: TradableInstrument, market_data: MarketDataSummary) -> ResearchCandidate:
        liquidity = _quote_liquidity(market_data, self.min_liquidity_score)
        signals = _trend_signals(market_data)
        return ResearchCandidate(
            instrument=instrument,
            asset_class=instrument.asset_class,
            market_data_summary=market_data,
            technical_signals=signals,
            news_context={"items": market_data.news_catalysts},
            macro_context={"rates": market_data.macro_rates},
            liquidity=liquidity,
            known_risks={
                "data_unavailable": market_data.status != DataStatus.AVAILABLE,
                "event_risk": "review_required",
            },
        )


@dataclass
class OptionsScanner:
    min_liquidity_score: float
    asset_class: AssetClass = AssetClass.OPTION

    def scan(self, instrument: TradableInstrument, market_data: MarketDataSummary) -> ResearchCandidate:
        chain = market_data.options_chain
        spread = chain.get("spread_pct")
        open_interest = chain.get("open_interest")
        volume = chain.get("volume")
        score = 0.0
        reasons: list[str] = []
        if isinstance(spread, int | float) and spread <= 0.10:
            score += 0.4
        else:
            reasons.append("Option spread data missing or too wide")
        if isinstance(open_interest, int | float) and open_interest > 0:
            score += 0.3
        else:
            reasons.append("Open interest data missing")
        if isinstance(volume, int | float) and volume > 0:
            score += 0.3
        else:
            reasons.append("Option volume data missing")
        acceptable = score >= self.min_liquidity_score
        defined_risk = bool(
            instrument.contract_details.get("defined_risk")
            or instrument.contract_details.get("max_loss")
        )
        naked = bool(instrument.contract_details.get("naked"))
        return ResearchCandidate(
            instrument=instrument,
            asset_class=instrument.asset_class,
            market_data_summary=market_data,
            technical_signals={"unusual_volume": chain.get("unusual_volume"), "iv_rank": chain.get("iv_rank")},
            news_context={"items": market_data.news_catalysts},
            macro_context={"rates": market_data.macro_rates},
            liquidity=LiquidityProfile(acceptable=acceptable, score=min(score, 1.0), metrics=chain, reasons=reasons),
            known_risks={
                "data_unavailable": market_data.status != DataStatus.AVAILABLE,
                "defined_risk": defined_risk,
                "naked_options": naked,
                "iv_crush_risk": chain.get("iv_crush_risk", "unknown"),
                "earnings_risk": chain.get("earnings_risk", "unknown"),
            },
        )


@dataclass
class FuturesScanner:
    min_liquidity_score: float
    asset_class: AssetClass = AssetClass.FUTURE

    def scan(self, instrument: TradableInstrument, market_data: MarketDataSummary) -> ResearchCandidate:
        contract = market_data.futures_contract
        liquidity = _quote_liquidity(market_data, self.min_liquidity_score)
        return ResearchCandidate(
            instrument=instrument,
            asset_class=instrument.asset_class,
            market_data_summary=market_data,
            technical_signals=_trend_signals(market_data),
            news_context={"items": market_data.news_catalysts},
            macro_context={"rates": market_data.macro_rates},
            liquidity=liquidity,
            known_risks={
                "data_unavailable": market_data.status != DataStatus.AVAILABLE,
                "margin_requirement": contract.get("margin_requirement"),
                "expiry": contract.get("expiry"),
                "rollover_risk": contract.get("rollover_risk", "unknown"),
            },
        )


@dataclass
class UnsupportedAssetScanner:
    asset_class: AssetClass

    def scan(self, instrument: TradableInstrument, market_data: MarketDataSummary) -> ResearchCandidate:
        return ResearchCandidate(
            instrument=instrument,
            asset_class=instrument.asset_class,
            market_data_summary=market_data,
            liquidity=LiquidityProfile(acceptable=False, score=0.0, reasons=["Asset class scanner unavailable"]),
            known_risks={"unsupported_asset_class": instrument.asset_class.value},
        )


def build_scanner_registry(min_liquidity_score: float) -> dict[AssetClass, AssetScanner]:
    return {
        AssetClass.STOCK: EquityEtfScanner(AssetClass.STOCK, min_liquidity_score),
        AssetClass.ETF: EquityEtfScanner(AssetClass.ETF, min_liquidity_score),
        AssetClass.OPTION: OptionsScanner(min_liquidity_score),
        AssetClass.FUTURE: FuturesScanner(min_liquidity_score),
    }


def _quote_liquidity(market_data: MarketDataSummary, min_liquidity_score: float) -> LiquidityProfile:
    if market_data.status != DataStatus.AVAILABLE:
        return LiquidityProfile(
            acceptable=False,
            score=0.0,
            reasons=[market_data.reason or "Market data unavailable"],
        )
    quote = market_data.quote
    score = 0.0
    reasons: list[str] = []
    spread_pct = quote.get("spread_pct")
    volume = quote.get("volume")
    if isinstance(spread_pct, int | float) and spread_pct <= 0.01:
        score += 0.5
    else:
        reasons.append("Spread data missing or too wide")
    if isinstance(volume, int | float) and volume > 0:
        score += 0.5
    else:
        reasons.append("Volume data missing")
    return LiquidityProfile(
        acceptable=score >= min_liquidity_score,
        score=min(score, 1.0),
        metrics={"spread_pct": spread_pct, "volume": volume},
        reasons=reasons,
    )


def _trend_signals(market_data: MarketDataSummary) -> dict[str, object]:
    quote = market_data.quote
    history = market_data.historical_ohlcv
    return {
        "momentum": quote.get("momentum"),
        "breakout": quote.get("breakout"),
        "volume_spike": quote.get("volume_spike"),
        "trend": quote.get("trend"),
        "volatility_expansion": quote.get("volatility_expansion"),
        "history_points": len(history),
    }
