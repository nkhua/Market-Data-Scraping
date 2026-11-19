from app.models import PortfolioSnapshot, TradeIntent
from app.execution.risk.position_sizer import PositionSizer


def test_fixed_fractional_position_size_uses_risk_budget() -> None:
    portfolio = PortfolioSnapshot(equity=100_000, cash=50_000, buying_power=100_000, positions=[])
    intent = TradeIntent(
        symbol="AAPL",
        side="BUY",
        entry_price=100.0,
        stop_price=95.0,
        take_profit_price=110.0,
        setup_source="test",
    )

    sizer = PositionSizer(method="fixed_fractional", max_risk_per_trade_pct=0.01)
    shares, risk_amount = sizer.calculate_size(intent, portfolio)

    assert shares == 200
    assert risk_amount == 1000.0


def test_equal_weight_position_size_uses_notional_budget() -> None:
    portfolio = PortfolioSnapshot(equity=90_000, cash=50_000, buying_power=90_000, positions=[])
    intent = TradeIntent(
        symbol="MSFT",
        side="BUY",
        entry_price=300.0,
        stop_price=290.0,
        take_profit_price=330.0,
        setup_source="test",
    )

    sizer = PositionSizer(method="equal_weight", max_risk_per_trade_pct=0.01)
    shares, risk_amount = sizer.calculate_size(intent, portfolio)

    assert shares == 90
    assert risk_amount == 900.0


def test_position_size_is_zero_when_stop_missing() -> None:
    portfolio = PortfolioSnapshot(equity=100_000, cash=50_000, buying_power=100_000, positions=[])
    intent = TradeIntent(
        symbol="AAPL",
        side="BUY",
        entry_price=100.0,
        stop_price=None,
        take_profit_price=110.0,
        setup_source="test",
    )

    sizer = PositionSizer(method="fixed_fractional", max_risk_per_trade_pct=0.01)
    shares, risk_amount = sizer.calculate_size(intent, portfolio)

    assert shares == 0
    assert risk_amount == 0.0


def test_position_size_is_capped_by_buying_power() -> None:
    portfolio = PortfolioSnapshot(equity=100_000, cash=5_000, buying_power=5_000, positions=[])
    intent = TradeIntent(
        symbol="AAPL",
        side="BUY",
        entry_price=100.0,
        stop_price=95.0,
        take_profit_price=110.0,
        setup_source="test",
    )

    sizer = PositionSizer(method="fixed_fractional", max_risk_per_trade_pct=0.01)
    shares, risk_amount = sizer.calculate_size(intent, portfolio)

    assert shares == 50
    assert risk_amount == 250.0


def test_position_size_is_capped_by_single_position_exposure() -> None:
    portfolio = PortfolioSnapshot(equity=100_000, cash=100_000, buying_power=100_000, positions=[])
    intent = TradeIntent(
        symbol="AAPL",
        side="BUY",
        entry_price=100.0,
        stop_price=99.0,
        take_profit_price=103.0,
        setup_source="test",
    )

    sizer = PositionSizer(
        method="fixed_fractional",
        max_risk_per_trade_pct=0.01,
        max_position_exposure_pct=0.10,
    )
    shares, risk_amount = sizer.calculate_size(intent, portfolio)

    assert shares == 100
    assert risk_amount == 100.0
