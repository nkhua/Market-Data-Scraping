from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.models import AssetClass, DataStatus, NewsFetchResult, TradableInstrument
from app.research.providers import InstrumentUniverseBuilder, ResearchNewsProvider


@dataclass
class UnavailableResearchNewsProvider(ResearchNewsProvider):
    provider_name: str = "unavailable"
    reason: str = "NEWS_DATA_PROVIDER is not configured"
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.news"))

    def get_news_for_instrument(self, instrument: TradableInstrument) -> NewsFetchResult:
        self.logger.info(
            "News unavailable for %s %s: %s",
            instrument.asset_class.value,
            instrument.symbol,
            self.reason,
        )
        return NewsFetchResult(
            status=DataStatus.UNAVAILABLE,
            provider=self.provider_name,
            reason=self.reason,
        )

    def discover_instruments(self) -> list[TradableInstrument]:
        self.logger.info("News catalyst discovery unavailable: %s", self.reason)
        return []


@dataclass
class AlphaVantageNewsProvider(ResearchNewsProvider):
    api_key: str
    topics: list[str]
    lookback_minutes: int
    max_articles: int
    max_symbols: int
    per_symbol_limit: int
    min_relevance_score: float
    allowed_asset_classes: list[AssetClass]
    known_etf_symbols: set[str] = field(default_factory=set)
    timeout_seconds: int = 10
    base_url: str = "https://www.alphavantage.co/query"
    provider_name: str = "alpha_vantage"
    http_get: Callable[[str, int], dict[str, Any]] | None = field(default=None, repr=False)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("trading_bot.research.news.alpha_vantage"))

    def get_news_for_instrument(self, instrument: TradableInstrument) -> NewsFetchResult:
        provider_ticker = self._provider_ticker(instrument)
        if provider_ticker is None:
            return NewsFetchResult(
                status=DataStatus.UNAVAILABLE,
                provider=self.provider_name,
                reason=f"News provider does not support asset class {instrument.asset_class.value!r}",
            )
        return self._fetch(tickers=provider_ticker, topics=None, limit=self.per_symbol_limit, focus_symbol=instrument.symbol)

    def discover_instruments(self) -> list[TradableInstrument]:
        result = self._fetch(tickers=None, topics=self.topics, limit=self.max_articles, focus_symbol=None)
        if result.status != DataStatus.AVAILABLE:
            self.logger.info("News catalyst discovery returned no usable provider result: %s", result.reason)
            return []

        symbol_rows: dict[tuple[str, AssetClass], list[dict[str, Any]]] = defaultdict(list)
        for catalyst in result.catalysts:
            for mention in catalyst.get("ticker_sentiment", []):
                parsed = self._parse_provider_symbol(str(mention.get("ticker", "")))
                if parsed is None:
                    continue
                symbol, asset_class = parsed
                if asset_class not in self.allowed_asset_classes:
                    continue
                relevance = _to_float(mention.get("relevance_score"))
                if relevance is None or relevance < self.min_relevance_score:
                    continue
                symbol_rows[(symbol, asset_class)].append(
                    {
                        "relevance_score": relevance,
                        "sentiment_score": _to_float(mention.get("ticker_sentiment_score")),
                        "sentiment_label": mention.get("ticker_sentiment_label"),
                        "article_title": catalyst.get("title"),
                        "published_at": catalyst.get("published_at"),
                        "source": catalyst.get("source"),
                    }
                )

        ranked = sorted(
            symbol_rows.items(),
            key=lambda item: _news_rank_score(item[1]),
            reverse=True,
        )[: self.max_symbols]

        instruments: list[TradableInstrument] = []
        for (symbol, asset_class), rows in ranked:
            top_row = max(rows, key=lambda row: float(row.get("relevance_score") or 0.0))
            instruments.append(
                TradableInstrument(
                    symbol=symbol,
                    asset_class=asset_class,
                    exchange="SMART",
                    currency="USD",
                    contract_details={
                        "discovery_source": "news_catalyst",
                        "requires_news_context": True,
                        "news_article_count": len(rows),
                        "news_relevance_score": top_row.get("relevance_score"),
                        "news_sentiment_score": top_row.get("sentiment_score"),
                        "news_sentiment_label": top_row.get("sentiment_label"),
                    },
                    is_tradeable=True,
                    data_provider=self.provider_name,
                    broker_provider="IBKR",
                )
            )
        return instruments

    def _fetch(
        self,
        *,
        tickers: str | None,
        topics: list[str] | None,
        limit: int,
        focus_symbol: str | None,
    ) -> NewsFetchResult:
        if not self.api_key:
            return NewsFetchResult(
                status=DataStatus.UNAVAILABLE,
                provider=self.provider_name,
                reason="ALPHA_VANTAGE_API_KEY is not configured",
            )

        params: dict[str, str] = {
            "function": "NEWS_SENTIMENT",
            "apikey": self.api_key,
            "sort": "LATEST",
            "limit": str(max(1, limit)),
            "time_from": (datetime.utcnow() - timedelta(minutes=self.lookback_minutes)).strftime("%Y%m%dT%H%M"),
        }
        if tickers:
            params["tickers"] = tickers
        elif topics:
            params["topics"] = ",".join(topics)

        url = f"{self.base_url}?{urlencode(params)}"
        try:
            payload = self._http_get(url, self.timeout_seconds)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return NewsFetchResult(
                status=DataStatus.UNAVAILABLE,
                provider=self.provider_name,
                reason=f"Alpha Vantage news request failed: {exc}",
            )

        provider_error = _provider_error(payload)
        if provider_error:
            return NewsFetchResult(
                status=DataStatus.UNAVAILABLE,
                provider=self.provider_name,
                reason=provider_error,
            )

        feed = payload.get("feed")
        if not isinstance(feed, list):
            return NewsFetchResult(
                status=DataStatus.UNAVAILABLE,
                provider=self.provider_name,
                reason="Alpha Vantage response did not include a news feed",
            )

        return NewsFetchResult(
            status=DataStatus.AVAILABLE,
            provider=self.provider_name,
            as_of=datetime.utcnow(),
            catalysts=[_parse_article(article, focus_symbol) for article in feed if isinstance(article, dict)],
        )

    def _http_get(self, url: str, timeout_seconds: int) -> dict[str, Any]:
        if self.http_get is not None:
            return self.http_get(url, timeout_seconds)
        with urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310
            body = response.read().decode("utf-8")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("Expected object response", body, 0)
        return payload

    def _provider_ticker(self, instrument: TradableInstrument) -> str | None:
        if instrument.asset_class in {AssetClass.STOCK, AssetClass.ETF}:
            return instrument.symbol
        if instrument.asset_class == AssetClass.CRYPTO:
            return f"CRYPTO:{instrument.symbol}"
        return None

    def _parse_provider_symbol(self, raw_symbol: str) -> tuple[str, AssetClass] | None:
        normalized = raw_symbol.strip().upper()
        if not normalized:
            return None
        if normalized.startswith("CRYPTO:"):
            symbol = normalized.split(":", 1)[1]
            return (symbol, AssetClass.CRYPTO) if symbol else None
        if normalized.startswith("FOREX:"):
            return None
        asset_class = AssetClass.ETF if normalized in self.known_etf_symbols else AssetClass.STOCK
        return normalized, asset_class


@dataclass
class NewsCatalystUniverseBuilder(InstrumentUniverseBuilder):
    news_provider: ResearchNewsProvider
    asset_class: AssetClass = AssetClass.STOCK
    name: str = "news_catalyst"

    def build(self) -> list[TradableInstrument]:
        return self.news_provider.discover_instruments()


def _provider_error(payload: dict[str, Any]) -> str | None:
    for key in ["Error Message", "Note", "Information"]:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_article(article: dict[str, Any], focus_symbol: str | None) -> dict[str, Any]:
    ticker_sentiment = article.get("ticker_sentiment")
    mentions = ticker_sentiment if isinstance(ticker_sentiment, list) else []
    return {
        "provider": "alpha_vantage",
        "title": article.get("title"),
        "url": article.get("url"),
        "source": article.get("source"),
        "published_at": _parse_alpha_vantage_time(article.get("time_published")),
        "summary": article.get("summary"),
        "overall_sentiment_score": _to_float(article.get("overall_sentiment_score")),
        "overall_sentiment_label": article.get("overall_sentiment_label"),
        "topics": article.get("topics") if isinstance(article.get("topics"), list) else [],
        "focus_relevance_score": _focus_relevance(mentions, focus_symbol),
        "ticker_sentiment": mentions,
    }


def _parse_alpha_vantage_time(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%S").isoformat()
    except ValueError:
        return value


def _focus_relevance(mentions: list[Any], focus_symbol: str | None) -> float | None:
    if not focus_symbol:
        return None
    normalized = focus_symbol.upper()
    scores: list[float] = []
    for mention in mentions:
        if not isinstance(mention, dict):
            continue
        if str(mention.get("ticker", "")).upper() != normalized:
            continue
        score = _to_float(mention.get("relevance_score"))
        if score is not None:
            scores.append(score)
    return max(scores) if scores else None


def _news_rank_score(rows: list[dict[str, Any]]) -> float:
    score = 0.0
    for row in rows:
        relevance = float(row.get("relevance_score") or 0.0)
        sentiment = abs(float(row.get("sentiment_score") or 0.0))
        score += relevance * (1.0 + sentiment)
    return score


def _to_float(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None
