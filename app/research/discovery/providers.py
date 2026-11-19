from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from app.models import DiscoveryContext, DiscoveryEvidence, EvidenceSourceType


class DiscoveryProvider(Protocol):
    name: str
    source_type: EvidenceSourceType

    def discover(self, context: DiscoveryContext) -> list[DiscoveryEvidence]:
        ...


@dataclass
class WebSearchDiscoveryProvider:
    name: str = "web_search"
    source_type: EvidenceSourceType = EvidenceSourceType.NEWS
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.discovery.web"))

    def discover(self, context: DiscoveryContext) -> list[DiscoveryEvidence]:
        self.logger.info(
            "Web search discovery provider is not configured in %s mode with base_universe_size=%s",
            context.mode,
            len(context.base_universe_symbols),
        )
        return []


@dataclass
class EarningsCalendarDiscoveryProvider:
    name: str = "earnings_calendar"
    source_type: EvidenceSourceType = EvidenceSourceType.EARNINGS
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.discovery.earnings"))

    def discover(self, context: DiscoveryContext) -> list[DiscoveryEvidence]:
        self.logger.info(
            "Earnings calendar provider is not configured with trigger window=%s day(s)",
            context.earnings_window_days,
        )
        return []


@dataclass
class MarketMoversDiscoveryProvider:
    name: str = "market_movers"
    source_type: EvidenceSourceType = EvidenceSourceType.MOVER
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.discovery.movers"))

    def discover(self, context: DiscoveryContext) -> list[DiscoveryEvidence]:
        self.logger.info(
            "Market movers provider is not configured with unusual_move_pct=%s volatility_threshold=%s",
            context.unusual_move_pct,
            context.volatility_trigger_threshold,
        )
        return []


@dataclass
class FilingsDiscoveryProvider:
    name: str = "filings"
    source_type: EvidenceSourceType = EvidenceSourceType.FILING
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.discovery.filings"))

    def discover(self, context: DiscoveryContext) -> list[DiscoveryEvidence]:
        if not context.include_filings:
            return []
        self.logger.info("Filings provider is not configured")
        return []


@dataclass
class CatalystPagesDiscoveryProvider:
    name: str = "catalyst_pages"
    source_type: EvidenceSourceType = EvidenceSourceType.CATALYST
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.discovery.catalyst"))

    def discover(self, context: DiscoveryContext) -> list[DiscoveryEvidence]:
        if not context.include_catalyst_pages:
            return []
        self.logger.info("Catalyst pages provider is not configured")
        return []


def build_discovery_providers(enabled_sources: list[str]) -> list[DiscoveryProvider]:
    registry: dict[str, DiscoveryProvider] = {
        "web_search": WebSearchDiscoveryProvider(),
        "earnings_calendar": EarningsCalendarDiscoveryProvider(),
        "market_movers": MarketMoversDiscoveryProvider(),
        "filings": FilingsDiscoveryProvider(),
        "catalyst_pages": CatalystPagesDiscoveryProvider(),
    }
    providers: list[DiscoveryProvider] = []
    for name in enabled_sources:
        provider = registry.get(name)
        if provider is not None:
            providers.append(provider)
    return providers
