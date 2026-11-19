from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from time import monotonic, sleep
from typing import Literal
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.models import EarningsFact, EarningsResult


Period = Literal["quarter", "year"]
JsonReader = Callable[[Request, int], dict]
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_REPORT_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A"}
SEC_METRICS = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
    "net_income": ("NetIncomeLoss",),
    "diluted_eps": ("EarningsPerShareDiluted",),
}
ALPHA_DOCS = "https://www.alphavantage.co/documentation/#income-statement"


def mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def rows(value: object) -> list[dict]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def parse_date(value: object) -> date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    return None


def decimal_value(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def read_json(request: Request, timeout_seconds: int) -> dict:
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.load(response, parse_float=Decimal)
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    return payload


def _sec_fact(metric: str, tag: str, row: dict, cik: int, today: date) -> EarningsFact | None:
    start = parse_date(row.get("start"))
    end = parse_date(row.get("end"))
    filed = parse_date(row.get("filed"))
    value = decimal_value(row.get("val"))
    accession = str(row.get("accn", ""))
    if (
        not start or not end or not filed or not end <= filed <= today or value is None
        or row.get("form") not in SEC_REPORT_FORMS or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession)
    ):
        return None
    duration = (end - start).days + 1
    if 70 <= duration <= 110:
        period: Period = "quarter"
    elif 330 <= duration <= 390 and row["form"] in {"10-K", "10-K/A"}:
        period = "year"
    else:
        return None
    return EarningsFact(
        metric=metric,
        period=period,
        period_end=end,
        value=value,
        unit="USD/share" if metric == "diluted_eps" else "USD",
        filed_on=filed,
        source_url=f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm",
        source_field=f"us-gaap:{tag}",
    )


def parse_sec_earnings(payload: dict, cik: int, today: date) -> list[EarningsFact]:
    taxonomy = mapping(mapping(payload.get("facts")).get("us-gaap"))
    by_period = defaultdict(list)
    for metric, tags in SEC_METRICS.items():
        unit = "USD/shares" if metric == "diluted_eps" else "USD"
        for priority, tag in enumerate(tags):
            units = mapping(mapping(taxonomy.get(tag)).get("units"))
            for row in rows(units.get(unit)):
                fact = _sec_fact(metric, tag, row, cik, today)
                if fact:
                    by_period[fact.period].append((priority, fact))

    latest = []
    for facts in by_period.values():
        period_end = max(fact.period_end for _, fact in facts)
        for metric in SEC_METRICS:
            options = [(priority, fact) for priority, fact in facts if fact.period_end == period_end and fact.metric == metric]
            if not options:
                continue
            # Keep the most recently filed version of the preferred taxonomy tag.
            preferred_tag = min(priority for priority, _ in options)
            preferred = [fact for priority, fact in options if priority == preferred_tag]
            newest_filing = max(fact.filed_on for fact in preferred)
            best = [fact for fact in preferred if fact.filed_on == newest_filing]
            if len({fact.value for fact in best}) == 1:
                latest.append(min(best, key=lambda fact: fact.source_url))
    return latest


@dataclass
class SECEarningsProvider:
    user_agent: str
    timeout_seconds: int = 10
    http_get: JsonReader = read_json
    _tickers: dict[str, set[int]] = field(default_factory=dict, init=False)
    _directory_loaded_at: float | None = field(default=None, init=False)
    _next_request: float = field(default=0.0, init=False)

    def _request(self, url: str) -> dict:
        delay = self._next_request - monotonic()
        if delay > 0:
            sleep(delay)
        self._next_request = monotonic() + 0.2
        return self.http_get(Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}), self.timeout_seconds)

    @staticmethod
    def _ticker(symbol: str) -> str:
        return symbol.strip().upper().replace(".", "-")

    def _directory(self) -> dict[str, set[int]]:
        if self._directory_loaded_at is None or monotonic() - self._directory_loaded_at >= 86_400:
            tickers = defaultdict(set)
            for entry in self._request(SEC_TICKERS_URL).values():
                ticker = mapping(entry).get("ticker")
                cik = mapping(entry).get("cik_str")
                if isinstance(ticker, str) and type(cik) is int and 0 < cik <= 9_999_999_999:
                    tickers[self._ticker(ticker)].add(cik)
            if not tickers:
                raise ValueError("Empty SEC ticker directory")
            self._tickers = dict(tickers)
            self._directory_loaded_at = monotonic()
        return self._tickers

    def fetch(self, symbol: str) -> EarningsResult:
        provider = "sec_edgar"
        if not self.user_agent.strip():
            return EarningsResult(provider=provider, reason="SEC_EDGAR_USER_AGENT is not configured")
        try:
            ciks = self._directory().get(self._ticker(symbol), set())
            if len(ciks) != 1:
                return EarningsResult(provider=provider, reason="No unique SEC issuer for ticker")
            cik = next(iter(ciks))
            payload = self._request(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
        except (OSError, ValueError):
            return EarningsResult(provider=provider, reason="SEC EDGAR data request failed or returned invalid JSON")
        if payload.get("cik") != cik:
            return EarningsResult(provider=provider, reason="SEC response issuer did not match the requested CIK")
        facts = parse_sec_earnings(payload, cik, datetime.now(timezone.utc).date())
        return EarningsResult(provider=provider, facts=facts, reason=None if facts else "No usable US GAAP filing facts")


@dataclass
class AlphaVantageIncomeProvider:
    api_key: str
    timeout_seconds: int = 10
    http_get: JsonReader = read_json

    def fetch(self, symbol: str) -> EarningsResult:
        provider = "alpha_vantage"
        if not self.api_key.strip():
            return EarningsResult(provider=provider, reason="ALPHA_VANTAGE_API_KEY is not configured")
        params = urlencode({"function": "INCOME_STATEMENT", "symbol": symbol, "apikey": self.api_key})
        try:
            payload = self.http_get(Request(f"https://www.alphavantage.co/query?{params}"), self.timeout_seconds)
        except (OSError, ValueError):
            return EarningsResult(provider=provider, reason="Alpha Vantage income statement request failed")
        if any(payload.get(key) for key in ("Error Message", "Note", "Information")):
            return EarningsResult(provider=provider, reason="Alpha Vantage rejected or rate-limited the income statement request")
        if str(payload.get("symbol", "")).upper() != symbol.upper():
            return EarningsResult(provider=provider, reason="Income statement response did not match the requested ticker")

        facts = []
        today = datetime.now(timezone.utc).date()
        for key, period in (("quarterlyReports", "quarter"), ("annualReports", "year")):
            for row in rows(payload.get(key)):
                end = parse_date(row.get("fiscalDateEnding"))
                currency = row.get("reportedCurrency")
                if not end or end > today or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
                    continue
                for metric, source_field in (("revenue", "totalRevenue"), ("net_income", "netIncome")):
                    value = decimal_value(row.get(source_field))
                    if value is not None:
                        facts.append(EarningsFact(
                            metric=metric, period=period, period_end=end, unit=currency, value=value,
                            source_url=ALPHA_DOCS, source_field=source_field,
                        ))
        return EarningsResult(provider=provider, facts=facts, reason=None if facts else "No usable income statement facts")
