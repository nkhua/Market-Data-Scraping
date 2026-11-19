from __future__ import annotations

from app.models import PortfolioPosition


class ExitManager:
    def should_exit(self, position: PortfolioPosition, stop_price: float | None, take_profit_price: float | None) -> str | None:
        if stop_price is not None and position.market_price <= stop_price:
            return "stop_loss_hit"
        if take_profit_price is not None and position.market_price >= take_profit_price:
            return "take_profit_hit"
        return None
