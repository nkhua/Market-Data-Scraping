from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TriggerType(str, Enum):
    PRICE_MOVE = "price_move"
    VOLATILITY_EXPANSION = "volatility_expansion"
    EARNINGS_APPROACHING = "earnings_approaching"
    HEADLINE = "headline"
    RESEARCH = "research"


class EvidenceSourceType(str, Enum):
    NEWS = "news"
    EARNINGS = "earnings"
    MOVER = "mover"
    VOLATILITY = "volatility"
    FILING = "filing"
    CATALYST = "catalyst"


class AnalystDecision(str, Enum):
    ALLOW = "allow"
    REJECT = "reject"
    REVIEW = "review"


class ConvictionBucket(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AutonomyAction(str, Enum):
    AUTO_EXECUTE = "auto_execute"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"


class AssetClass(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    OPTION = "option"
    FUTURE = "future"
    FOREX = "forex"
    CRYPTO = "crypto"
    BOND = "bond"


class DataStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    STALE = "stale"


class ResearchDecisionStatus(str, Enum):
    REJECTED = "rejected"
    READY_FOR_CLAUDE = "ready_for_claude"
    ANALYZED = "analyzed"


class AppBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TradableInstrument(AppBaseModel):
    symbol: str
    asset_class: AssetClass
    exchange: str
    currency: str
    contract_details: dict[str, Any] = Field(default_factory=dict)
    is_tradeable: bool = True
    data_provider: str | None = None
    broker_provider: str = "IBKR"


class MarketDataSummary(AppBaseModel):
    status: DataStatus
    provider: str
    as_of: datetime | None = None
    reason: str | None = None
    quote: dict[str, Any] = Field(default_factory=dict)
    historical_ohlcv: list[dict[str, Any]] = Field(default_factory=list)
    regular_session_daily_bars: bool = False
    options_chain: dict[str, Any] = Field(default_factory=dict)
    futures_contract: dict[str, Any] = Field(default_factory=dict)
    forex_rates: dict[str, Any] = Field(default_factory=dict)
    macro_rates: dict[str, Any] = Field(default_factory=dict)
    news_status: DataStatus = DataStatus.UNAVAILABLE
    news_reason: str | None = None
    news_catalysts: list[dict[str, Any]] = Field(default_factory=list)


class NewsFetchResult(AppBaseModel):
    status: DataStatus
    provider: str
    as_of: datetime | None = None
    reason: str | None = None
    catalysts: list[dict[str, Any]] = Field(default_factory=list)


class LiquidityProfile(AppBaseModel):
    acceptable: bool = False
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    metrics: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class EarningsFact(AppBaseModel):
    metric: Literal["revenue", "net_income", "diluted_eps"]
    period: Literal["quarter", "year"]
    period_end: date
    value: Decimal = Field(allow_inf_nan=False)
    unit: str
    filed_on: date | None = None
    source_url: str
    source_field: str


class EarningsResult(AppBaseModel):
    provider: str
    facts: list[EarningsFact] = Field(default_factory=list)
    reason: str | None = None


class SourceCheck(AppBaseModel):
    id: str
    status: Literal["matched", "conflict", "unverified"]
    primary: EarningsFact
    comparison: EarningsFact | None = None
    tolerance: Decimal | None = None
    reason: str


class ResearchSource(AppBaseModel):
    id: str
    kind: Literal["market_data", "news", "filing", "source_check"]
    provider: str
    label: str
    url: str | None = None


class CloseCheck(AppBaseModel):
    id: Literal["check-daily-close"] = "check-daily-close"
    status: Literal["matched", "conflict", "unverified"]
    session: date | None = None
    ibkr_close_usd: Decimal | None = None
    alpha_vantage_close_usd: Decimal | None = None
    tolerance_usd: Decimal | None = None
    reason: str


class ResearchEvidence(AppBaseModel):
    filings: EarningsResult
    comparison: EarningsResult
    checks: list[SourceCheck]
    sources: list[ResearchSource]
    close_check: CloseCheck | None = None


class ResearchCitations(AppBaseModel):
    trade_thesis: list[str] = Field(min_length=1)
    bull_case: list[str] = Field(min_length=1)
    bear_case: list[str] = Field(min_length=1)
    key_catalysts: list[list[str]]
    major_risks: list[list[str]]


class ResearchCandidate(AppBaseModel):
    instrument: TradableInstrument
    asset_class: AssetClass
    market_data_summary: MarketDataSummary
    technical_signals: dict[str, Any] = Field(default_factory=dict)
    news_context: dict[str, Any] = Field(default_factory=dict)
    macro_context: dict[str, Any] = Field(default_factory=dict)
    liquidity: LiquidityProfile = Field(default_factory=LiquidityProfile)
    known_risks: dict[str, Any] = Field(default_factory=dict)
    portfolio_context: dict[str, Any] = Field(default_factory=dict)
    evidence: ResearchEvidence | None = None


class ClaudeResearchInput(AppBaseModel):
    instrument: dict[str, Any]
    asset_class: AssetClass
    market_data_summary: dict[str, Any]
    technical_signals: dict[str, Any]
    news_context: dict[str, Any]
    macro_context: dict[str, Any]
    liquidity: dict[str, Any]
    known_risks: dict[str, Any]
    portfolio_context: dict[str, Any]
    evidence: ResearchEvidence | None = None


class ClaudeResearchOutput(AppBaseModel):
    symbol: str
    asset_class: AssetClass
    trade_thesis: str
    bull_case: str
    bear_case: str
    key_catalysts: list[str] = Field(default_factory=list)
    major_risks: list[str] = Field(default_factory=list)
    confidence_score: int = Field(ge=0, le=100)
    opportunity_score: int = Field(ge=0, le=100)
    suggested_direction: Literal["long", "short", "avoid"]
    suggested_strategy: str
    suggested_entry: float | None = None
    suggested_stop_loss: float | None = None
    suggested_take_profit: float | None = None
    time_horizon: str
    needs_human_review: bool = True
    citations: ResearchCitations | None = None


class ResearchDecision(AppBaseModel):
    status: ResearchDecisionStatus
    instrument: TradableInstrument
    candidate: ResearchCandidate | None = None
    reasons: list[str] = Field(default_factory=list)
    claude_analysis: ClaudeResearchOutput | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PriceSnapshot(AppBaseModel):
    symbol: str
    last: float
    close: float
    high: float
    low: float
    volume: int
    average_volume: int
    bid: float | None = None
    ask: float | None = None
    atr: float | None = None
    ma_fast: float | None = None
    ma_slow: float | None = None
    sector: str | None = None
    as_of: datetime = Field(default_factory=datetime.utcnow)


class HeadlineItem(AppBaseModel):
    symbol: str
    headline: str
    source: str
    published_at: datetime
    relevance_score: float = 0.5


class ResearchItem(AppBaseModel):
    symbol: str
    summary: str
    source: str
    published_at: datetime
    relevance_score: float = 0.5


class DiscoveryEvidence(AppBaseModel):
    symbol: str
    source_type: EvidenceSourceType
    provider_name: str
    trigger_reason: str
    summary: str
    observed_at: datetime
    relevance_score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryContext(AppBaseModel):
    mode: Literal["broad", "watchlist_anchored"] = "broad"
    base_universe_symbols: list[str] = Field(default_factory=list)
    headline_min_relevance_score: float = 0.7
    unusual_move_pct: float = 0.03
    volatility_trigger_threshold: float = 1.2
    earnings_window_days: int = 7
    include_filings: bool = False
    include_catalyst_pages: bool = False


class EarningsEvent(AppBaseModel):
    symbol: str
    earnings_date: date
    timing: Literal["pre_market", "post_market", "unknown"] = "unknown"


class MonitorTrigger(AppBaseModel):
    symbol: str
    trigger_type: TriggerType
    reason: str
    strength: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CandidateSignal(AppBaseModel):
    symbol: str
    price_snapshot: PriceSnapshot | None = None
    triggers: list[MonitorTrigger] = Field(default_factory=list)
    earnings_event: EarningsEvent | None = None
    headlines: list[HeadlineItem] = Field(default_factory=list)
    research_items: list[ResearchItem] = Field(default_factory=list)
    evidence: list[DiscoveryEvidence] = Field(default_factory=list)
    volatility_context: dict[str, Any] = Field(default_factory=dict)
    catalyst_notes: list[str] = Field(default_factory=list)
    urgency_score: float = 0.0
    monitor_notes: list[str] = Field(default_factory=list)


class FilterDecision(AppBaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    metrics: dict[str, float | int | str | bool | None] = Field(default_factory=dict)


class PortfolioPosition(AppBaseModel):
    symbol: str
    quantity: int
    average_cost: float
    market_price: float
    sector: str | None = None

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price


class PortfolioSnapshot(AppBaseModel):
    equity: float
    cash: float
    buying_power: float
    positions: list[PortfolioPosition] = Field(default_factory=list)
    open_orders_exposure: float = 0.0
    captured_at: datetime = Field(default_factory=datetime.utcnow)


class AnalystResponse(AppBaseModel):
    decision: AnalystDecision
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    key_risks: list[str]
    risk_tags: list[str] = Field(default_factory=list)
    catalyst_classification: str
    suggested_conviction_bucket: ConvictionBucket


class TradeIntent(AppBaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    entry_price: float
    stop_price: float | None
    take_profit_price: float | None
    setup_source: str
    conviction: ConvictionBucket = ConvictionBucket.LOW
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderApproval(AppBaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    position_size: int = 0
    risk_amount: float = 0.0
    estimated_exposure: float = 0.0


class AccountAutonomyState(AppBaseModel):
    consecutive_losses: int = 0
    daily_drawdown_pct: float = 0.0
    total_drawdown_pct: float = 0.0


class AutonomyDecision(AppBaseModel):
    action: AutonomyAction
    reasons: list[str] = Field(default_factory=list)
    base_action: AutonomyAction
    downgrade_steps_applied: int = 0
    risk_approval: OrderApproval


class ReviewQueueItem(AppBaseModel):
    symbol: str
    action: AutonomyAction = AutonomyAction.APPROVAL_REQUIRED
    reasons: list[str] = Field(default_factory=list)
    trade_intent: dict[str, Any]
    risk_approval: dict[str, Any]
    analyst_review: dict[str, Any] | None = None
    account_state: dict[str, Any]
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OrderRequest(AppBaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["MKT", "LMT"] = "LMT"
    limit_price: float | None = None
    tif: Literal["DAY", "GTC"] = "DAY"
    paper: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderResult(AppBaseModel):
    accepted: bool
    broker_order_id: str | None = None
    status: str
    message: str
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
