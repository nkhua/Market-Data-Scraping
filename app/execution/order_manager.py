from __future__ import annotations

from app.broker.ibkr_client import IBKRClient
from app.models import OrderRequest, OrderResult


class OrderManager:
    def __init__(self, client: IBKRClient, dry_run: bool = True) -> None:
        self.client = client
        self.dry_run = dry_run

    def submit_order(self, order: OrderRequest) -> OrderResult:
        self.client.validate_live_mode(order.paper)
        if self.dry_run:
            return OrderResult(
                accepted=False,
                broker_order_id=None,
                status="not_submitted",
                message="Dry-run mode enabled. Order was not sent to broker.",
            )

        return OrderResult(
            accepted=False,
            status="blocked",
            message="Broker order submission is unavailable until the IBKR execution adapter is enabled.",
        )
