from __future__ import annotations

from app.models import OrderApproval, PortfolioSnapshot, TradeIntent


class ConstraintChecker:
    def __init__(
        self,
        allowed_symbols: list[str],
        require_hard_stop: bool = True,
        min_reward_to_risk: float = 1.5,
    ) -> None:
        self.allowed_symbols = {symbol.upper() for symbol in allowed_symbols}
        self.require_hard_stop = require_hard_stop
        self.min_reward_to_risk = min_reward_to_risk

    def evaluate(self, intent: TradeIntent, portfolio: PortfolioSnapshot) -> OrderApproval:
        reasons: list[str] = []
        symbol = intent.symbol.upper()
        if self.allowed_symbols and symbol not in self.allowed_symbols:
            reasons.append(f"Symbol {intent.symbol} is not in the allowed symbol list")
        if intent.side != "BUY":
            reasons.append("Only long BUY entries are supported by the current risk model")
        if intent.entry_price <= 0:
            reasons.append("Entry price must be positive")
        if self.require_hard_stop and intent.stop_price is None:
            reasons.append("Stop price is required by hard risk settings")
        if intent.stop_price is not None:
            if intent.stop_price <= 0:
                reasons.append("Stop price must be positive")
            elif intent.stop_price >= intent.entry_price and intent.side == "BUY":
                reasons.append("Stop price must be below entry for long trades")
        if intent.take_profit_price is None:
            reasons.append("Take-profit price is required by reward/risk settings")
        elif intent.take_profit_price <= 0:
            reasons.append("Take-profit price must be positive")
        elif intent.take_profit_price <= intent.entry_price and intent.side == "BUY":
            reasons.append("Take-profit price must be above entry for long trades")

        if (
            intent.stop_price is not None
            and intent.take_profit_price is not None
            and intent.side == "BUY"
            and 0 < intent.stop_price < intent.entry_price < intent.take_profit_price
        ):
            risk_per_share = intent.entry_price - intent.stop_price
            reward_per_share = intent.take_profit_price - intent.entry_price
            reward_to_risk = reward_per_share / risk_per_share
            if reward_to_risk < self.min_reward_to_risk:
                reasons.append(
                    f"Reward/risk {reward_to_risk:.2f} below minimum {self.min_reward_to_risk:.2f}"
                )
        if portfolio.equity <= 0:
            reasons.append("Portfolio equity must be positive")
        if portfolio.buying_power < 0:
            reasons.append("Portfolio buying power cannot be negative")
        if portfolio.open_orders_exposure < 0:
            reasons.append("Open orders exposure cannot be negative")
        return OrderApproval(approved=not reasons, reasons=reasons)
