from __future__ import annotations

from collections import defaultdict

from app.models import OrderApproval, PortfolioSnapshot, TradeIntent


class PortfolioChecker:
    def __init__(
        self,
        max_open_positions: int,
        max_portfolio_exposure_pct: float,
        max_daily_new_exposure_pct: float,
        max_sector_exposure_pct: float,
    ) -> None:
        self.max_open_positions = max_open_positions
        self.max_portfolio_exposure_pct = max_portfolio_exposure_pct
        self.max_daily_new_exposure_pct = max_daily_new_exposure_pct
        self.max_sector_exposure_pct = max_sector_exposure_pct

    def evaluate(
        self,
        intent: TradeIntent,
        portfolio: PortfolioSnapshot,
        proposed_quantity: int,
        daily_new_exposure: float,
    ) -> OrderApproval:
        reasons: list[str] = []
        proposed_exposure = proposed_quantity * intent.entry_price
        current_exposure = (
            sum(abs(position.market_value) for position in portfolio.positions)
            + portfolio.open_orders_exposure
        )
        existing_symbols = {position.symbol.upper() for position in portfolio.positions}
        opens_new_symbol = intent.symbol.upper() not in existing_symbols
        if proposed_quantity <= 0:
            reasons.append("Calculated position size is zero")
        if opens_new_symbol and len(existing_symbols) >= self.max_open_positions:
            reasons.append(f"Max open positions reached: {self.max_open_positions}")
        if portfolio.equity <= 0:
            reasons.append("Portfolio equity must be positive")
        elif (current_exposure + proposed_exposure) / portfolio.equity > self.max_portfolio_exposure_pct:
            reasons.append("Portfolio exposure limit exceeded")
        if proposed_exposure > portfolio.buying_power:
            reasons.append("Buying power limit exceeded")
        if (
            portfolio.equity > 0
            and (daily_new_exposure + proposed_exposure) / portfolio.equity > self.max_daily_new_exposure_pct
        ):
            reasons.append("Daily new exposure limit exceeded")

        sector_exposure = defaultdict(float)
        for position in portfolio.positions:
            if position.sector:
                sector_exposure[position.sector.strip().lower()] += abs(position.market_value)
        raw_target_sector = intent.metadata.get("sector")
        target_sector = str(raw_target_sector).strip().lower() if raw_target_sector else ""
        if portfolio.equity > 0 and self.max_sector_exposure_pct > 0 and not target_sector:
            reasons.append("Sector metadata required to evaluate concentration limit")
        if portfolio.equity > 0 and target_sector:
            next_sector_ratio = (sector_exposure[target_sector] + proposed_exposure) / portfolio.equity
            if next_sector_ratio > self.max_sector_exposure_pct:
                reasons.append("Sector exposure limit exceeded")

        return OrderApproval(
            approved=not reasons,
            reasons=reasons,
            position_size=proposed_quantity,
            estimated_exposure=proposed_exposure,
        )
