from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from urllib.parse import urlsplit

from app.models import EarningsFact, EarningsResult, ResearchCandidate, ResearchEvidence, ResearchSource, SourceCheck
from app.research.price_check import ALPHA_DAILY_DOCS, AlphaVantageCloseCheck


class EarningsProvider(Protocol):
    def fetch(self, symbol: str) -> EarningsResult: ...


def _check(primary: EarningsFact, comparison: EarningsResult) -> SourceCheck:
    check_id = f"check-{primary.period}-{primary.metric}"
    peers = [
        fact for fact in comparison.facts
        if (fact.metric, fact.period, fact.period_end, fact.unit)
        == (primary.metric, primary.period, primary.period_end, primary.unit)
    ]
    if primary.metric == "diluted_eps" or not peers or len({fact.value for fact in peers}) > 1:
        if primary.metric == "diluted_eps":
            reason = "Comparison feed does not supply directly comparable GAAP diluted EPS"
        elif peers:
            reason = "Comparison source returned conflicting values for this metric and fiscal period"
        else:
            reason = comparison.reason or "No matching metric, fiscal period end, and currency in comparison feed"
        return SourceCheck(id=check_id, status="unverified", primary=primary, reason=reason)

    peer = peers[0]
    # Allow minor rounding between normalized feeds without concealing larger differences.
    tolerance = max(Decimal("1"), abs(primary.value) * Decimal("0.0001"))
    matched = abs(primary.value - peer.value) <= tolerance
    return SourceCheck(
        id=check_id, status="matched" if matched else "conflict", primary=primary, comparison=peer,
        tolerance=tolerance, reason="Values agree within tolerance" if matched else "Values differ beyond tolerance",
    )


def _source_url(value: object) -> str | None:
    if isinstance(value, str):
        try:
            url = urlsplit(value)
            if url.scheme in {"http", "https"} and url.hostname and url.username is None:
                return value
        except ValueError:
            pass
    return None


@dataclass
class EquityEvidenceService:
    filings: EarningsProvider
    comparison: EarningsProvider
    price_comparison: AlphaVantageCloseCheck | None = None

    def collect(self, candidate: ResearchCandidate) -> ResearchEvidence:
        symbol = candidate.instrument.symbol
        primary = self.filings.fetch(symbol)
        comparison = self.comparison.fetch(symbol) if any(
            fact.metric != "diluted_eps" for fact in primary.facts
        ) else EarningsResult(provider="alpha_vantage", reason="No comparable SEC filing metrics to cross-check")

        checks = [_check(fact, comparison) for fact in primary.facts]
        sources = [ResearchSource(
            id="market-data", kind="market_data", provider=candidate.market_data_summary.provider,
            label="Quotes, historical bars, and derived technical signals for this candidate",
        )]
        seen_urls = set()
        for index, article in enumerate(candidate.market_data_summary.news_catalysts, start=1):
            url = _source_url(article.get("url"))
            title = article.get("title")
            if not url or url in seen_urls or not isinstance(title, str) or not title.strip():
                continue
            seen_urls.add(url)
            sources.append(ResearchSource(
                id=f"news-{index}", kind="news", provider=str(article.get("source") or article.get("provider") or "news"),
                label=title, url=url,
            ))
        for check in checks:
            fact = check.primary
            sources.extend([
                ResearchSource(
                    id=f"filing-{fact.period}-{fact.metric}", kind="filing", provider=primary.provider,
                    label=f"{fact.metric}, fiscal {fact.period} ended {fact.period_end}", url=fact.source_url,
                ),
                ResearchSource(
                    id=check.id, kind="source_check", provider=f"{primary.provider} / {comparison.provider}",
                    label=f"{fact.metric}, fiscal {fact.period} ended {fact.period_end}: {check.status}",
                ),
            ])
        # Retain same-period comparison facts, including duplicates that prevented verification.
        periods = {(fact.period, fact.period_end) for fact in primary.facts}
        comparison = comparison.model_copy(update={
            "facts": [fact for fact in comparison.facts if (fact.period, fact.period_end) in periods],
        })
        if not comparison.facts and comparison.reason is None:
            comparison.reason = "No comparison income statement for the selected SEC fiscal periods"
        close_check = self.price_comparison.compare(candidate) if self.price_comparison is not None else None
        if close_check is not None:
            sources.append(ResearchSource(
                id=close_check.id, kind="source_check", provider="ibkr / alpha_vantage",
                label=f"Daily close comparison ({close_check.status})", url=ALPHA_DAILY_DOCS,
            ))
        return ResearchEvidence(filings=primary, comparison=comparison, checks=checks, sources=sources, close_check=close_check)
