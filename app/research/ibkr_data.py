from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.broker.ibkr_client import IBKRClient
from app.models import AssetClass, DataStatus, MarketDataSummary, TradableInstrument
from app.research.providers import InstrumentUniverseBuilder, PortfolioContextProvider, ResearchMarketDataProvider


@dataclass
class IBKRScannerUniverseBuilder(InstrumentUniverseBuilder):
    client: IBKRClient
    scan_codes: list[str]
    location_code: str
    max_results: int
    asset_class: AssetClass = AssetClass.STOCK
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.ibkr.scanner"))

    def build(self) -> list[TradableInstrument]:
        if not self.scan_codes:
            return []
        try:
            from ib_insync import ScannerSubscription
        except ImportError as exc:
            self.logger.warning("IBKR scanner unavailable: %s", exc)
            return []

        instruments: list[TradableInstrument] = []
        seen: set[str] = set()
        try:
            ib = self.client.connect()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("IBKR scanner connection unavailable: %s", exc)
            return []

        per_scan_rows = max(1, self.max_results)
        for code in self.scan_codes:
            try:
                subscription = ScannerSubscription(
                    instrument="STK",
                    locationCode=self.location_code,
                    scanCode=code,
                    numberOfRows=per_scan_rows,
                )
                rows = ib.reqScannerData(subscription)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("IBKR scanner %s unavailable: %s", code, exc)
                continue

            for row in rows:
                contract = row.contractDetails.contract
                symbol = str(getattr(contract, "symbol", "")).strip().upper()
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                instruments.append(
                    TradableInstrument(
                        symbol=symbol,
                        asset_class=self.asset_class,
                        exchange="SMART",
                        currency=str(getattr(contract, "currency", "USD") or "USD"),
                        contract_details={
                            "conId": getattr(contract, "conId", None),
                            "secType": getattr(contract, "secType", "STK"),
                            "scanner_code": code,
                        },
                        is_tradeable=True,
                        data_provider="IBKR",
                        broker_provider="IBKR",
                    )
                )
                if len(instruments) >= self.max_results:
                    return instruments
        return instruments


@dataclass
class IBKRResearchMarketDataProvider(ResearchMarketDataProvider):
    client: IBKRClient
    historical_duration: str = "3 M"
    historical_bar_size: str = "1 day"
    use_regular_trading_hours: bool = True
    provider_name: str = "ibkr"
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.ibkr.data"))

    def get_market_data(self, instrument: TradableInstrument) -> MarketDataSummary:
        try:
            ib = self.client.connect()
            contract = self.client.qualify_contract_object(instrument)
            tickers = ib.reqTickers(contract)
            bars = ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=self.historical_duration,
                barSizeSetting=self.historical_bar_size,
                whatToShow="TRADES",
                useRTH=self.use_regular_trading_hours,
                formatDate=1,
                keepUpToDate=False,
            )
        except Exception as exc:  # noqa: BLE001
            return self._unavailable(instrument, f"IBKR data request failed: {exc}")

        if not tickers:
            return self._unavailable(instrument, "IBKR returned no quote")
        if not bars:
            return self._unavailable(instrument, "IBKR returned no historical bars")

        ticker = tickers[0]
        quote = self._build_quote(ticker, bars)
        if quote.get("last") is None:
            return self._unavailable(instrument, "IBKR quote did not include a usable market price")
        history = [self._bar_to_dict(bar) for bar in bars]
        return MarketDataSummary(
            status=DataStatus.AVAILABLE,
            provider=self.provider_name,
            as_of=datetime.utcnow(),
            quote=quote,
            historical_ohlcv=history,
            regular_session_daily_bars=self.use_regular_trading_hours and self.historical_bar_size == "1 day",
            futures_contract=self._future_details(instrument, contract),
        )

    def _unavailable(self, instrument: TradableInstrument, reason: str) -> MarketDataSummary:
        self.logger.info("IBKR data unavailable for %s %s: %s", instrument.asset_class.value, instrument.symbol, reason)
        return MarketDataSummary(
            status=DataStatus.UNAVAILABLE,
            provider=self.provider_name,
            reason=reason,
        )

    def _build_quote(self, ticker: Any, bars: list[Any]) -> dict[str, object]:
        last = _first_number(
            _call_or_value(ticker, "marketPrice"),
            getattr(ticker, "last", None),
            getattr(ticker, "close", None),
            bars[-1].close if bars else None,
        )
        bid = _first_number(getattr(ticker, "bid", None))
        ask = _first_number(getattr(ticker, "ask", None))
        spread_pct = None
        if bid is not None and ask is not None and last is not None and ask >= bid and last > 0:
            spread_pct = (ask - bid) / last
        indicators = _indicators(bars)
        return {
            "last": last,
            "bid": bid,
            "ask": ask,
            "close": _first_number(getattr(ticker, "close", None), bars[-1].close if bars else None),
            "volume": _first_number(getattr(ticker, "volume", None), bars[-1].volume if bars else None),
            "spread_pct": spread_pct,
            **indicators,
        }

    def _future_details(self, instrument: TradableInstrument, contract: Any) -> dict[str, object]:
        if instrument.asset_class != AssetClass.FUTURE:
            return {}
        return {
            "expiry": getattr(contract, "lastTradeDateOrContractMonth", None)
            or instrument.contract_details.get("expiry"),
            "multiplier": getattr(contract, "multiplier", None),
        }

    @staticmethod
    def _bar_to_dict(bar: Any) -> dict[str, object]:
        return {
            "date": str(bar.date),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        }


@dataclass
class IBKRPortfolioContextProvider(PortfolioContextProvider):
    client: IBKRClient
    provider_name: str = "ibkr"
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.ibkr.account"))

    def get_context(self) -> dict[str, object]:
        try:
            return {
                "status": "available",
                "provider": self.provider_name,
                "account_summary": self.client.account_summary(),
                "positions": self.client.positions(),
                "captured_at": datetime.utcnow().isoformat(),
            }
        except Exception as exc:  # noqa: BLE001
            self.logger.info("IBKR account context unavailable: %s", exc)
            return {"status": "unavailable", "provider": self.provider_name, "reason": str(exc)}


def _call_or_value(obj: Any, name: str) -> Any:
    value = getattr(obj, name, None)
    if callable(value):
        return value()
    return value


def _first_number(*values: Any) -> float | None:
    for value in values:
        if isinstance(value, int | float) and not math.isnan(float(value)):
            return float(value)
    return None


def _indicators(bars: list[Any]) -> dict[str, object]:
    closes = [float(bar.close) for bar in bars if _first_number(getattr(bar, "close", None)) is not None]
    highs = [float(bar.high) for bar in bars if _first_number(getattr(bar, "high", None)) is not None]
    lows = [float(bar.low) for bar in bars if _first_number(getattr(bar, "low", None)) is not None]
    volumes = [float(bar.volume) for bar in bars if _first_number(getattr(bar, "volume", None)) is not None]
    if not closes:
        return {}
    last_close = closes[-1]
    ma20 = _average(closes[-20:])
    ma50 = _average(closes[-50:])
    prior = closes[-21] if len(closes) > 20 else closes[0]
    momentum = (last_close / prior - 1.0) if prior else None
    high_window = max(highs[-21:-1]) if len(highs) > 20 else max(highs) if highs else None
    breakout = bool(high_window is not None and last_close >= high_window)
    avg_volume = _average(volumes[-21:-1]) if len(volumes) > 20 else _average(volumes)
    volume_spike = bool(avg_volume and volumes and volumes[-1] > avg_volume * 1.5)
    ranges = [high - low for high, low in zip(highs, lows, strict=False)]
    recent_range = _average(ranges[-5:])
    baseline_range = _average(ranges[-25:-5]) if len(ranges) > 25 else _average(ranges)
    volatility_expansion = bool(recent_range and baseline_range and recent_range > baseline_range * 1.25)
    trend = "up" if ma20 and ma50 and last_close > ma20 > ma50 else "not_uptrend"
    return {
        "ma20": ma20,
        "ma50": ma50,
        "momentum": momentum,
        "breakout": breakout,
        "volume_spike": volume_spike,
        "trend": trend,
        "volatility_expansion": volatility_expansion,
    }


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
