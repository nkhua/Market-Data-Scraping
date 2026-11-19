from app.config import AutonomySettings
from app.models import (
    AccountAutonomyState,
    AnalystDecision,
    AnalystResponse,
    AutonomyAction,
    ConvictionBucket,
    OrderApproval,
    TradeIntent,
)
from app.execution.risk.autonomy_engine import AutonomyEngine


def build_engine() -> AutonomyEngine:
    settings = AutonomySettings(
        auto_execute_enabled=True,
        require_analyst_for_auto_execute=True,
        require_analyst_for_approval=False,
        auto_execute_min_confidence=0.85,
        approval_required_min_confidence=0.55,
        auto_execute_allowed_catalysts=["momentum", "headline"],
        approval_required_allowed_catalysts=["momentum", "headline", "earnings", "volatility", "other"],
        auto_execute_allowed_conviction_buckets=["high"],
        approval_required_allowed_conviction_buckets=["low", "medium", "high"],
        blocked_risk_tags=["data_missing", "regulatory_halt"],
        approval_required_risk_tags=["earnings_uncertainty", "macro_event"],
        downgrade_after_losing_streak=3,
        downgrade_daily_drawdown_pct=0.02,
        shutdown_total_drawdown_pct=0.10,
    )
    return AutonomyEngine(settings)


def build_intent(conviction: ConvictionBucket = ConvictionBucket.HIGH) -> TradeIntent:
    return TradeIntent(
        symbol="AAPL",
        side="BUY",
        entry_price=100.0,
        stop_price=95.0,
        take_profit_price=110.0,
        setup_source="test",
        conviction=conviction,
        metadata={"sector": "Technology"},
    )


def build_approval(approved: bool = True) -> OrderApproval:
    return OrderApproval(
        approved=approved,
        reasons=[] if approved else ["Hard risk rejection"],
        position_size=100,
        risk_amount=500.0,
        estimated_exposure=10_000.0,
    )


def build_review(
    confidence: float,
    decision: AnalystDecision = AnalystDecision.ALLOW,
    catalyst: str = "momentum",
    conviction: ConvictionBucket = ConvictionBucket.HIGH,
    risk_tags: list[str] | None = None,
) -> AnalystResponse:
    return AnalystResponse(
        decision=decision,
        confidence=confidence,
        summary="Test setup",
        key_risks=["Normal pullback risk"],
        risk_tags=risk_tags or [],
        catalyst_classification=catalyst,
        suggested_conviction_bucket=conviction,
    )


def test_auto_execute_classification() -> None:
    engine = build_engine()
    decision = engine.classify(
        intent=build_intent(),
        risk_approval=build_approval(),
        analyst_review=build_review(confidence=0.90),
        account_state=AccountAutonomyState(),
    )

    assert decision.action == AutonomyAction.AUTO_EXECUTE
    assert decision.base_action == AutonomyAction.AUTO_EXECUTE


def test_approval_required_classification() -> None:
    engine = build_engine()
    decision = engine.classify(
        intent=build_intent(conviction=ConvictionBucket.MEDIUM),
        risk_approval=build_approval(),
        analyst_review=build_review(confidence=0.70, conviction=ConvictionBucket.MEDIUM),
        account_state=AccountAutonomyState(),
    )

    assert decision.action == AutonomyAction.APPROVAL_REQUIRED
    assert decision.base_action == AutonomyAction.APPROVAL_REQUIRED


def test_blocked_classification() -> None:
    engine = build_engine()
    decision = engine.classify(
        intent=build_intent(),
        risk_approval=build_approval(),
        analyst_review=build_review(confidence=0.90, risk_tags=["data_missing"]),
        account_state=AccountAutonomyState(),
    )

    assert decision.action == AutonomyAction.BLOCKED
    assert "Blocked risk tags present" in decision.reasons[0]


def test_analyst_reject_blocks_even_with_high_confidence() -> None:
    engine = build_engine()
    decision = engine.classify(
        intent=build_intent(),
        risk_approval=build_approval(),
        analyst_review=build_review(confidence=0.95, decision=AnalystDecision.REJECT),
        account_state=AccountAutonomyState(),
    )

    assert decision.action == AutonomyAction.BLOCKED
    assert decision.base_action == AutonomyAction.BLOCKED
    assert "Analyst decision rejected the trade" in decision.reasons


def test_analyst_review_decision_cannot_auto_execute() -> None:
    engine = build_engine()
    decision = engine.classify(
        intent=build_intent(),
        risk_approval=build_approval(),
        analyst_review=build_review(confidence=0.95, decision=AnalystDecision.REVIEW),
        account_state=AccountAutonomyState(),
    )

    assert decision.action == AutonomyAction.APPROVAL_REQUIRED
    assert decision.base_action == AutonomyAction.APPROVAL_REQUIRED
    assert "Analyst decision requires manual review" in decision.reasons


def test_downgrade_behavior_after_losses_and_drawdown() -> None:
    engine = build_engine()
    decision = engine.classify(
        intent=build_intent(),
        risk_approval=build_approval(),
        analyst_review=build_review(confidence=0.90),
        account_state=AccountAutonomyState(
            consecutive_losses=3,
            daily_drawdown_pct=0.03,
            total_drawdown_pct=0.05,
        ),
    )

    assert decision.base_action == AutonomyAction.AUTO_EXECUTE
    assert decision.action == AutonomyAction.BLOCKED
    assert decision.downgrade_steps_applied == 2
