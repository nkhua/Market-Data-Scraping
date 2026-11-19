from __future__ import annotations

from app.models import PortfolioSnapshot, TradeIntent


class PositionSizer:
    def __init__(
        self,
        method: str,
        max_risk_per_trade_pct: float,
        max_position_exposure_pct: float | None = None,
    ) -> None:
        self.method = method
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_position_exposure_pct = max_position_exposure_pct

    def calculate_size(self, intent: TradeIntent, portfolio: PortfolioSnapshot) -> tuple[int, float]:
        if intent.stop_price is None or intent.entry_price <= 0 or portfolio.equity <= 0:
            return 0, 0.0

        risk_per_share = abs(intent.entry_price - intent.stop_price)
        if risk_per_share <= 0:
            return 0, 0.0

        risk_budget = portfolio.equity * self.max_risk_per_trade_pct
        shares_by_risk = int(risk_budget / risk_per_share)
        shares_by_buying_power = int(max(portfolio.buying_power, 0.0) / intent.entry_price)
        max_shares = min(shares_by_risk, shares_by_buying_power)
        if self.max_position_exposure_pct is not None:
            max_position_notional = portfolio.equity * self.max_position_exposure_pct
            max_shares = min(max_shares, int(max_position_notional / intent.entry_price))

        if self.method == "equal_weight":
            notional_budget = portfolio.equity / max(len(portfolio.positions) + 1, 1)
            max_shares = min(max_shares, int(notional_budget / intent.entry_price))

        shares = max(max_shares, 0)
        return max(shares, 0), shares * risk_per_share
