from __future__ import annotations

from app.models import MonitorTrigger, TriggerType


class VolatilityMonitor:
    def __init__(self, threshold_ratio: float) -> None:
        self.threshold_ratio = threshold_ratio

    def evaluate(self, atr: float | None, baseline_atr: float | None, symbol: str) -> MonitorTrigger | None:
        if not atr or not baseline_atr or baseline_atr <= 0:
            return None
        ratio = atr / baseline_atr
        if ratio < self.threshold_ratio:
            return None
        return MonitorTrigger(
            symbol=symbol,
            trigger_type=TriggerType.VOLATILITY_EXPANSION,
            reason=f"ATR expansion ratio {ratio:.2f} exceeded threshold {self.threshold_ratio:.2f}",
            strength=min(ratio / (self.threshold_ratio * 1.5), 1.0),
            metadata={"atr": atr, "baseline_atr": baseline_atr, "ratio": ratio},
        )
