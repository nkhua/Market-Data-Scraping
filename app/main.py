from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.claude.client import ClaudeClient
from app.claude.decision_service import ClaudeDecisionService
from app.config import Settings, load_settings
from app.broker.ibkr_client import IBKRClient
from app.logger import configure_logging
from app.models import AssetClass, ResearchDecision
from app.research.earnings import AlphaVantageIncomeProvider, SECEarningsProvider
from app.research.evidence import EquityEvidenceService
from app.research.ibkr_data import IBKRPortfolioContextProvider, IBKRResearchMarketDataProvider, IBKRScannerUniverseBuilder
from app.research.news import AlphaVantageNewsProvider, NewsCatalystUniverseBuilder, UnavailableResearchNewsProvider
from app.research.pipeline import MultiAssetResearchPipeline
from app.research.price_check import AlphaVantageCloseCheck
from app.research.providers import (
    ConfiguredContractUniverseBuilder,
    ConfiguredSymbolUniverseBuilder,
    UnavailablePortfolioContextProvider,
    UnavailableResearchMarketDataProvider,
)
from app.research.risk import ResearchRiskGate
from app.research.scanners import build_scanner_registry
from app.research.symbol_directory import NasdaqTraderStockUniverseBuilder
from app.scheduler import Scheduler
from app.storage.research_store import ResearchStore
from app.storage.sqlite_store import SQLiteStore


@dataclass
class ApplicationServices:
    settings: Settings
    logger: logging.Logger
    research_pipeline: MultiAssetResearchPipeline
    scheduler: Scheduler


def build_services(settings_path: str | None = None) -> ApplicationServices:
    settings = load_settings(settings_path)
    logger = configure_logging(settings.app.log_level)
    store = SQLiteStore(settings.app.state_db_path)
    ibkr_client = IBKRClient(
        host=settings.broker.host,
        port=settings.broker.port,
        client_id=settings.broker.client_id,
        account_id=settings.broker.account_id,
    )
    research_store = ResearchStore(store)
    research_market_data_provider = build_research_market_data_provider(settings, ibkr_client)
    research_news_provider = build_research_news_provider(settings)
    research_pipeline = MultiAssetResearchPipeline(
        universe_builders=build_universe_builders(settings, ibkr_client, research_news_provider),
        market_data_provider=research_market_data_provider,
        news_provider=research_news_provider,
        portfolio_context_provider=build_portfolio_context_provider(settings, ibkr_client),
        scanners=build_scanner_registry(settings.research.min_liquidity_threshold),
        risk_gate=ResearchRiskGate(
            allowed_asset_classes=[AssetClass(item) for item in settings.research.allowed_asset_classes],
            max_data_age_seconds=settings.research.max_data_age_seconds,
            min_liquidity_threshold=settings.research.min_liquidity_threshold,
            allow_shorting=settings.research.allow_shorting,
            allow_naked_options=settings.research.allow_naked_options,
        ),
        claude_decision_service=ClaudeDecisionService(
            enabled=settings.claude.enabled,
            client=ClaudeClient(
                model=settings.claude.model,
                timeout_seconds=settings.claude.timeout_seconds,
                max_tokens=settings.claude.max_tokens,
            ),
        ),
        research_store=research_store,
        logger=logging.getLogger("trading_bot.research"),
        max_candidates_for_claude=settings.research.max_candidates_for_claude,
        equity_evidence_service=EquityEvidenceService(
            filings=SECEarningsProvider(settings.research.sec_edgar_user_agent),
            comparison=AlphaVantageIncomeProvider(settings.research.alpha_vantage_api_key),
            price_comparison=AlphaVantageCloseCheck(settings.research.alpha_vantage_api_key),
        ),
    )
    return ApplicationServices(
        settings=settings,
        logger=logger,
        research_pipeline=research_pipeline,
        scheduler=Scheduler(settings.discovery.frequency_seconds),
    )


def build_universe_builders(settings: Settings, ibkr_client: IBKRClient, research_news_provider):
    builders = [
        ConfiguredSymbolUniverseBuilder(AssetClass.STOCK, settings.universe.stock_symbols),
        ConfiguredSymbolUniverseBuilder(AssetClass.ETF, settings.universe.etf_symbols),
        ConfiguredContractUniverseBuilder(AssetClass.OPTION, settings.universe.option_contracts),
        ConfiguredContractUniverseBuilder(AssetClass.FUTURE, settings.universe.future_contracts),
        ConfiguredSymbolUniverseBuilder(AssetClass.FOREX, settings.universe.forex_pairs, exchange="IDEALPRO"),
        ConfiguredSymbolUniverseBuilder(AssetClass.CRYPTO, settings.universe.crypto_symbols, exchange="PAXOS"),
        ConfiguredContractUniverseBuilder(AssetClass.BOND, settings.universe.bond_contracts),
    ]
    provider_name = settings.research.market_data_provider.strip().lower()
    if (
        settings.research.all_stocks_universe_enabled
        and "stock" in settings.research.allowed_asset_classes
        and provider_name == "ibkr"
    ):
        builders.append(
            NasdaqTraderStockUniverseBuilder(
                include_etfs=settings.research.all_stocks_include_etfs,
                max_symbols=settings.research.all_stocks_max_symbols,
                timeout_seconds=settings.research.all_stocks_request_timeout_seconds,
            )
        )
    if provider_name == "ibkr" and settings.research.ibkr_stock_scanner_enabled:
        builders.append(
            IBKRScannerUniverseBuilder(
                client=ibkr_client,
                scan_codes=settings.research.ibkr_stock_scanner_codes,
                location_code=settings.research.ibkr_stock_scanner_location_code,
                max_results=settings.research.ibkr_stock_scanner_max_results,
            )
        )
    if settings.research.news_focus_enabled:
        builders.append(NewsCatalystUniverseBuilder(research_news_provider))
    return builders


def build_research_market_data_provider(settings: Settings, ibkr_client: IBKRClient):
    provider_name = settings.research.market_data_provider.strip().lower()
    if provider_name == "ibkr":
        return IBKRResearchMarketDataProvider(
            client=ibkr_client,
            historical_duration=settings.research.historical_duration,
            historical_bar_size=settings.research.historical_bar_size,
        )
    return UnavailableResearchMarketDataProvider(
        provider_name=provider_name or "unavailable",
        reason=(
            "MARKET_DATA_PROVIDER is not configured"
            if not provider_name
            else f"Market data provider {provider_name!r} is not implemented"
        ),
    )


def build_research_news_provider(settings: Settings):
    provider_name = settings.research.news_data_provider.strip().lower()
    if provider_name == "alpha_vantage":
        return AlphaVantageNewsProvider(
            api_key=settings.research.alpha_vantage_api_key,
            topics=settings.research.news_focus_topics,
            lookback_minutes=settings.research.news_focus_lookback_minutes,
            max_articles=settings.research.news_focus_max_articles,
            max_symbols=settings.research.news_focus_max_symbols,
            per_symbol_limit=settings.research.news_per_symbol_limit,
            min_relevance_score=settings.research.news_min_relevance_score,
            timeout_seconds=settings.research.news_request_timeout_seconds,
            allowed_asset_classes=[AssetClass(item) for item in settings.research.allowed_asset_classes],
            known_etf_symbols={symbol.strip().upper() for symbol in settings.universe.etf_symbols if symbol.strip()},
        )
    return UnavailableResearchNewsProvider(
        provider_name=provider_name or "unavailable",
        reason=(
            "NEWS_DATA_PROVIDER is not configured"
            if not provider_name
            else f"News data provider {provider_name!r} is not implemented"
        ),
    )


def build_portfolio_context_provider(settings: Settings, ibkr_client: IBKRClient):
    if settings.research.market_data_provider.strip().lower() == "ibkr":
        return IBKRPortfolioContextProvider(ibkr_client)
    return UnavailablePortfolioContextProvider()


def run_research_cycle(services: ApplicationServices) -> list[dict[str, Any]]:
    decisions: list[ResearchDecision] = services.research_pipeline.run()
    return [decision.model_dump(mode="json") for decision in decisions]


def run_once(settings_path: str | None = None, symbols: list[str] | None = None) -> list[dict[str, Any]]:
    if symbols:
        raise RuntimeError(
            "Explicit runtime symbols are disabled. Configure universe providers instead of passing symbol lists."
        )
    services = build_services(settings_path)
    if services.settings.app.trading_mode != "research_only":
        services.logger.warning(
            "Trading mode %s requested, but execution remains disabled until the IBKR execution adapter is wired.",
            services.settings.app.trading_mode,
        )
    return run_research_cycle(services)


def run_forever(settings_path: str | None = None) -> None:
    services = build_services(settings_path)
    services.scheduler.run_forever(lambda: run_research_cycle(services))


if __name__ == "__main__":
    run_once()
