from __future__ import annotations

import logging

from app.research.discovery.providers import DiscoveryProvider
from app.models import DiscoveryContext, DiscoveryEvidence
from app.storage.discovery_store import DiscoveryStore
from app.storage.journal import TradeJournal


class DiscoveryService:
    def __init__(
        self,
        providers: list[DiscoveryProvider],
        discovery_store: DiscoveryStore,
        journal: TradeJournal,
        logger: logging.Logger | None = None,
    ) -> None:
        self.providers = providers
        self.discovery_store = discovery_store
        self.journal = journal
        self.logger = logger or logging.getLogger("trading_bot.discovery")

    def discover(self, context: DiscoveryContext) -> list[DiscoveryEvidence]:
        evidence_items: list[DiscoveryEvidence] = []
        for provider in self.providers:
            provider_items = provider.discover(context)
            for item in provider_items:
                self.logger.info(
                    "Discovered symbol %s from %s with source_type=%s",
                    item.symbol,
                    item.provider_name,
                    item.source_type.value,
                )
                row_id = self.discovery_store.save_evidence(item)
                self.journal.log_discovery_evidence(
                    item.symbol,
                    item.model_dump(mode="json") | {"discovery_evidence_id": row_id},
                )
                self.logger.info(
                    "Evidence added for %s from %s: %s",
                    item.symbol,
                    item.provider_name,
                    item.trigger_reason,
                )
            evidence_items.extend(provider_items)
        return evidence_items
