from app.models import PortfolioSnapshot, TradeIntent
from app.execution.risk.constraints import ConstraintChecker


def test_constraints_reject_symbol_not_in_allowlist() -> None:
    checker = ConstraintChecker(allowed_symbols=["AAPL"], require_hard_stop=True)
    portfolio = PortfolioSnapshot(equity=100_000, cash=50_000, buying_power=100_000, positions=[])
    intent = TradeIntent(
        symbol="TSLA",
        side="BUY",
        entry_price=100.0,
        stop_price=95.0,
        take_profit_price=110.0,
        setup_source="test",
    )

    result = checker.evaluate(intent, portfolio)

    assert not result.approved
    assert "not in the allowed symbol list" in result.reasons[0]
