from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.models import ResearchCitations


class ClaudeResearchResponseSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    asset_class: str = Field(pattern="^(stock|etf|option|future|forex|crypto|bond)$")
    trade_thesis: str
    bull_case: str
    bear_case: str
    key_catalysts: list[str]
    major_risks: list[str]
    confidence_score: int = Field(ge=0, le=100)
    opportunity_score: int = Field(ge=0, le=100)
    suggested_direction: str = Field(pattern="^(long|short|avoid)$")
    suggested_strategy: str
    suggested_entry: float | None = None
    suggested_stop_loss: float | None = None
    suggested_take_profit: float | None = None
    time_horizon: str
    needs_human_review: bool = True
    citations: ResearchCitations | None = None
