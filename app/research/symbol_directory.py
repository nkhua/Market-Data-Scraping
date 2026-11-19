from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from io import StringIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.models import AssetClass, TradableInstrument
from app.research.providers import InstrumentUniverseBuilder


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


@dataclass
class NasdaqTraderStockUniverseBuilder(InstrumentUniverseBuilder):
    include_etfs: bool = False
    max_symbols: int = 0
    timeout_seconds: int = 10
    nasdaq_listed_url: str = NASDAQ_LISTED_URL
    other_listed_url: str = OTHER_LISTED_URL
    http_get: Callable[[str, int], str] | None = field(default=None, repr=False)
    asset_class: AssetClass = AssetClass.STOCK
    name: str = "all_us_stocks"
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.symbol_directory"))

    def build(self) -> list[TradableInstrument]:
        try:
            nasdaq_text = self._http_get(self.nasdaq_listed_url, self.timeout_seconds)
            other_text = self._http_get(self.other_listed_url, self.timeout_seconds)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            self.logger.warning("Nasdaq Trader stock universe unavailable: %s", exc)
            return []

        instruments = [
            *self._parse_nasdaq_listed(nasdaq_text),
            *self._parse_other_listed(other_text),
        ]
        deduped: dict[str, TradableInstrument] = {}
        for instrument in instruments:
            deduped.setdefault(instrument.symbol, instrument)

        sorted_instruments = sorted(deduped.values(), key=lambda item: item.symbol)
        if self.max_symbols > 0:
            return sorted_instruments[: self.max_symbols]
        return sorted_instruments

    def _http_get(self, url: str, timeout_seconds: int) -> str:
        if self.http_get is not None:
            return self.http_get(url, timeout_seconds)
        request = Request(url, headers={"User-Agent": "trading_bot/1.0"})
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return response.read().decode("utf-8")

    def _parse_nasdaq_listed(self, text: str) -> list[TradableInstrument]:
        rows, created_at = _read_pipe_rows(text)
        instruments: list[TradableInstrument] = []
        for row in rows:
            if row.get("Test Issue") != "N":
                continue
            is_etf = row.get("ETF") == "Y"
            if is_etf and not self.include_etfs:
                continue
            symbol = _clean_symbol(row.get("Symbol", ""))
            if not symbol:
                continue
            instruments.append(
                TradableInstrument(
                    symbol=symbol,
                    asset_class=AssetClass.ETF if is_etf else AssetClass.STOCK,
                    exchange="SMART",
                    currency="USD",
                    contract_details={
                        "universe_source": "nasdaq_trader_symbol_directory",
                        "directory_file": "nasdaqlisted.txt",
                        "file_creation_time": created_at,
                        "security_name": row.get("Security Name"),
                        "primary_listing_exchange": "NASDAQ",
                        "market_category": row.get("Market Category"),
                        "financial_status": row.get("Financial Status"),
                        "round_lot_size": row.get("Round Lot Size"),
                        "is_etf": is_etf,
                    },
                    is_tradeable=True,
                    data_provider="NASDAQ_TRADER",
                    broker_provider="IBKR",
                )
            )
        return instruments

    def _parse_other_listed(self, text: str) -> list[TradableInstrument]:
        rows, created_at = _read_pipe_rows(text)
        instruments: list[TradableInstrument] = []
        for row in rows:
            if row.get("Test Issue") != "N":
                continue
            is_etf = row.get("ETF") == "Y"
            if is_etf and not self.include_etfs:
                continue
            symbol = _clean_symbol(row.get("ACT Symbol", ""))
            if not symbol:
                continue
            instruments.append(
                TradableInstrument(
                    symbol=symbol,
                    asset_class=AssetClass.ETF if is_etf else AssetClass.STOCK,
                    exchange="SMART",
                    currency="USD",
                    contract_details={
                        "universe_source": "nasdaq_trader_symbol_directory",
                        "directory_file": "otherlisted.txt",
                        "file_creation_time": created_at,
                        "security_name": row.get("Security Name"),
                        "primary_listing_exchange": _exchange_name(row.get("Exchange")),
                        "exchange_code": row.get("Exchange"),
                        "cqs_symbol": row.get("CQS Symbol"),
                        "nasdaq_symbol": row.get("NASDAQ Symbol"),
                        "round_lot_size": row.get("Round Lot Size"),
                        "is_etf": is_etf,
                    },
                    is_tradeable=True,
                    data_provider="NASDAQ_TRADER",
                    broker_provider="IBKR",
                )
            )
        return instruments


def _read_pipe_rows(text: str) -> tuple[list[dict[str, str]], str | None]:
    cleaned_lines = [line.strip() for line in text.splitlines() if line.strip()]
    created_at = None
    data_lines: list[str] = []
    for line in cleaned_lines:
        if line.startswith("File Creation Time:"):
            created_at = line.split("|", 1)[0].replace("File Creation Time:", "").strip()
            continue
        data_lines.append(line)
    if not data_lines:
        return [], created_at
    reader = csv.DictReader(StringIO("\n".join(data_lines)), delimiter="|")
    return [dict(row) for row in reader], created_at


def _clean_symbol(value: str) -> str:
    return value.strip().upper()


def _exchange_name(value: str | None) -> str | None:
    exchange_codes = {
        "A": "NYSE MKT",
        "N": "NYSE",
        "P": "NYSE ARCA",
        "Z": "BATS",
        "V": "IEXG",
    }
    if value is None:
        return None
    return exchange_codes.get(value.strip().upper(), value)
