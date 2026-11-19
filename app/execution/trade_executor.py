from __future__ import annotations

import logging

from app.execution.order_manager import OrderManager
from app.models import (
    AccountAutonomyState,
    AnalystResponse,
    AutonomyAction,
    AutonomyDecision,
    OrderRequest,
    PortfolioSnapshot,
    ReviewQueueItem,
    TradeIntent,
)
from app.execution.risk.autonomy_engine import AutonomyEngine
from app.execution.risk.order_gate import OrderGate
from app.storage.journal import TradeJournal
from app.storage.review_queue import ReviewQueue


class TradeExecutor:
    def __init__(
        self,
        order_gate: OrderGate,
        autonomy_engine: AutonomyEngine,
        order_manager: OrderManager,
        journal: TradeJournal,
        review_queue: ReviewQueue,
        paper: bool,
    ) -> None:
        self.order_gate = order_gate
        self.autonomy_engine = autonomy_engine
        self.order_manager = order_manager
        self.journal = journal
        self.review_queue = review_queue
        self.paper = paper
        self.logger = logging.getLogger("trading_bot.execution")

    def submit_trade(
        self,
        intent: TradeIntent,
        portfolio: PortfolioSnapshot,
        analyst_review: AnalystResponse | None,
        account_state: AccountAutonomyState,
        daily_new_exposure: float = 0.0,
    ):
        risk_approval = self.order_gate.approve(intent, portfolio, daily_new_exposure=daily_new_exposure)
        autonomy_decision = self.autonomy_engine.classify(intent, risk_approval, analyst_review, account_state)
        self.journal.log_autonomy_decision(intent.symbol, autonomy_decision.model_dump(mode="json"))
        self.logger.info(
            "Risk classification result for %s: %s reasons=%s",
            intent.symbol,
            autonomy_decision.action.value,
            autonomy_decision.reasons,
        )

        if autonomy_decision.action == AutonomyAction.BLOCKED:
            self.logger.info("Trade blocked for %s: %s", intent.symbol, autonomy_decision.reasons)
            self.journal.log_order_rejection(intent.symbol, autonomy_decision.model_dump(mode="json"))
            return autonomy_decision, None

        if autonomy_decision.action == AutonomyAction.APPROVAL_REQUIRED:
            queue_item = ReviewQueueItem(
                symbol=intent.symbol,
                reasons=autonomy_decision.reasons,
                trade_intent=intent.model_dump(mode="json"),
                risk_approval=risk_approval.model_dump(mode="json"),
                analyst_review=analyst_review.model_dump(mode="json") if analyst_review else None,
                account_state=account_state.model_dump(mode="json"),
            )
            queue_id = self.review_queue.enqueue(queue_item)
            payload = queue_item.model_dump(mode="json") | {"queue_id": queue_id}
            self.journal.log_review_queue(intent.symbol, payload)
            self.logger.info("Trade queued for approval for %s with queue_id=%s", intent.symbol, queue_id)
            return autonomy_decision, None

        self.logger.info(
            "Risk engine approved %s with position_size=%s estimated_exposure=%.2f",
            intent.symbol,
            risk_approval.position_size,
            risk_approval.estimated_exposure,
        )
        order_request = OrderRequest(
            symbol=intent.symbol,
            side=intent.side,
            quantity=risk_approval.position_size,
            order_type="LMT",
            limit_price=intent.entry_price,
            paper=self.paper,
            metadata=intent.metadata | {"setup_source": intent.setup_source},
        )
        self.journal.log_order_approval(intent.symbol, risk_approval.model_dump(mode="json"))
        result = self.order_manager.submit_order(order_request)
        self.journal.log_order_submission(intent.symbol, result.model_dump(mode="json"))
        self.logger.info(
            "Order submitted for %s with status=%s accepted=%s",
            intent.symbol,
            result.status,
            result.accepted,
        )
        if result.status == "filled":
            self.logger.info("Order filled for %s", intent.symbol)
            self.journal.log_fill(intent.symbol, result.model_dump(mode="json"))
        if result.status == "cancelled":
            self.logger.info("Order cancelled for %s", intent.symbol)
        return autonomy_decision, result
