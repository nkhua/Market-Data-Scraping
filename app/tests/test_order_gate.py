from app.models import PortfolioSnapshot, TradeIntent
from app.execution.risk.constraints import ConstraintChecker
from app.execution.risk.order_gate import OrderGate
from app.execution.risk.portfolio_checks import PortfolioChecker
from app.execution.risk.position_sizer import PositionSizer


def test_order_gate_approves_valid_trade() -> None:
    gate = OrderGate(
        constraint_checker=ConstraintChecker(allowed_symbols=["AAPL"], require_hard_stop=True),
        position_sizer=PositionSizer(method="fixed_fractional", max_risk_per_trade_pct=0.01),
        portfolio_checker=PortfolioChecker(
            max_open_positions=5,
            max_portfolio_exposure_pct=0.50,
            max_daily_new_exposure_pct=0.20,
            max_sector_exposure_pct=0.25,
        ),
    )
    portfolio = PortfolioSnapshot(equity=100_000, cash=50_000, buying_power=100_000, positions=[])
    intent = TradeIntent(
        symbol="AAPL",
        side="BUY",
        entry_price=100.0,
        stop_price=95.0,
        take_profit_price=110.0,
        setup_source="test",
        metadata={"sector": "Technology"},
    )

    result = gate.approve(intent, portfolio, daily_new_exposure=0.0)

    assert result.approved
    assert result.position_size == 200


def test_order_gate_rejects_missing_stop() -> None:
    gate = OrderGate(
        constraint_checker=ConstraintChecker(allowed_symbols=["AAPL"], require_hard_stop=True),
        position_sizer=PositionSizer(method="fixed_fractional", max_risk_per_trade_pct=0.01),
        portfolio_checker=PortfolioChecker(
            max_open_positions=5,
            max_portfolio_exposure_pct=0.50,
            max_daily_new_exposure_pct=0.20,
            max_sector_exposure_pct=0.25,
        ),
    )
    portfolio = PortfolioSnapshot(equity=100_000, cash=50_000, buying_power=100_000, positions=[])
    intent = TradeIntent(
        symbol="AAPL",
        side="BUY",
        entry_price=100.0,
        stop_price=None,
        take_profit_price=110.0,
        setup_source="test",
    )

    result = gate.approve(intent, portfolio, daily_new_exposure=0.0)

    assert not result.approved
    assert "Stop price is required by hard risk settings" in result.reasons


def test_order_gate_rejects_when_daily_exposure_limit_exceeded() -> None:
    gate = OrderGate(
        constraint_checker=ConstraintChecker(allowed_symbols=["AAPL"], require_hard_stop=True),
        position_sizer=PositionSizer(method="fixed_fractional", max_risk_per_trade_pct=0.02),
        portfolio_checker=PortfolioChecker(
            max_open_positions=5,
            max_portfolio_exposure_pct=0.90,
            max_daily_new_exposure_pct=0.05,
            max_sector_exposure_pct=0.50,
        ),
    )
    portfolio = PortfolioSnapshot(equity=100_000, cash=50_000, buying_power=100_000, positions=[])
    intent = TradeIntent(
        symbol="AAPL",
        side="BUY",
        entry_price=100.0,
        stop_price=95.0,
        take_profit_price=110.0,
        setup_source="test",
        metadata={"sector": "Technology"},
    )

    result = gate.approve(intent, portfolio, daily_new_exposure=4_500.0)

    assert not result.approved
    assert "Daily new exposure limit exceeded" in result.reasons


def test_order_gate_rejects_poor_reward_to_risk() -> None:
    gate = OrderGate(
        constraint_checker=ConstraintChecker(
            allowed_symbols=["AAPL"],
            require_hard_stop=True,
            min_reward_to_risk=1.5,
        ),
        position_sizer=PositionSizer(method="fixed_fractional", max_risk_per_trade_pct=0.01),
        portfolio_checker=PortfolioChecker(
            max_open_positions=5,
            max_portfolio_exposure_pct=0.50,
            max_daily_new_exposure_pct=0.20,
            max_sector_exposure_pct=0.25,
        ),
    )
    portfolio = PortfolioSnapshot(equity=100_000, cash=50_000, buying_power=100_000, positions=[])
    intent = TradeIntent(
        symbol="AAPL",
        side="BUY",
        entry_price=100.0,
        stop_price=95.0,
        take_profit_price=102.0,
        setup_source="test",
        metadata={"sector": "Technology"},
    )

    result = gate.approve(intent, portfolio, daily_new_exposure=0.0)

    assert not result.approved
    assert any("Reward/risk" in reason for reason in result.reasons)
