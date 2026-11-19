from __future__ import annotations

from app.models import OrderApproval, PortfolioSnapshot, TradeIntent
from app.execution.risk.constraints import ConstraintChecker
from app.execution.risk.portfolio_checks import PortfolioChecker
from app.execution.risk.position_sizer import PositionSizer


class OrderGate:
    def __init__(
        self,
        constraint_checker: ConstraintChecker,
        position_sizer: PositionSizer,
        portfolio_checker: PortfolioChecker,
    ) -> None:
        self.constraint_checker = constraint_checker
        self.position_sizer = position_sizer
        self.portfolio_checker = portfolio_checker

    def approve(
        self,
        intent: TradeIntent,
        portfolio: PortfolioSnapshot,
        daily_new_exposure: float = 0.0,
    ) -> OrderApproval:
        constraint_result = self.constraint_checker.evaluate(intent, portfolio)
        if not constraint_result.approved:
            return constraint_result

        position_size, risk_amount = self.position_sizer.calculate_size(intent, portfolio)
        if intent.stop_price is None:
            return OrderApproval(approved=False, reasons=["No-trade: stop cannot be computed"])

        portfolio_result = self.portfolio_checker.evaluate(intent, portfolio, position_size, daily_new_exposure)
        if not portfolio_result.approved:
            portfolio_result.risk_amount = risk_amount
            return portfolio_result

        return OrderApproval(
            approved=True,
            reasons=[],
            position_size=position_size,
            risk_amount=risk_amount,
            estimated_exposure=portfolio_result.estimated_exposure,
        )
