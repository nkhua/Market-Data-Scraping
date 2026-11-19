from __future__ import annotations

from datetime import date

from app.models import EarningsEvent, MonitorTrigger, TriggerType


class EarningsMonitor:
    def __init__(self, lookahead_days: int) -> None:
        self.lookahead_days = lookahead_days

    def evaluate(self, earnings_event: EarningsEvent | None) -> MonitorTrigger | None:
        if earnings_event is None:
            return None
        days_until = (earnings_event.earnings_date - date.today()).days
        if days_until < 0 or days_until > self.lookahead_days:
            return None
        return MonitorTrigger(
            symbol=earnings_event.symbol,
            trigger_type=TriggerType.EARNINGS_APPROACHING,
            reason=f"Earnings in {days_until} day(s), timing={earnings_event.timing}",
            strength=max(0.1, 1 - (days_until / max(self.lookahead_days, 1))),
            metadata={"earnings_date": earnings_event.earnings_date.isoformat(), "days_until": days_until},
        )
