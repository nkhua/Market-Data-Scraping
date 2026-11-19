from __future__ import annotations

from app.models import CandidateSignal, FilterDecision


class TechnicalFilter:
    def __init__(self, require_price_above_fast_ma: bool = True) -> None:
        self.require_price_above_fast_ma = require_price_above_fast_ma

    def evaluate(self, candidate: CandidateSignal) -> FilterDecision:
        snapshot = candidate.price_snapshot
        if snapshot is None:
            return FilterDecision(passed=False, reasons=["Missing snapshot for technical evaluation"])

        reasons: list[str] = []
        trigger_kinds = {trigger.trigger_type.value for trigger in candidate.triggers}

        if snapshot.ma_fast is None or snapshot.ma_slow is None:
            reasons.append("Missing moving average data")
        else:
            if snapshot.ma_fast <= snapshot.ma_slow:
                reasons.append("Fast moving average is not above slow moving average")
            if self.require_price_above_fast_ma and snapshot.last <= snapshot.ma_fast:
                reasons.append("Price is not above fast moving average")

        allowed_entry = (
            "price_move" in trigger_kinds
            or "headline" in trigger_kinds
            or "research" in trigger_kinds
        )
        if not allowed_entry:
            reasons.append("No simple entry trigger present after monitor stage")

        return FilterDecision(
            passed=not reasons,
            reasons=reasons,
            metrics={
                "last": snapshot.last,
                "ma_fast": snapshot.ma_fast,
                "ma_slow": snapshot.ma_slow,
                "trigger_count": len(candidate.triggers),
            },
        )
