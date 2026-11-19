from __future__ import annotations

from app.models import MonitorTrigger, TriggerType


class PriceMonitor:
    def __init__(self, unusual_move_pct: float) -> None:
        self.unusual_move_pct = unusual_move_pct

    def evaluate(self, price_change_pct: float, symbol: str) -> MonitorTrigger | None:
        if abs(price_change_pct) < self.unusual_move_pct:
            return None
        strength = min(abs(price_change_pct) / max(self.unusual_move_pct * 2, 0.0001), 1.0)
        return MonitorTrigger(
            symbol=symbol,
            trigger_type=TriggerType.PRICE_MOVE,
            reason=f"Daily move of {price_change_pct:.2%} exceeded threshold {self.unusual_move_pct:.2%}",
            strength=strength,
            metadata={"price_change_pct": price_change_pct},
        )
