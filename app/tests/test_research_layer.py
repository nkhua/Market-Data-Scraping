from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

from app.models import (
    AssetClass,
    ClaudeResearchOutput,
    DataStatus,
    MarketDataSummary,
    NewsFetchResult,
    ResearchCandidate,
    ResearchDecisionStatus,
    TradableInstrument,
)
from app.research.ibkr_data import IBKRResearchMarketDataProvider, IBKRScannerUniverseBuilder
from app.research.news import AlphaVantageNewsProvider
from app.research.pipeline import MultiAssetResearchPipeline
from app.research.providers import ConfiguredContractUniverseBuilder, ConfiguredSymbolUniverseBuilder
from app.research.risk import ResearchRiskGate
from app.research.scanners import build_scanner_registry
from app.research.symbol_directory import NasdaqTraderStockUniverseBuilder
from app.storage.research_store import ResearchStore
from app.storage.sqlite_store import SQLiteStore


def build_gate(allowed: list[AssetClass] | None = None) -> ResearchRiskGate:
    return ResearchRiskGate(
        allowed_asset_classes=allowed or [AssetClass.STOCK, AssetClass.ETF],
        max_data_age_seconds=900,
        min_liquidity_threshold=0.5,
        allow_shorting=False,
        allow_naked_options=False,
    )


def test_missing_market_data_rejects_research_candidate() -> None:
    instrument = TradableInstrument(
        symbol="AAPL",
        asset_class=AssetClass.STOCK,
        exchange="SMART",
        currency="USD",
        data_provider=None,
    )
    market_data = MarketDataSummary(
        status=DataStatus.UNAVAILABLE,
        provider="unavailable",
        reason="MARKET_DATA_PROVIDER is not configured",
    )
    scanner = build_scanner_registry(0.5)[AssetClass.STOCK]
    candidate = scanner.scan(instrument, market_data)

    decision = build_gate().evaluate(candidate)

    assert decision.status == ResearchDecisionStatus.REJECTED
    assert "MARKET_DATA_PROVIDER is not configured" in decision.reasons


def test_option_requires_defined_risk_structure() -> None:
    instrument = TradableInstrument(
        symbol="AAPL",
        asset_class=AssetClass.OPTION,
        exchange="SMART",
        currency="USD",
        contract_details={"expiry": "20260619", "strike": 200.0, "right": "C"},
    )
    market_data = MarketDataSummary(
        status=DataStatus.AVAILABLE,
        provider="fixture",
        as_of=datetime.utcnow(),
        options_chain={"spread_pct": 0.05, "open_interest": 100, "volume": 20},
    )
    scanner = build_scanner_registry(0.5)[AssetClass.OPTION]
    candidate = scanner.scan(instrument, market_data)

    decision = build_gate([AssetClass.OPTION]).evaluate(candidate)

    assert decision.status == ResearchDecisionStatus.REJECTED
    assert "Options require a known max loss or defined-risk structure" in decision.reasons


def test_future_requires_margin_and_rollover_data() -> None:
    instrument = TradableInstrument(
        symbol="ES",
        asset_class=AssetClass.FUTURE,
        exchange="CME",
        currency="USD",
        contract_details={"expiry": "202606"},
    )
    market_data = MarketDataSummary(
        status=DataStatus.AVAILABLE,
        provider="fixture",
        as_of=datetime.utcnow(),
        quote={"spread_pct": 0.001, "volume": 1000},
        futures_contract={},
    )
    scanner = build_scanner_registry(0.5)[AssetClass.FUTURE]
    candidate = scanner.scan(instrument, market_data)

    decision = build_gate([AssetClass.FUTURE]).evaluate(candidate)

    assert decision.status == ResearchDecisionStatus.REJECTED
    assert "Futures require margin requirement data" in decision.reasons
    assert "Futures require expiry/rollover data" in decision.reasons


def test_stale_data_rejects_candidate() -> None:
    instrument = TradableInstrument(
        symbol="SPY",
        asset_class=AssetClass.ETF,
        exchange="SMART",
        currency="USD",
    )
    market_data = MarketDataSummary(
        status=DataStatus.AVAILABLE,
        provider="fixture",
        as_of=datetime.utcnow() - timedelta(hours=2),
        quote={"spread_pct": 0.001, "volume": 1000},
    )
    scanner = build_scanner_registry(0.5)[AssetClass.ETF]
    candidate = scanner.scan(instrument, market_data)

    decision = build_gate().evaluate(candidate)

    assert decision.status == ResearchDecisionStatus.REJECTED
    assert "Market data is stale" in decision.reasons


def test_configured_universe_builders_do_not_invent_symbols() -> None:
    stock_builder = ConfiguredSymbolUniverseBuilder(AssetClass.STOCK, [])
    option_builder = ConfiguredContractUniverseBuilder(AssetClass.OPTION, [])

    assert stock_builder.build() == []
    assert option_builder.build() == []


def test_nasdaq_trader_universe_builder_loads_all_current_stock_symbols() -> None:
    nasdaq_listed = "\n".join(
        [
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N",
            "QQQ|Invesco QQQ Trust|G|N|N|100|Y|N",
            "ZTEST|Sample Test Security|Q|Y|N|100|N|N",
            "File Creation Time: 0514202618:00|||||||",
        ]
    )
    other_listed = "\n".join(
        [
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol",
            "IBM|International Business Machines Corporation|N|IBM|N|100|N|IBM",
            "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY",
            "File Creation Time: 0514202618:00|||||||",
        ]
    )

    def http_get(url: str, timeout_seconds: int) -> str:
        assert timeout_seconds == 10
        if url.endswith("nasdaqlisted.txt"):
            return nasdaq_listed
        return other_listed

    builder = NasdaqTraderStockUniverseBuilder(http_get=http_get)

    instruments = builder.build()

    assert [instrument.symbol for instrument in instruments] == ["AAPL", "IBM"]
    assert all(instrument.asset_class == AssetClass.STOCK for instrument in instruments)
    assert instruments[0].contract_details["universe_source"] == "nasdaq_trader_symbol_directory"
    assert instruments[1].contract_details["primary_listing_exchange"] == "NYSE"


def test_nasdaq_trader_universe_builder_fails_closed_when_directory_unavailable() -> None:
    def http_get(url: str, timeout_seconds: int) -> str:
        raise URLError("directory unavailable")

    builder = NasdaqTraderStockUniverseBuilder(http_get=http_get)

    assert builder.build() == []


def test_claude_research_output_is_analysis_not_execution_approval() -> None:
    output = ClaudeResearchOutput(
        symbol="AAPL",
        asset_class=AssetClass.STOCK,
        trade_thesis="Research thesis",
        bull_case="Bull case",
        bear_case="Bear case",
        key_catalysts=[],
        major_risks=[],
        confidence_score=90,
        opportunity_score=90,
        suggested_direction="long",
        suggested_strategy="Research only",
        time_horizon="days",
        needs_human_review=True,
    )

    assert output.needs_human_review is True
    assert not hasattr(output, "approved")


def test_production_code_has_no_embedded_market_fixtures() -> None:
    root = Path(__file__).resolve().parents[1]
    banned = ["mock", "fake", "dummy", "random", "hardcoded"]
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for token in banned:
            if token in text:
                offenders.append(f"{path.name}:{token}")

    assert offenders == []


class FixtureContract:
    conId = 123
    symbol = "MSFT"
    secType = "STK"
    exchange = "SMART"
    currency = "USD"


class FixtureContractDetails:
    contract = FixtureContract()


class FixtureScannerRow:
    contractDetails = FixtureContractDetails()


class FixtureScannerConnection:
    def reqScannerData(self, subscription):
        assert subscription.instrument == "STK"
        assert subscription.scanCode == "HOT_BY_VOLUME"
        assert subscription.locationCode == "STK.US.MAJOR"
        assert subscription.numberOfRows == 10
        return [FixtureScannerRow()]


class FixtureScannerClient:
    def connect(self):
        return FixtureScannerConnection()


def test_ibkr_scanner_builds_real_source_instruments_from_api_rows(monkeypatch) -> None:
    # Importing the IBKR SDK opens an asyncio wakeup socket on Windows.
    monkeypatch.setitem(sys.modules, "ib_insync", SimpleNamespace(ScannerSubscription=SimpleNamespace))
    builder = IBKRScannerUniverseBuilder(
        client=FixtureScannerClient(),
        scan_codes=["HOT_BY_VOLUME"],
        location_code="STK.US.MAJOR",
        max_results=10,
    )

    instruments = builder.build()

    assert len(instruments) == 1
    assert instruments[0].symbol == "MSFT"
    assert instruments[0].data_provider == "IBKR"


class FixtureBar:
    def __init__(self, index: int) -> None:
        self.date = f"2026-05-{index:02d}"
        self.open = 100.0 + index
        self.high = 101.0 + index
        self.low = 99.0 + index
        self.close = 100.5 + index
        self.volume = 1000 + index


class FixtureTicker:
    bid = 151.0
    ask = 151.1
    close = 150.0
    volume = 5000

    def marketPrice(self) -> float:
        return 151.05


class FixtureMarketDataClient:
    def connect(self):
        return self

    def qualify_contract_object(self, instrument):
        return FixtureContract()

    def reqTickers(self, contract):
        return [FixtureTicker()]

    def reqHistoricalData(self, *args, **kwargs):
        return [FixtureBar(index) for index in range(1, 61)]


def test_ibkr_market_data_provider_returns_available_real_source_summary() -> None:
    instrument = TradableInstrument(
        symbol="MSFT",
        asset_class=AssetClass.STOCK,
        exchange="SMART",
        currency="USD",
        data_provider="IBKR",
    )
    provider = IBKRResearchMarketDataProvider(client=FixtureMarketDataClient())

    summary = provider.get_market_data(instrument)

    assert summary.status == DataStatus.AVAILABLE
    assert summary.provider == "ibkr"
    assert summary.quote["last"] == 151.05
    assert len(summary.historical_ohlcv) == 60


class FixtureNoQuoteClient(FixtureMarketDataClient):
    def reqTickers(self, contract):
        return []


def test_ibkr_market_data_provider_rejects_when_quote_unavailable() -> None:
    instrument = TradableInstrument(
        symbol="MSFT",
        asset_class=AssetClass.STOCK,
        exchange="SMART",
        currency="USD",
        data_provider="IBKR",
    )
    provider = IBKRResearchMarketDataProvider(client=FixtureNoQuoteClient())

    summary = provider.get_market_data(instrument)

    assert summary.status == DataStatus.UNAVAILABLE
    assert summary.reason == "IBKR returned no quote"


def test_alpha_vantage_news_provider_builds_news_focused_universe_from_provider_feed() -> None:
    def http_get(url: str, timeout_seconds: int) -> dict[str, object]:
        assert "function=NEWS_SENTIMENT" in url
        assert "topics=earnings" in url
        assert timeout_seconds == 10
        return {
            "feed": [
                {
                    "title": "Microsoft cloud demand improves",
                    "url": "https://example.com/msft",
                    "source": "Example Wire",
                    "time_published": "20260514T130000",
                    "summary": "Brief market summary",
                    "overall_sentiment_score": "0.35",
                    "overall_sentiment_label": "Somewhat-Bullish",
                    "ticker_sentiment": [
                        {
                            "ticker": "MSFT",
                            "relevance_score": "0.82",
                            "ticker_sentiment_score": "0.42",
                            "ticker_sentiment_label": "Bullish",
                        }
                    ],
                }
            ]
        }

    provider = AlphaVantageNewsProvider(
        api_key="test-key",
        topics=["earnings"],
        lookback_minutes=1440,
        max_articles=50,
        max_symbols=10,
        per_symbol_limit=5,
        min_relevance_score=0.2,
        allowed_asset_classes=[AssetClass.STOCK],
        http_get=http_get,
    )

    instruments = provider.discover_instruments()

    assert len(instruments) == 1
    assert instruments[0].symbol == "MSFT"
    assert instruments[0].asset_class == AssetClass.STOCK
    assert instruments[0].contract_details["discovery_source"] == "news_catalyst"
    assert instruments[0].contract_details["requires_news_context"] is True


def test_alpha_vantage_news_provider_marks_news_unavailable_without_api_key() -> None:
    provider = AlphaVantageNewsProvider(
        api_key="",
        topics=["earnings"],
        lookback_minutes=1440,
        max_articles=50,
        max_symbols=10,
        per_symbol_limit=5,
        min_relevance_score=0.2,
        allowed_asset_classes=[AssetClass.STOCK],
    )
    instrument = TradableInstrument(
        symbol="MSFT",
        asset_class=AssetClass.STOCK,
        exchange="SMART",
        currency="USD",
    )

    result = provider.get_news_for_instrument(instrument)

    assert result.status == DataStatus.UNAVAILABLE
    assert "ALPHA_VANTAGE_API_KEY" in (result.reason or "")
    assert provider.discover_instruments() == []


def test_news_focused_candidate_requires_real_news_context() -> None:
    instrument = TradableInstrument(
        symbol="MSFT",
        asset_class=AssetClass.STOCK,
        exchange="SMART",
        currency="USD",
        contract_details={"requires_news_context": True},
    )
    market_data = MarketDataSummary(
        status=DataStatus.AVAILABLE,
        provider="fixture",
        as_of=datetime.utcnow(),
        quote={"spread_pct": 0.001, "volume": 1000},
    )
    candidate = build_scanner_registry(0.5)[AssetClass.STOCK].scan(instrument, market_data)

    decision = build_gate().evaluate(candidate)

    assert decision.status == ResearchDecisionStatus.REJECTED
    assert "News-focused candidate requires real news context" in decision.reasons


class FixtureNewsProvider:
    provider_name = "fixture_news"

    def get_news_for_instrument(self, instrument):
        return NewsFetchResult(
            status=DataStatus.AVAILABLE,
            provider=self.provider_name,
            as_of=datetime.utcnow(),
            catalysts=[
                {
                    "provider": self.provider_name,
                    "title": f"{instrument.symbol} earnings catalyst",
                    "source": "Fixture Wire",
                    "published_at": datetime.utcnow().isoformat(),
                    "summary": "Brief catalyst summary",
                    "ticker_sentiment": [{"ticker": instrument.symbol, "relevance_score": "0.9"}],
                }
            ],
        )

    def discover_instruments(self):
        return []


class FixturePipelineMarketDataProvider:
    provider_name = "fixture_market"

    def get_market_data(self, instrument):
        return MarketDataSummary(
            status=DataStatus.AVAILABLE,
            provider=self.provider_name,
            as_of=datetime.utcnow(),
            quote={"last": 100.0, "spread_pct": 0.001, "volume": 1000, "trend": "up"},
            historical_ohlcv=[
                {"date": "2026-05-13", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 1000}
            ],
        )


class FixturePortfolioProvider:
    provider_name = "fixture_portfolio"

    def get_context(self):
        return {"status": "available", "provider": self.provider_name}


class FixtureAnalystService:
    def __init__(self) -> None:
        self.candidate = None

    def review(self, candidate):
        self.candidate = candidate
        return ClaudeResearchOutput(
            symbol=candidate.instrument.symbol,
            asset_class=candidate.asset_class,
            trade_thesis="News-backed research thesis",
            bull_case="Bull case",
            bear_case="Bear case",
            key_catalysts=["earnings catalyst"],
            major_risks=[],
            confidence_score=70,
            opportunity_score=65,
            suggested_direction="long",
            suggested_strategy="Research only",
            time_horizon="days",
            needs_human_review=True,
        )


def test_pipeline_attaches_news_context_before_claude_receives_candidate(tmp_path) -> None:
    analyst = FixtureAnalystService()
    pipeline = MultiAssetResearchPipeline(
        universe_builders=[ConfiguredSymbolUniverseBuilder(AssetClass.STOCK, ["MSFT"])],
        market_data_provider=FixturePipelineMarketDataProvider(),
        news_provider=FixtureNewsProvider(),
        portfolio_context_provider=FixturePortfolioProvider(),
        scanners=build_scanner_registry(0.5),
        risk_gate=build_gate(),
        claude_decision_service=analyst,
        research_store=ResearchStore(SQLiteStore(str(tmp_path / "research.sqlite3"))),
        logger=logging.getLogger("test"),
        max_candidates_for_claude=10,
    )

    decisions = pipeline.run()

    assert decisions[0].status == ResearchDecisionStatus.ANALYZED
    assert analyst.candidate is not None
    assert analyst.candidate.news_context["items"][0]["title"] == "MSFT earnings catalyst"
    assert analyst.candidate.market_data_summary.news_status == DataStatus.AVAILABLE
