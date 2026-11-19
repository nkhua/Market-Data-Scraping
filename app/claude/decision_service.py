from __future__ import annotations

import json
import logging
from pathlib import Path

from app.claude.client import ClaudeClient
from app.claude.schemas import ClaudeResearchResponseSchema
from app.models import ClaudeResearchInput, ClaudeResearchOutput, ResearchCandidate, ResearchCitations


PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


class ClaudeDecisionService:
    def __init__(
        self,
        enabled: bool,
        client: ClaudeClient,
        template_path: Path | None = None,
    ) -> None:
        self.enabled = enabled
        self.client = client
        self.template_path = template_path or (PROMPTS_DIR / "claude_multi_asset_research.md")
        self.logger = logging.getLogger("trading_bot.claude.decision")

    def build_input(self, candidate: ResearchCandidate) -> ClaudeResearchInput:
        return ClaudeResearchInput(
            instrument=candidate.instrument.model_dump(mode="json"),
            asset_class=candidate.asset_class,
            market_data_summary=candidate.market_data_summary.model_dump(mode="json"),
            technical_signals=candidate.technical_signals,
            news_context=candidate.news_context,
            macro_context=candidate.macro_context,
            liquidity=candidate.liquidity.model_dump(mode="json"),
            known_risks=candidate.known_risks,
            portfolio_context=candidate.portfolio_context,
            evidence=candidate.evidence,
        )

    def build_prompt(self, candidate: ResearchCandidate) -> str:
        template = self.template_path.read_text(encoding="utf-8")
        payload = json.dumps(self.build_input(candidate).model_dump(mode="json"), indent=2)
        return f"{template}\n\nInput JSON:\n```json\n{payload}\n```"

    def review(self, candidate: ResearchCandidate) -> ClaudeResearchOutput:
        if not self.enabled:
            raise RuntimeError("Claude research is disabled")

        self.logger.info("Claude multi-asset research started for %s", candidate.instrument.symbol)
        payload = self.client.analyze(self.build_prompt(candidate))
        if not isinstance(payload, dict):
            raise RuntimeError("Claude returned a non-object payload. Expected a JSON object.")
        schema = ClaudeResearchResponseSchema.model_validate(payload)
        if schema.symbol != candidate.instrument.symbol or schema.asset_class != candidate.asset_class.value:
            raise ValueError("Claude response did not match the candidate instrument")
        output = ClaudeResearchOutput.model_validate(schema.model_dump())
        evidence = candidate.evidence
        if evidence is not None:
            citations = self._validate_citations(output, {source.id for source in evidence.sources})
            conflicts = [
                (check.id, f"Unresolved discrepancy in {check.primary.metric} for the fiscal "
                           f"{check.primary.period} ended {check.primary.period_end}.")
                for check in evidence.checks if check.status == "conflict"
            ]
            if evidence.close_check and evidence.close_check.status == "conflict":
                check = evidence.close_check
                conflicts.append((check.id, f"Unresolved discrepancy in the daily close for {check.session}."))
            if conflicts:
                output.suggested_direction = "avoid"
                output.suggested_strategy = "Wait for the conflicting source figures to be reconciled."
                output.suggested_entry = output.suggested_stop_loss = output.suggested_take_profit = None
                output.needs_human_review = True
                for source_id, risk in conflicts:
                    if not any(source_id in group for group in citations.major_risks):
                        output.major_risks.append(risk)
                        citations.major_risks.append([source_id])
        self.logger.info(
            "Claude multi-asset research completed for %s confidence=%s opportunity=%s",
            output.symbol,
            output.confidence_score,
            output.opportunity_score,
        )
        return output

    @staticmethod
    def _validate_citations(output: ClaudeResearchOutput, supported_ids: set[str]) -> ResearchCitations:
        citations = output.citations
        if citations is None:
            raise ValueError("Claude omitted required evidence citations")
        if len(citations.key_catalysts) != len(output.key_catalysts) or len(citations.major_risks) != len(output.major_risks):
            raise ValueError("Claude must cite each catalyst and risk separately")
        citation_groups = [
            citations.trade_thesis, citations.bull_case, citations.bear_case,
            *citations.key_catalysts, *citations.major_risks,
        ]
        if any(not group or not set(group) <= supported_ids for group in citation_groups):
            raise ValueError("Claude returned an empty or unknown evidence citation")
        return citations
