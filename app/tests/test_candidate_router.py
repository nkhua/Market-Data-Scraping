from app.research.filters.candidate_router import CandidateRouter
from app.research.filters.event_filters import EventFilter
from app.research.filters.liquidity_filters import LiquidityFilter
from app.research.filters.technical_filters import TechnicalFilter
from app.models import CandidateSignal, MonitorTrigger, PriceSnapshot, TriggerType


def test_candidate_router_rejects_on_liquidity_failure() -> None:
    router = CandidateRouter(
        liquidity_filter=LiquidityFilter(min_price=5.0, min_average_volume=1_000_000, max_spread_pct=0.01),
        event_filter=EventFilter(earnings_blackout_days=2),
        technical_filter=TechnicalFilter(),
    )
    candidate = CandidateSignal(
        symbol="XYZ",
        price_snapshot=PriceSnapshot(
            symbol="XYZ",
            last=3.0,
            close=2.8,
            high=3.2,
            low=2.7,
            volume=100_000,
            average_volume=100_000,
            bid=2.99,
            ask=3.01,
            atr=0.2,
            ma_fast=2.9,
            ma_slow=2.8,
        ),
        triggers=[
            MonitorTrigger(
                symbol="XYZ",
                trigger_type=TriggerType.PRICE_MOVE,
                reason="test",
                strength=0.9,
            )
        ],
    )

    routed = router.route(candidate)

    assert not routed.passed
    assert any("liquidity" in reason for reason in routed.rejection_reasons)
