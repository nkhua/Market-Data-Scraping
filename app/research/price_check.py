from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode
from urllib.request import Request

from app.models import CloseCheck, ResearchCandidate
from app.research.earnings import JsonReader, decimal_value, mapping, parse_date, read_json


ALPHA_DAILY_DOCS = "https://www.alphavantage.co/documentation/#daily"


@dataclass
class AlphaVantageCloseCheck:
    api_key: str
    timeout_seconds: int = 10
    http_get: JsonReader = read_json

    def compare(self, candidate: ResearchCandidate) -> CloseCheck:
        market = candidate.market_data_summary
        if market.provider != "ibkr" or not market.regular_session_daily_bars or candidate.instrument.currency != "USD":
            return CloseCheck(status="unverified", reason="Comparison requires regular-session daily IBKR USD bars")

        today = datetime.now(timezone.utc).date()
        bars = {}
        for row in market.historical_ohlcv:
            session = parse_date(row.get("date"))
            close = decimal_value(row.get("close"))
            if session and today - timedelta(days=7) <= session < today and close is not None and close > 0:
                bars[session] = close
        if not bars:
            return CloseCheck(status="unverified", reason="No completed IBKR daily bar in the last seven days")

        session = max(bars)
        primary = bars[session]
        comparison, reason = self._close(candidate.instrument.symbol, session.isoformat())
        if comparison is None:
            return CloseCheck(status="unverified", session=session, ibkr_close_usd=primary, reason=reason)
        tolerance = max(Decimal("0.01"), primary * Decimal("0.0001"))
        matched = abs(primary - comparison) <= tolerance
        return CloseCheck(
            status="matched" if matched else "conflict", session=session,
            ibkr_close_usd=primary, alpha_vantage_close_usd=comparison, tolerance_usd=tolerance,
            reason="Closes agree within tolerance" if matched else "Closes differ; check split adjustments and feed conventions",
        )

    def _close(self, symbol: str, session: str) -> tuple[Decimal | None, str]:
        if not self.api_key.strip():
            return None, "ALPHA_VANTAGE_API_KEY is not configured"
        params = urlencode({"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": self.api_key})
        try:
            payload = self.http_get(Request(f"https://www.alphavantage.co/query?{params}"), self.timeout_seconds)
        except (OSError, ValueError):
            return None, "Alpha Vantage daily price request failed"
        if any(payload.get(key) for key in ("Error Message", "Note", "Information")):
            return None, "Alpha Vantage rejected or rate-limited the daily price request"
        metadata = mapping(payload.get("Meta Data"))
        if str(metadata.get("2. Symbol", "")).upper() != symbol.upper() or metadata.get("5. Time Zone") != "US/Eastern":
            return None, "Daily price response did not identify the requested US ticker"
        row = mapping(mapping(payload.get("Time Series (Daily)")).get(session))
        close = decimal_value(row.get("4. close"))
        if close is None or close <= 0:
            return None, "No Alpha Vantage close for the same session"
        return close, ""
