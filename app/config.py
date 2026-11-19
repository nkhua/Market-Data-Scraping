from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SETTINGS_PATH = ROOT_DIR / "config" / "settings.yaml"
DEFAULT_ENV_PATH = ROOT_DIR / ".env"


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_name: str = "trading_bot"
    trading_mode: Literal["research_only", "paper", "semi_auto", "auto"] = "research_only"
    enable_live_trading: bool = False
    environment: Literal["paper", "live"] = "paper"
    paper_trading: bool = True
    dry_run: bool = True
    timezone: str = "America/Toronto"
    state_db_path: str = "data/trading_bot.sqlite3"
    log_level: str = "INFO"
    journal_retention_days: int = 180

    @model_validator(mode="after")
    def validate_paper_defaults(self) -> "AppSettings":
        if self.environment != "live":
            return self
        if self.paper_trading:
            raise ValueError("app.paper_trading must be false when app.environment is live.")
        return self


class DiscoverySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frequency_seconds: int = 300
    mode: Literal["broad", "watchlist_anchored"] = "broad"
    base_universe_symbols: list[str] = Field(default_factory=list)
    enabled_sources: list[str] = Field(
        default_factory=list
    )
    max_discovered_candidates_per_cycle: int = 100
    max_candidates_for_claude: int = 10
    source_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "news": 1.0,
            "earnings": 0.8,
            "mover": 1.1,
            "volatility": 1.0,
            "filing": 0.7,
            "catalyst": 0.7,
        }
    )
    headline_min_relevance_score: float = 0.7
    unusual_move_pct: float = 0.03
    volatility_trigger_threshold: float = 1.4
    earnings_window_days: int = 7
    include_filings: bool = False
    include_catalyst_pages: bool = False

    @field_validator("frequency_seconds")
    @classmethod
    def validate_frequency(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("discovery.frequency_seconds must be greater than 0.")
        return value

    @field_validator("max_discovered_candidates_per_cycle")
    @classmethod
    def validate_max_discovered_candidates_per_cycle(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("discovery.max_discovered_candidates_per_cycle must be greater than 0.")
        return value

    @field_validator("max_candidates_for_claude")
    @classmethod
    def validate_max_candidates_for_claude(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("discovery.max_candidates_for_claude must be greater than 0.")
        return value

    @field_validator("headline_min_relevance_score")
    @classmethod
    def validate_headline_min_relevance_score(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("discovery.headline_min_relevance_score must be between 0 and 1.")
        return value

    @field_validator("source_weights")
    @classmethod
    def validate_source_weights(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("discovery.source_weights must not be empty.")
        for key, item in value.items():
            if item < 0:
                raise ValueError(f"discovery.source_weights[{key!r}] must be 0 or greater.")
        return value

    @model_validator(mode="after")
    def validate_thresholds(self) -> "DiscoverySettings":
        bounded_fields = {
            "headline_min_relevance_score": self.headline_min_relevance_score,
            "unusual_move_pct": self.unusual_move_pct,
        }
        for field_name, value in bounded_fields.items():
            if value < 0 or value > 1:
                raise ValueError(f"discovery.{field_name} must be between 0 and 1.")
        if self.volatility_trigger_threshold <= 0:
            raise ValueError("discovery.volatility_trigger_threshold must be greater than 0.")
        if self.earnings_window_days < 0:
            raise ValueError("discovery.earnings_window_days must be 0 or greater.")
        return self


class FilterSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_price: float = 5.0
    max_spread_pct: float = 0.005
    min_average_volume: int = 1_000_000
    earnings_blackout_days: int = 2
    trend_fast_ma_period: int = 20
    trend_slow_ma_period: int = 50
    require_price_above_fast_ma: bool = True

    @model_validator(mode="after")
    def validate_periods(self) -> "FilterSettings":
        if self.trend_fast_ma_period <= 0 or self.trend_slow_ma_period <= 0:
            raise ValueError("Moving average periods must be positive integers.")
        if self.trend_fast_ma_period >= self.trend_slow_ma_period:
            raise ValueError("filters.trend_fast_ma_period must be smaller than filters.trend_slow_ma_period.")
        return self


class RiskSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_risk_per_trade_pct: float = 0.005
    max_position_exposure_pct: float = 0.15
    max_portfolio_exposure_pct: float = 0.50
    max_open_positions: int = 6
    max_daily_new_exposure_pct: float = 0.20
    max_sector_exposure_pct: float = 0.25
    max_margin_usage_pct: float = 0.50
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06
    min_reward_to_risk: float = 1.5
    allowed_symbols: list[str] = Field(default_factory=list)
    position_sizing_method: Literal["fixed_fractional", "equal_weight"] = "fixed_fractional"
    require_hard_stop: bool = True

    @model_validator(mode="after")
    def validate_risk_values(self) -> "RiskSettings":
        bounded_fields = {
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
            "max_position_exposure_pct": self.max_position_exposure_pct,
            "max_portfolio_exposure_pct": self.max_portfolio_exposure_pct,
            "max_daily_new_exposure_pct": self.max_daily_new_exposure_pct,
            "max_sector_exposure_pct": self.max_sector_exposure_pct,
            "max_margin_usage_pct": self.max_margin_usage_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }
        for field_name, value in bounded_fields.items():
            if value <= 0 or value > 1:
                raise ValueError(f"risk.{field_name} must be between 0 and 1.")
        if self.max_open_positions <= 0:
            raise ValueError("risk.max_open_positions must be greater than 0.")
        if self.min_reward_to_risk <= 0:
            raise ValueError("risk.min_reward_to_risk must be greater than 0.")
        return self


class UniverseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_symbols: list[str] = Field(default_factory=list)
    etf_symbols: list[str] = Field(default_factory=list)
    option_contracts: list[dict[str, Any]] = Field(default_factory=list)
    future_contracts: list[dict[str, Any]] = Field(default_factory=list)
    forex_pairs: list[str] = Field(default_factory=list)
    crypto_symbols: list[str] = Field(default_factory=list)
    bond_contracts: list[dict[str, Any]] = Field(default_factory=list)


class ResearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_asset_classes: list[Literal["stock", "etf", "option", "future", "forex", "crypto", "bond"]] = Field(
        default_factory=lambda: ["stock", "etf"]
    )
    market_data_provider: str = ""
    news_data_provider: str = ""
    all_stocks_universe_enabled: bool = True
    all_stocks_include_etfs: bool = False
    all_stocks_max_symbols: int = 0
    all_stocks_request_timeout_seconds: int = 10
    alpha_vantage_api_key: str = ""
    sec_edgar_user_agent: str = ""
    news_focus_enabled: bool = False
    news_focus_topics: list[str] = Field(
        default_factory=lambda: [
            "financial_markets",
            "earnings",
            "mergers_and_acquisitions",
            "ipo",
            "economy_macro",
            "economy_monetary",
        ]
    )
    news_focus_lookback_minutes: int = 1_440
    news_focus_max_articles: int = 50
    news_focus_max_symbols: int = 25
    news_per_symbol_limit: int = 5
    news_min_relevance_score: float = 0.15
    news_request_timeout_seconds: int = 10
    ibkr_stock_scanner_enabled: bool = False
    ibkr_stock_scanner_codes: list[str] = Field(default_factory=lambda: ["HOT_BY_VOLUME", "TOP_PERC_GAIN"])
    ibkr_stock_scanner_location_code: str = "STK.US.MAJOR"
    ibkr_stock_scanner_max_results: int = 25
    historical_duration: str = "3 M"
    historical_bar_size: str = "1 day"
    max_candidates_for_claude: int = 10
    max_data_age_seconds: int = 900
    min_liquidity_threshold: float = 0.5
    allow_options: bool = False
    allow_futures: bool = False
    allow_forex: bool = False
    allow_crypto: bool = False
    allow_shorting: bool = False
    allow_naked_options: bool = False

    @model_validator(mode="after")
    def validate_research_values(self) -> "ResearchSettings":
        if self.max_candidates_for_claude <= 0:
            raise ValueError("research.max_candidates_for_claude must be greater than 0.")
        if self.all_stocks_max_symbols < 0:
            raise ValueError("research.all_stocks_max_symbols must be 0 or greater.")
        if self.all_stocks_request_timeout_seconds <= 0:
            raise ValueError("research.all_stocks_request_timeout_seconds must be greater than 0.")
        if self.news_focus_lookback_minutes <= 0:
            raise ValueError("research.news_focus_lookback_minutes must be greater than 0.")
        if self.news_focus_max_articles <= 0:
            raise ValueError("research.news_focus_max_articles must be greater than 0.")
        if self.news_focus_max_symbols <= 0:
            raise ValueError("research.news_focus_max_symbols must be greater than 0.")
        if self.news_per_symbol_limit <= 0:
            raise ValueError("research.news_per_symbol_limit must be greater than 0.")
        if self.news_request_timeout_seconds <= 0:
            raise ValueError("research.news_request_timeout_seconds must be greater than 0.")
        if not 0 <= self.news_min_relevance_score <= 1:
            raise ValueError("research.news_min_relevance_score must be between 0 and 1.")
        if self.ibkr_stock_scanner_max_results <= 0:
            raise ValueError("research.ibkr_stock_scanner_max_results must be greater than 0.")
        if self.max_data_age_seconds <= 0:
            raise ValueError("research.max_data_age_seconds must be greater than 0.")
        if not 0 <= self.min_liquidity_threshold <= 1:
            raise ValueError("research.min_liquidity_threshold must be between 0 and 1.")
        allowed = set(self.allowed_asset_classes)
        if "option" in allowed and not self.allow_options:
            raise ValueError("research.allow_options must be true before option can be allowed.")
        if "future" in allowed and not self.allow_futures:
            raise ValueError("research.allow_futures must be true before future can be allowed.")
        if "forex" in allowed and not self.allow_forex:
            raise ValueError("research.allow_forex must be true before forex can be allowed.")
        if "crypto" in allowed and not self.allow_crypto:
            raise ValueError("research.allow_crypto must be true before crypto can be allowed.")
        return self


class ClaudeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    model: str = "claude-sonnet-4-6"
    timeout_seconds: int = 20
    min_confidence_for_allow: float = 0.60
    max_tokens: int = 1_600

    @model_validator(mode="after")
    def validate_claude_values(self) -> "ClaudeSettings":
        if self.timeout_seconds <= 0:
            raise ValueError("claude.timeout_seconds must be greater than 0.")
        if self.max_tokens <= 0:
            raise ValueError("claude.max_tokens must be greater than 0.")
        if not 0 <= self.min_confidence_for_allow <= 1:
            raise ValueError("claude.min_confidence_for_allow must be between 0 and 1.")
        return self


class BrokerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 101
    account_id: str = ""

    @model_validator(mode="after")
    def validate_broker_values(self) -> "BrokerSettings":
        if self.port <= 0:
            raise ValueError("broker.port must be greater than 0.")
        if self.client_id < 0:
            raise ValueError("broker.client_id must be 0 or greater.")
        return self


class AutonomySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_execute_enabled: bool = True
    require_analyst_for_auto_execute: bool = True
    require_analyst_for_approval: bool = False
    auto_execute_min_confidence: float = 0.85
    approval_required_min_confidence: float = 0.55
    auto_execute_allowed_catalysts: list[str] = Field(default_factory=list)
    approval_required_allowed_catalysts: list[str] = Field(default_factory=list)
    auto_execute_allowed_conviction_buckets: list[Literal["low", "medium", "high"]] = Field(default_factory=list)
    approval_required_allowed_conviction_buckets: list[Literal["low", "medium", "high"]] = Field(default_factory=list)
    blocked_risk_tags: list[str] = Field(default_factory=list)
    approval_required_risk_tags: list[str] = Field(default_factory=list)
    downgrade_after_losing_streak: int = 3
    downgrade_daily_drawdown_pct: float = 0.02
    shutdown_total_drawdown_pct: float = 0.10

    @model_validator(mode="after")
    def validate_autonomy_values(self) -> "AutonomySettings":
        for field_name in [
            "auto_execute_min_confidence",
            "approval_required_min_confidence",
            "downgrade_daily_drawdown_pct",
            "shutdown_total_drawdown_pct",
        ]:
            value = getattr(self, field_name)
            if value < 0 or value > 1:
                raise ValueError(f"autonomy.{field_name} must be between 0 and 1.")
        if self.approval_required_min_confidence > self.auto_execute_min_confidence:
            raise ValueError(
                "autonomy.approval_required_min_confidence cannot be greater than autonomy.auto_execute_min_confidence."
            )
        if self.downgrade_after_losing_streak < 0:
            raise ValueError("autonomy.downgrade_after_losing_streak must be 0 or greater.")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app: AppSettings
    universe: UniverseSettings = Field(default_factory=UniverseSettings)
    research: ResearchSettings = Field(default_factory=ResearchSettings)
    discovery: DiscoverySettings
    filters: FilterSettings
    risk: RiskSettings
    claude: ClaudeSettings
    broker: BrokerSettings
    autonomy: AutonomySettings


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise RuntimeError(f"Environment variable {name} must be a boolean value like true/false.")


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in {None, ""} else default


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    app = raw.setdefault("app", {})
    broker = raw.setdefault("broker", {})
    research = raw.setdefault("research", {})
    risk = raw.setdefault("risk", {})

    app["trading_mode"] = os.getenv("TRADING_MODE", app.get("trading_mode", "research_only")).strip().lower()
    app["enable_live_trading"] = _env_bool("ENABLE_LIVE_TRADING", app.get("enable_live_trading", False))
    app["environment"] = os.getenv("ENV", app.get("environment", "paper")).strip().lower()
    app["paper_trading"] = _env_bool("PAPER_TRADING", app.get("paper_trading", True))
    app["dry_run"] = _env_bool("DRY_RUN", app.get("dry_run", True))

    broker["host"] = os.getenv("IBKR_HOST", broker.get("host", "127.0.0.1"))
    broker["port"] = int(os.getenv("IBKR_PORT", broker.get("port", 7497)))
    broker["client_id"] = int(os.getenv("IBKR_CLIENT_ID", broker.get("client_id", 101)))
    broker["account_id"] = os.getenv("IBKR_ACCOUNT_ID", broker.get("account_id", ""))

    research["allowed_asset_classes"] = [
        item.lower()
        for item in _env_list(
            "ALLOWED_ASSET_CLASSES",
            research.get("allowed_asset_classes", ["stock", "etf"]),
        )
    ]
    research["market_data_provider"] = os.getenv("MARKET_DATA_PROVIDER", research.get("market_data_provider", ""))
    research["news_data_provider"] = os.getenv("NEWS_DATA_PROVIDER", research.get("news_data_provider", ""))
    research["all_stocks_universe_enabled"] = _env_bool(
        "ALL_STOCKS_UNIVERSE_ENABLED",
        research.get("all_stocks_universe_enabled", True),
    )
    research["all_stocks_include_etfs"] = _env_bool(
        "ALL_STOCKS_INCLUDE_ETFS",
        research.get("all_stocks_include_etfs", False),
    )
    research["all_stocks_max_symbols"] = int(
        os.getenv("ALL_STOCKS_MAX_SYMBOLS", research.get("all_stocks_max_symbols", 0))
    )
    research["all_stocks_request_timeout_seconds"] = int(
        os.getenv(
            "ALL_STOCKS_REQUEST_TIMEOUT_SECONDS",
            research.get("all_stocks_request_timeout_seconds", 10),
        )
    )
    research["alpha_vantage_api_key"] = os.getenv(
        "ALPHA_VANTAGE_API_KEY",
        research.get("alpha_vantage_api_key", ""),
    )
    research["sec_edgar_user_agent"] = os.getenv("SEC_EDGAR_USER_AGENT", research.get("sec_edgar_user_agent", ""))
    research["news_focus_enabled"] = _env_bool(
        "NEWS_FOCUS_ENABLED",
        research.get("news_focus_enabled", False),
    )
    research["news_focus_topics"] = _env_list(
        "NEWS_FOCUS_TOPICS",
        research.get(
            "news_focus_topics",
            ["financial_markets", "earnings", "mergers_and_acquisitions", "ipo"],
        ),
    )
    research["news_focus_lookback_minutes"] = int(
        os.getenv(
            "NEWS_FOCUS_LOOKBACK_MINUTES",
            research.get("news_focus_lookback_minutes", 1_440),
        )
    )
    research["news_focus_max_articles"] = int(
        os.getenv("NEWS_FOCUS_MAX_ARTICLES", research.get("news_focus_max_articles", 50))
    )
    research["news_focus_max_symbols"] = int(
        os.getenv("NEWS_FOCUS_MAX_SYMBOLS", research.get("news_focus_max_symbols", 25))
    )
    research["news_per_symbol_limit"] = int(
        os.getenv("NEWS_PER_SYMBOL_LIMIT", research.get("news_per_symbol_limit", 5))
    )
    research["news_min_relevance_score"] = _env_float(
        "NEWS_MIN_RELEVANCE_SCORE",
        research.get("news_min_relevance_score", 0.15),
    )
    research["news_request_timeout_seconds"] = int(
        os.getenv("NEWS_REQUEST_TIMEOUT_SECONDS", research.get("news_request_timeout_seconds", 10))
    )
    research["ibkr_stock_scanner_enabled"] = _env_bool(
        "IBKR_STOCK_SCANNER_ENABLED",
        research.get("ibkr_stock_scanner_enabled", False),
    )
    research["ibkr_stock_scanner_codes"] = _env_list(
        "IBKR_STOCK_SCANNER_CODES",
        research.get("ibkr_stock_scanner_codes", ["HOT_BY_VOLUME", "TOP_PERC_GAIN"]),
    )
    research["ibkr_stock_scanner_location_code"] = os.getenv(
        "IBKR_STOCK_SCANNER_LOCATION_CODE",
        research.get("ibkr_stock_scanner_location_code", "STK.US.MAJOR"),
    )
    research["ibkr_stock_scanner_max_results"] = int(
        os.getenv(
            "IBKR_STOCK_SCANNER_MAX_RESULTS",
            research.get("ibkr_stock_scanner_max_results", 25),
        )
    )
    research["historical_duration"] = os.getenv(
        "HISTORICAL_DURATION",
        research.get("historical_duration", "3 M"),
    )
    research["historical_bar_size"] = os.getenv(
        "HISTORICAL_BAR_SIZE",
        research.get("historical_bar_size", "1 day"),
    )
    research["min_liquidity_threshold"] = _env_float(
        "MIN_LIQUIDITY_THRESHOLD",
        research.get("min_liquidity_threshold", 0.5),
    )
    research["allow_options"] = _env_bool("ALLOW_OPTIONS", research.get("allow_options", False))
    research["allow_futures"] = _env_bool("ALLOW_FUTURES", research.get("allow_futures", False))
    research["allow_forex"] = _env_bool("ALLOW_FOREX", research.get("allow_forex", False))
    research["allow_crypto"] = _env_bool("ALLOW_CRYPTO", research.get("allow_crypto", False))
    research["allow_shorting"] = _env_bool("ALLOW_SHORTING", research.get("allow_shorting", False))
    research["allow_naked_options"] = _env_bool(
        "ALLOW_NAKED_OPTIONS",
        research.get("allow_naked_options", False),
    )

    risk["max_risk_per_trade_pct"] = _env_float(
        "MAX_RISK_PER_TRADE_PERCENT",
        risk.get("max_risk_per_trade_pct", 0.005),
    )
    risk["max_portfolio_exposure_pct"] = _env_float(
        "MAX_PORTFOLIO_EXPOSURE_PERCENT",
        risk.get("max_portfolio_exposure_pct", 0.50),
    )
    risk["max_margin_usage_pct"] = _env_float(
        "MAX_MARGIN_USAGE_PERCENT",
        risk.get("max_margin_usage_pct", 0.50),
    )
    return raw


def _validate_runtime_guardrails(settings: Settings) -> None:
    trading_mode = os.getenv("TRADING_MODE", settings.app.trading_mode).strip().lower()
    enable_live_trading = _env_bool("ENABLE_LIVE_TRADING", settings.app.enable_live_trading)
    env_name = os.getenv("ENV", settings.app.environment).strip().lower()
    paper_trading = _env_bool("PAPER_TRADING", settings.app.paper_trading)
    live_trading_ack = _env_bool("LIVE_TRADING_ACK", False)

    if trading_mode != settings.app.trading_mode:
        raise RuntimeError(
            f"Startup blocked: TRADING_MODE={trading_mode!r} does not match "
            f"app.trading_mode={settings.app.trading_mode!r}."
        )

    if trading_mode == "auto" and not enable_live_trading:
        raise RuntimeError("Auto trading is blocked unless ENABLE_LIVE_TRADING=true.")

    if env_name != settings.app.environment:
        raise RuntimeError(
            f"Startup blocked: ENV={env_name!r} does not match app.environment={settings.app.environment!r}."
        )

    if paper_trading != settings.app.paper_trading:
        raise RuntimeError(
            "Startup blocked: PAPER_TRADING does not match app.paper_trading. "
            "Keep config and environment aligned before running."
        )

    wants_live = settings.app.environment == "live" or not settings.app.paper_trading
    if wants_live:
        missing: list[str] = []
        if env_name != "live":
            missing.append("ENV=live")
        if paper_trading:
            missing.append("PAPER_TRADING=false")
        if not live_trading_ack:
            missing.append("LIVE_TRADING_ACK=true")
        if missing:
            raise RuntimeError(
                "Live trading startup blocked. To run live you must set: " + ", ".join(missing) + "."
            )


def _resolve_path(explicit_path: str | None) -> Path:
    return Path(explicit_path).expanduser().resolve() if explicit_path else DEFAULT_SETTINGS_PATH


@lru_cache(maxsize=1)
def load_settings(settings_path: str | None = None) -> Settings:
    load_dotenv(DEFAULT_ENV_PATH, override=False)
    path = _resolve_path(settings_path or os.getenv("TRADING_BOT_SETTINGS"))
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise RuntimeError(f"Settings file not found: {path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not read settings file at {path}: {exc}") from exc
    raw = _apply_env_overrides(raw)
    try:
        settings = Settings.model_validate(raw)
    except ValidationError as exc:
        error_lines = [
            f"- {'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        raise RuntimeError(
            f"Invalid settings in {path}:\n" + "\n".join(error_lines)
        ) from exc

    _validate_runtime_guardrails(settings)
    return settings
