from __future__ import annotations

from datetime import date

from app.models import EarningsEvent, FilterDecision


class EventFilter:
    def __init__(self, earnings_blackout_days: int) -> None:
        self.earnings_blackout_days = earnings_blackout_days

    def evaluate(self, earnings_event: EarningsEvent | None) -> FilterDecision:
        if earnings_event is None:
            return FilterDecision(passed=True, reasons=[])
        days_until = (earnings_event.earnings_date - date.today()).days
        if 0 <= days_until <= self.earnings_blackout_days:
            return FilterDecision(
                passed=False,
                reasons=[f"Earnings blackout active: earnings in {days_until} day(s)"],
                metrics={"days_until_earnings": days_until},
            )
        return FilterDecision(passed=True, metrics={"days_until_earnings": days_until})
