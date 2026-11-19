from __future__ import annotations

from app.models import FilterDecision, PriceSnapshot


class LiquidityFilter:
    def __init__(self, min_price: float, min_average_volume: int, max_spread_pct: float) -> None:
        self.min_price = min_price
        self.min_average_volume = min_average_volume
        self.max_spread_pct = max_spread_pct

    def evaluate(self, snapshot: PriceSnapshot | None) -> FilterDecision:
        reasons: list[str] = []
        if snapshot is None:
            return FilterDecision(passed=False, reasons=["Missing price snapshot"])
        if snapshot.last < self.min_price:
            reasons.append(f"Price {snapshot.last:.2f} below minimum {self.min_price:.2f}")
        if snapshot.average_volume < self.min_average_volume:
            reasons.append(
                f"Average volume {snapshot.average_volume} below minimum {self.min_average_volume}"
            )
        spread_pct = None
        if snapshot.bid and snapshot.ask and snapshot.last > 0:
            spread_pct = (snapshot.ask - snapshot.bid) / snapshot.last
            if spread_pct > self.max_spread_pct:
                reasons.append(f"Spread {spread_pct:.4%} exceeded maximum {self.max_spread_pct:.4%}")
        return FilterDecision(
            passed=not reasons,
            reasons=reasons,
            metrics={"spread_pct": spread_pct, "average_volume": snapshot.average_volume, "last": snapshot.last},
        )
