from __future__ import annotations

from app.models import HeadlineItem, MonitorTrigger, TriggerType


class HeadlinesMonitor:
    def __init__(self, keywords: list[str]) -> None:
        self.keywords = [keyword.lower() for keyword in keywords]

    def evaluate(self, symbol: str, headlines: list[HeadlineItem]) -> list[MonitorTrigger]:
        triggers: list[MonitorTrigger] = []
        for item in headlines:
            headline_text = item.headline.lower()
            if any(keyword in headline_text for keyword in self.keywords):
                triggers.append(
                    MonitorTrigger(
                        symbol=symbol,
                        trigger_type=TriggerType.HEADLINE,
                        reason=f"Headline matched watch keywords: {item.headline}",
                        strength=min(max(item.relevance_score, 0.1), 1.0),
                        metadata={"headline": item.headline, "source": item.source},
                    )
                )
        return triggers
