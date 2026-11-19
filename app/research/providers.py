from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from app.models import AssetClass, DataStatus, MarketDataSummary, NewsFetchResult, TradableInstrument


class InstrumentUniverseBuilder(Protocol):
    asset_class: AssetClass

    def build(self) -> list[TradableInstrument]:
        ...


class ResearchMarketDataProvider(Protocol):
    provider_name: str

    def get_market_data(self, instrument: TradableInstrument) -> MarketDataSummary:
        ...


class ResearchNewsProvider(Protocol):
    provider_name: str

    def get_news_for_instrument(self, instrument: TradableInstrument) -> NewsFetchResult:
        ...

    def discover_instruments(self) -> list[TradableInstrument]:
        ...


class PortfolioContextProvider(Protocol):
    provider_name: str

    def get_context(self) -> dict[str, object]:
        ...


@dataclass
class ConfiguredSymbolUniverseBuilder:
    asset_class: AssetClass
    symbols: list[str]
    exchange: str = "SMART"
    currency: str = "USD"

    def build(self) -> list[TradableInstrument]:
        return [
            TradableInstrument(
                symbol=symbol.strip().upper(),
                asset_class=self.asset_class,
                exchange=self.exchange,
                currency=self.currency,
                contract_details={},
                is_tradeable=True,
                data_provider=None,
                broker_provider="IBKR",
            )
            for symbol in self.symbols
            if symbol.strip()
        ]


@dataclass
class ConfiguredContractUniverseBuilder:
    asset_class: AssetClass
    contracts: list[dict[str, object]]

    def build(self) -> list[TradableInstrument]:
        instruments: list[TradableInstrument] = []
        for contract in self.contracts:
            symbol = str(contract.get("symbol", "")).strip().upper()
            if not symbol:
                continue
            instruments.append(
                TradableInstrument(
                    symbol=symbol,
                    asset_class=self.asset_class,
                    exchange=str(contract.get("exchange", "SMART")),
                    currency=str(contract.get("currency", "USD")),
                    contract_details=dict(contract.get("contract_details", {})),
                    is_tradeable=bool(contract.get("is_tradeable", True)),
                    data_provider=None,
                    broker_provider=str(contract.get("broker_provider", "IBKR")),
                )
            )
        return instruments


@dataclass
class UnavailableResearchMarketDataProvider:
    provider_name: str = "unavailable"
    reason: str = "MARKET_DATA_PROVIDER is not configured"
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.data"))

    def get_market_data(self, instrument: TradableInstrument) -> MarketDataSummary:
        self.logger.info(
            "Market data unavailable for %s %s: %s",
            instrument.asset_class.value,
            instrument.symbol,
            self.reason,
        )
        return MarketDataSummary(
            status=DataStatus.UNAVAILABLE,
            provider=self.provider_name,
            reason=self.reason,
        )


@dataclass
class UnavailablePortfolioContextProvider:
    provider_name: str = "unavailable"
    reason: str = "IBKR account context is unavailable"

    def get_context(self) -> dict[str, object]:
        return {"status": "unavailable", "provider": self.provider_name, "reason": self.reason}
