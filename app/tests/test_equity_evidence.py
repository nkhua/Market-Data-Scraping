from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml

from app import main
from app.config import DEFAULT_SETTINGS_PATH, Settings
from app.models import DataStatus, MarketDataSummary, NewsFetchResult
from app.research.earnings import SEC_TICKERS_URL, AlphaVantageIncomeProvider, SECEarningsProvider, parse_sec_earnings
from app.research.price_check import AlphaVantageCloseCheck


def sec_row(value, *, start="2025-01-01", end="2025-03-31", filed="2025-04-24", form="10-Q"):
    return {"val": value, "start": start, "end": end, "filed": filed, "form": form, "accn": "0000000042-25-000001"}


def sec_payload(*, revenue_rows=None):
    return {"cik": 42, "facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {
            "USD": revenue_rows if revenue_rows is not None else [sec_row(10_000_000)],
        }},
        "NetIncomeLoss": {"units": {"USD": [sec_row(1_000_000)]}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": [sec_row("1.05")]}},
    }}}


def test_sec_normalization_uses_recent_durations_and_ignores_future_and_ambiguous_facts():
    facts = parse_sec_earnings(sec_payload(revenue_rows=[
        sec_row(44_000_000, start="2024-01-01", end="2024-12-31", filed="2025-02-20", form="10-K"),
        sec_row(12_000_000, start="2024-10-01", end="2024-12-31", filed="2025-02-20", form="10-K"),
        sec_row(10_000_000),
        sec_row(10_100_000, filed="2025-05-01", form="10-Q/A"),
        sec_row(25_000_000, start="2025-01-01", end="2025-06-30", filed="2025-07-15"),
        sec_row(100, start="2025-04-01", end="2025-06-30", filed="2025-08-01"),
    ]), 42, date(2025, 7, 31))
    values = {(fact.period, fact.metric): fact.value for fact in facts}
    assert values == {
        ("quarter", "revenue"): 10_100_000, ("quarter", "net_income"): 1_000_000,
        ("quarter", "diluted_eps"): Decimal("1.05"), ("year", "revenue"): 44_000_000,
    }
    assert any(fact.source_url.endswith("0000000042-25-000001-index.htm") for fact in facts)
    ambiguous = parse_sec_earnings(sec_payload(revenue_rows=[sec_row(10), sec_row(20)]), 42, date(2025, 7, 31))
    assert {fact.metric for fact in ambiguous} == {"diluted_eps", "net_income"}


def test_unavailable_feeds_are_reported_without_leaking_api_key():
    def fail(request, timeout):
        raise OSError(request.full_url)

    result = AlphaVantageIncomeProvider("private-fixture-key", http_get=fail).fetch("TST")
    assert not result.facts
    assert "private-fixture-key" not in result.model_dump_json()
    rejected = AlphaVantageIncomeProvider("key", http_get=lambda *_: {"Information": "message"}).fetch("TST")
    assert not rejected.facts
    assert "rate-limited" in rejected.reason
    assert not SECEarningsProvider("", http_get=fail).fetch("TST").facts


@pytest.mark.parametrize("case", ["match", "conflict", "incomparable", "bad_citation", "rejected_market"])
def test_research_cycle_validates_and_persists_equity_evidence(tmp_path, monkeypatch, case):
    today = datetime.now(timezone.utc).date()
    session = (today - timedelta(days=2)).isoformat()
    market = MarketDataSummary(
        status=DataStatus.AVAILABLE, provider="ibkr", as_of=datetime.utcnow(), regular_session_daily_bars=True,
        quote={"spread_pct": 0.001, "volume": 1_000_000, "last": 20.0},
        historical_ohlcv=[{"date": session, "close": 20.0}, {"date": today.isoformat(), "close": 25.0}],
    )

    class Market:
        def get_market_data(self, instrument):
            if case == "rejected_market":
                return MarketDataSummary(status=DataStatus.UNAVAILABLE, provider="ibkr", reason="No market data")
            return market

    class News:
        def get_news_for_instrument(self, instrument):
            return NewsFetchResult(status=DataStatus.AVAILABLE, provider="alpha_vantage", catalysts=[{
                "title": "Quarterly results coverage", "source": "Fixture Wire", "url": "https://news.example/results",
            }])

    requests = []

    def sec_get(request, timeout):
        assert request.get_header("User-agent") == "Test Research analyst@example.com"
        requests.append(request.full_url)
        if request.full_url == SEC_TICKERS_URL:
            return {"0": {"ticker": "TST", "cik_str": 42}}
        assert request.full_url.endswith("CIK0000000042.json")
        return sec_payload()

    def alpha_get(request, timeout):
        args = parse_qs(urlsplit(request.full_url).query)
        assert args["symbol"] == ["TST"]
        requests.append(args["function"][0])
        if args["function"] == ["INCOME_STATEMENT"]:
            return {"symbol": "TST", "quarterlyReports": [
                {"fiscalDateEnding": "2025-03-31", "reportedCurrency": "CAD", "totalRevenue": "10000000"},
                {"fiscalDateEnding": "2024-03-31", "reportedCurrency": "USD", "totalRevenue": "10000000"},
                {"fiscalDateEnding": "2025-03-31", "reportedCurrency": "USD",
                 "totalRevenue": "9500000" if case == "conflict" else "None" if case == "incomparable" else "10000001",
                 "netIncome": "1000000"},
            ]}
        assert args["function"] == ["TIME_SERIES_DAILY"]
        return {
            "Meta Data": {"2. Symbol": "TST", "5. Time Zone": "US/Eastern"},
            "Time Series (Daily)": {
                today.isoformat(): {"4. close": "25.00"},
                **({} if case == "incomparable" else {
                    session: {"4. close": "18.00" if case == "conflict" else "20.01"},
                }),
            },
        }

    class ResearchClient:
        def __init__(self, **kwargs):
            pass

        def analyze(self, prompt):
            data = json.loads(prompt.split("\nInput JSON:\n```json\n", 1)[1].removesuffix("\n```"))
            assert data["market_data_summary"]["quote"]["last"] == 20
            assert data["evidence"]["filings"]["facts"]
            assert {source["id"] for source in data["evidence"]["sources"]} >= {
                "market-data", "news-1", "filing-quarter-revenue", "check-quarter-revenue", "check-daily-close",
            }
            return {
                "symbol": "TST", "asset_class": "stock", "trade_thesis": "Quarterly report and price context",
                "bull_case": "Volume supports liquidity", "bear_case": "Earnings remain a risk",
                "key_catalysts": ["Recent quarterly results"], "major_risks": [], "confidence_score": 70,
                "opportunity_score": 70, "suggested_direction": "long", "suggested_strategy": "research",
                "suggested_entry": 20, "suggested_stop_loss": 18, "suggested_take_profit": 23,
                "time_horizon": "one week", "needs_human_review": False,
                "citations": {"trade_thesis": ["invented" if case == "bad_citation" else "filing-quarter-revenue"],
                              "bull_case": ["market-data"], "bear_case": ["check-quarter-revenue"],
                              "key_catalysts": [["news-1"]], "major_risks": []},
            }

    raw = yaml.safe_load(DEFAULT_SETTINGS_PATH.read_text(encoding="utf-8"))
    raw["app"]["state_db_path"] = str(tmp_path / "research.sqlite3")
    raw["universe"]["stock_symbols"] = ["TST"]
    raw["research"].update(sec_edgar_user_agent="Test Research analyst@example.com", alpha_vantage_api_key="test-key")
    settings = Settings.model_validate(raw)
    monkeypatch.setattr(main, "load_settings", lambda *_: settings)
    monkeypatch.setattr(main, "build_research_market_data_provider", lambda *_: Market())
    monkeypatch.setattr(main, "build_research_news_provider", lambda *_: News())
    monkeypatch.setattr(main, "SECEarningsProvider", lambda agent: SECEarningsProvider(agent, http_get=sec_get))
    monkeypatch.setattr(main, "AlphaVantageIncomeProvider", lambda key: AlphaVantageIncomeProvider(key, http_get=alpha_get))
    monkeypatch.setattr(main, "AlphaVantageCloseCheck", lambda key: AlphaVantageCloseCheck(key, http_get=alpha_get))
    monkeypatch.setattr(main, "ClaudeClient", ResearchClient)

    services = main.build_services()
    result, = main.run_research_cycle(services)

    if case == "rejected_market":
        assert not requests
        assert result["status"] == "rejected"
        assert result["candidate"]["evidence"] is None
        assert result["claude_analysis"] is None
        return

    assert requests == [SEC_TICKERS_URL, "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000042.json",
                        "INCOME_STATEMENT", "TIME_SERIES_DAILY"]
    evidence = result["candidate"]["evidence"]
    checks = {check["primary"]["metric"]: check["status"] for check in evidence["checks"]}
    assert checks == {
        "revenue": {"conflict": "conflict", "incomparable": "unverified"}.get(case, "matched"),
        "net_income": "matched", "diluted_eps": "unverified",
    }
    assert evidence["close_check"]["session"] == session
    assert evidence["close_check"]["status"] == checks["revenue"]
    analysis = result["claude_analysis"]
    if case == "bad_citation":
        assert result["status"] == "rejected" and analysis is None
        assert "unknown evidence citation" in result["reasons"][0]
    else:
        assert result["status"] == "analyzed"
        assert analysis["citations"]["key_catalysts"] == [["news-1"]]
        assert analysis["suggested_direction"] == ("avoid" if case == "conflict" else "long")
    if case == "conflict":
        assert analysis["needs_human_review"]
        assert analysis["suggested_entry"] is None
        assert analysis["citations"]["major_risks"] == [["check-quarter-revenue"], ["check-daily-close"]]
    with services.research_pipeline.research_store.store.connect() as connection:
        decision_payload, = connection.execute("SELECT payload FROM risk_decisions").fetchone()
        signal_payload, = connection.execute("SELECT payload FROM research_signals").fetchone()
        assert json.loads(decision_payload)["candidate"]["evidence"] == evidence
        assert json.loads(signal_payload)["evidence"] == evidence
        analyses = connection.execute("SELECT payload FROM claude_analysis").fetchall()
        assert [json.loads(payload) for payload, in analyses] == ([analysis] if analysis else [])
