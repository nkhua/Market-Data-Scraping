from __future__ import annotations

from app.config import AutonomySettings
from app.models import (
    AccountAutonomyState,
    AnalystDecision,
    AnalystResponse,
    AutonomyAction,
    AutonomyDecision,
    OrderApproval,
    TradeIntent,
)


class AutonomyEngine:
    def __init__(self, settings: AutonomySettings) -> None:
        self.settings = settings
        self.auto_execute_catalysts = {item.lower() for item in settings.auto_execute_allowed_catalysts}
        self.approval_catalysts = {item.lower() for item in settings.approval_required_allowed_catalysts}
        self.auto_execute_convictions = set(settings.auto_execute_allowed_conviction_buckets)
        self.approval_convictions = set(settings.approval_required_allowed_conviction_buckets)
        self.blocked_risk_tags = {item.lower() for item in settings.blocked_risk_tags}
        self.approval_risk_tags = {item.lower() for item in settings.approval_required_risk_tags}

    def classify(
        self,
        intent: TradeIntent,
        risk_approval: OrderApproval,
        analyst_review: AnalystResponse | None,
        account_state: AccountAutonomyState,
    ) -> AutonomyDecision:
        reasons: list[str] = []
        if not risk_approval.approved:
            return AutonomyDecision(
                action=AutonomyAction.BLOCKED,
                base_action=AutonomyAction.BLOCKED,
                reasons=risk_approval.reasons or ["Hard risk constraints failed"],
                risk_approval=risk_approval,
            )

        if account_state.total_drawdown_pct >= self.settings.shutdown_total_drawdown_pct:
            return AutonomyDecision(
                action=AutonomyAction.BLOCKED,
                base_action=AutonomyAction.BLOCKED,
                reasons=[
                    "Total drawdown shutdown triggered",
                    f"total_drawdown_pct={account_state.total_drawdown_pct:.2%}",
                ],
                risk_approval=risk_approval,
            )

        catalyst = analyst_review.catalyst_classification.lower() if analyst_review else ""
        conviction = intent.conviction.value
        risk_tags = {tag.lower() for tag in (analyst_review.risk_tags if analyst_review else [])}

        if risk_tags & self.blocked_risk_tags:
            return AutonomyDecision(
                action=AutonomyAction.BLOCKED,
                base_action=AutonomyAction.BLOCKED,
                reasons=[f"Blocked risk tags present: {sorted(risk_tags & self.blocked_risk_tags)}"],
                risk_approval=risk_approval,
            )

        base_action = AutonomyAction.APPROVAL_REQUIRED
        if analyst_review is None:
            if self.settings.require_analyst_for_approval:
                return AutonomyDecision(
                    action=AutonomyAction.BLOCKED,
                    base_action=AutonomyAction.BLOCKED,
                    reasons=["Analyst review required for this autonomy configuration"],
                    risk_approval=risk_approval,
                )
            reasons.append("Analyst review missing, routing to manual approval")
        else:
            if analyst_review.decision == AnalystDecision.REJECT:
                return AutonomyDecision(
                    action=AutonomyAction.BLOCKED,
                    base_action=AutonomyAction.BLOCKED,
                    reasons=["Analyst decision rejected the trade"],
                    risk_approval=risk_approval,
                )
            if analyst_review.confidence < self.settings.approval_required_min_confidence:
                return AutonomyDecision(
                    action=AutonomyAction.BLOCKED,
                    base_action=AutonomyAction.BLOCKED,
                    reasons=[
                        f"Analyst confidence {analyst_review.confidence:.2f} below approval threshold "
                        f"{self.settings.approval_required_min_confidence:.2f}"
                    ],
                    risk_approval=risk_approval,
                )
            if self.approval_catalysts and catalyst not in self.approval_catalysts:
                return AutonomyDecision(
                    action=AutonomyAction.BLOCKED,
                    base_action=AutonomyAction.BLOCKED,
                    reasons=[f"Catalyst {catalyst!r} not allowed for approval-required review"],
                    risk_approval=risk_approval,
                )
            if self.approval_convictions and conviction not in self.approval_convictions:
                return AutonomyDecision(
                    action=AutonomyAction.BLOCKED,
                    base_action=AutonomyAction.BLOCKED,
                    reasons=[f"Conviction bucket {conviction!r} not allowed for approval-required review"],
                    risk_approval=risk_approval,
                )
            if risk_tags & self.approval_risk_tags:
                reasons.append(f"Approval-required risk tags present: {sorted(risk_tags & self.approval_risk_tags)}")
            if analyst_review.decision == AnalystDecision.REVIEW:
                reasons.append("Analyst decision requires manual review")

            can_auto_execute = (
                self.settings.auto_execute_enabled
                and (not self.settings.require_analyst_for_auto_execute or analyst_review is not None)
                and analyst_review is not None
                and analyst_review.decision == AnalystDecision.ALLOW
                and analyst_review.confidence >= self.settings.auto_execute_min_confidence
                and (not self.auto_execute_catalysts or catalyst in self.auto_execute_catalysts)
                and (not self.auto_execute_convictions or conviction in self.auto_execute_convictions)
                and not (risk_tags & self.approval_risk_tags)
            )
            if can_auto_execute:
                base_action = AutonomyAction.AUTO_EXECUTE
            else:
                reasons.append("Auto-execute thresholds not met, routing to manual approval")

        action = base_action
        downgrade_steps = 0
        if account_state.consecutive_losses >= self.settings.downgrade_after_losing_streak > 0:
            action = self._downgrade(action)
            downgrade_steps += 1
            reasons.append(
                f"Losing streak downgrade triggered at {account_state.consecutive_losses} consecutive losses"
            )
        if account_state.daily_drawdown_pct >= self.settings.downgrade_daily_drawdown_pct > 0:
            action = self._downgrade(action)
            downgrade_steps += 1
            reasons.append(
                f"Daily drawdown downgrade triggered at {account_state.daily_drawdown_pct:.2%}"
            )

        if action == AutonomyAction.AUTO_EXECUTE and analyst_review is None:
            action = AutonomyAction.BLOCKED
            base_action = AutonomyAction.BLOCKED
            reasons.append("Analyst review missing for auto-execute path")

        if action == AutonomyAction.BLOCKED and not reasons:
            reasons.append("Autonomy engine blocked candidate")

        return AutonomyDecision(
            action=action,
            base_action=base_action,
            reasons=reasons,
            downgrade_steps_applied=downgrade_steps,
            risk_approval=risk_approval,
        )

    @staticmethod
    def _downgrade(action: AutonomyAction) -> AutonomyAction:
        if action == AutonomyAction.AUTO_EXECUTE:
            return AutonomyAction.APPROVAL_REQUIRED
        if action == AutonomyAction.APPROVAL_REQUIRED:
            return AutonomyAction.BLOCKED
        return AutonomyAction.BLOCKED
