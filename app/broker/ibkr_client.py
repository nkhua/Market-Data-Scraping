from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from app.models import AssetClass, TradableInstrument


@dataclass
class IBKRClient:
    host: str
    port: int
    client_id: int
    account_id: str
    _ib: Any | None = field(default=None, init=False, repr=False)

    def connect(self) -> Any:
        if self._ib is not None and self._ib.isConnected():
            return self._ib
        try:
            from ib_insync import IB
        except ImportError as exc:
            raise RuntimeError("ib-insync is required for IBKR connectivity") from exc
        ib = IB()
        ib.connect(self.host, self.port, clientId=self.client_id, readonly=True)
        self._ib = ib
        return ib

    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    def account_summary(self) -> dict[str, Any]:
        ib = self.connect()
        rows = ib.accountSummary(account=self.account_id)
        return {row.tag: row.value for row in rows}

    def positions(self) -> list[dict[str, Any]]:
        ib = self.connect()
        return [
            {
                "account": row.account,
                "contract": {
                    "conId": row.contract.conId,
                    "symbol": row.contract.symbol,
                    "secType": row.contract.secType,
                    "exchange": row.contract.exchange,
                    "currency": row.contract.currency,
                },
                "position": row.position,
                "avgCost": row.avgCost,
            }
            for row in ib.positions()
            if not self.account_id or row.account == self.account_id
        ]

    def qualify_contract(self, instrument: TradableInstrument) -> dict[str, Any]:
        first = self.qualify_contract_object(instrument)
        return {
            "conId": first.conId,
            "symbol": first.symbol,
            "secType": first.secType,
            "exchange": first.exchange,
            "currency": first.currency,
            "lastTradeDateOrContractMonth": getattr(first, "lastTradeDateOrContractMonth", ""),
            "strike": getattr(first, "strike", 0.0),
            "right": getattr(first, "right", ""),
            "multiplier": getattr(first, "multiplier", ""),
        }

    def qualify_contract_object(self, instrument: TradableInstrument) -> Any:
        ib = self.connect()
        contract = self.build_contract(instrument)
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            raise RuntimeError(f"IBKR contract lookup returned no contract for {instrument.symbol}")
        return qualified[0]

    def build_contract(self, instrument: TradableInstrument) -> Any:
        try:
            from ib_insync import Contract, Future, Option, Stock
        except ImportError as exc:
            raise RuntimeError("ib-insync is required for IBKR contract lookup") from exc

        details = instrument.contract_details
        if instrument.asset_class in {AssetClass.STOCK, AssetClass.ETF}:
            return Stock(instrument.symbol, instrument.exchange, instrument.currency)
        if instrument.asset_class == AssetClass.OPTION:
            return Option(
                instrument.symbol,
                str(details.get("expiry", "")),
                float(details.get("strike", 0.0)),
                str(details.get("right", "")),
                instrument.exchange,
                currency=instrument.currency,
            )
        if instrument.asset_class == AssetClass.FUTURE:
            return Future(
                instrument.symbol,
                str(details.get("expiry", "")),
                instrument.exchange,
                currency=instrument.currency,
            )
        return Contract(
            symbol=instrument.symbol,
            secType=details.get("secType", instrument.asset_class.value.upper()),
            exchange=instrument.exchange,
            currency=instrument.currency,
        )

    def validate_live_mode(self, paper: bool) -> None:
        if paper:
            return
        env_name = os.getenv("ENV", "paper").strip().lower()
        paper_trading = os.getenv("PAPER_TRADING", "true").strip().lower()
        ack = os.getenv("LIVE_TRADING_ACK", "false").strip().lower()
        if env_name != "live" or paper_trading != "false" or ack != "true":
            raise RuntimeError(
                "Live trading is blocked. Required environment flags are ENV=live, "
                "PAPER_TRADING=false, and LIVE_TRADING_ACK=true."
            )
