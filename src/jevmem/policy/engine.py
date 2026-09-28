"""Deterministic memory policies.

Judges produce probabilities; these policies alone decide what happens. Both are pure
functions of their inputs, so every decision can be replayed from cached judgments with
different thresholds or ablations without calling a model again.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from jevmem.judgment.base import (
    CandidateJudgment,
    ChoiceResult,
    IntentJudgment,
    PairJudgment,
    ProfileJudgment,
)
from jevmem.memory.lineage import Validity
from jevmem.memory.models import Durability, Horizon, LinkType
from jevmem.policy.thresholds import PolicyConfig

Intent = Literal["current", "historical", "both"]


# --- Write policy ------------------------------------------------------------------


class ProfileDecision(BaseModel):
    durability: Durability
    horizon: Horizon | None
    instruction_like: bool = False
    reason: str


class WriteAction(BaseModel):
    """What to record for one (earlier, later) pair. `link_type=None` means no relation."""

    link_type: LinkType | None
    supersede_earlier: bool = False
    reason: str


class WritePolicy:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config

    def _confident(self, result: ChoiceResult) -> bool:
        t = self.config.write
        return result.p(result.choice) >= t.relation and result.confidence >= t.confidence

    def profile(self, judgment: ProfileJudgment) -> ProfileDecision:
        flagged = (
            judgment.instruction is not None
            and judgment.instruction >= self.config.write.instruction
        )
        decision = self._durability(judgment)
        return decision.model_copy(update={"instruction_like": flagged})

    def _durability(self, judgment: ProfileJudgment) -> ProfileDecision:
        durability = judgment.durability
        if not self._confident(durability):
            # Uncertain durability defaults to LASTING: a fact is never expired on a guess.
            return ProfileDecision(
                durability=Durability.LASTING, horizon=None, reason="durability uncertain"
            )
        kind = Durability(durability.choice)
        horizon = Horizon(judgment.horizon.choice) if kind is Durability.TEMPORARY else None
        return ProfileDecision(durability=kind, horizon=horizon, reason=f"judged {kind.value}")

    def pair(self, judgment: PairJudgment, later_durability: Durability | None) -> WriteAction:
        relation = judgment.relation
        if not self._confident(relation):
            top_p = relation.p(relation.choice)
            return WriteAction(
                link_type=LinkType.UNCERTAIN_RELATION,
                reason=f"relation uncertain (top={relation.choice} p={top_p:.2f})",
            )
        match relation.choice:
            case "supersedes" if later_durability is Durability.TEMPORARY:
                return WriteAction(
                    link_type=LinkType.TEMPORARILY_OVERRIDES,
                    reason="temporary memory overrides until it expires",
                )
            case "supersedes":
                return WriteAction(
                    link_type=LinkType.SUPERSEDES, supersede_earlier=True, reason="superseded"
                )
            case "contradicts":
                return WriteAction(link_type=LinkType.CONFLICTS_WITH, reason="contradiction")
            case "duplicate":
                return WriteAction(link_type=LinkType.REINFORCES, reason="duplicate")
            case "refines":
                return WriteAction(link_type=LinkType.REFINES, reason="refinement")
            case _:
                return WriteAction(link_type=None, reason="unrelated")


# --- Read policy -------------------------------------------------------------------


class Decision(StrEnum):
    USE = "use"
    KEEP = "keep"  # relevant but not useful now; not injected
    DROP = "drop"
    STALE = "stale"  # superseded / expired / overridden for a current-intent query
    CONFLICT = "conflict"  # injected together with its conflict partner(s), annotated
    UNCERTAIN = "uncertain"  # inside the uncertainty band; injected only if configured
    UNJUDGED = "unjudged"  # judge unavailable: retriever order, never a faked judgment


INJECTED = {Decision.USE, Decision.CONFLICT, Decision.UNJUDGED}


class CandidateFacts(BaseModel):
    """What Python knows about a candidate, independent of any judge."""

    memory_id: str
    validity: Validity
    conflict_partner_ids: list[str] = Field(default_factory=list)
    possibly_outdated: bool = False  # has an UNCERTAIN_RELATION link from a later memory
    instruction_like: bool = False  # flagged at write time as trying to direct an AI
    immediate_predecessor_of_current: bool = False


class ResolvedIntent(BaseModel):
    intent: Intent
    low_confidence: bool
    judged: Intent | None  # the judge's raw choice, for the record


class ReadDecision(BaseModel):
    memory_id: str
    decision: Decision
    reason: str
    relevance: float | None = None
    utility: float | None = None
    validity: Validity
    historical: bool = False  # eligible only as past context (superseded/expired)
    annotations: list[str] = Field(default_factory=list)

    @property
    def injected(self) -> bool:
        return self.decision in INJECTED

    def injected_under(self, config: PolicyConfig) -> bool:
        return self.injected or (config.inject_uncertain and self.decision is Decision.UNCERTAIN)


class ReadPolicy:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config

    def resolve_intent(self, judgment: IntentJudgment | None) -> ResolvedIntent:
        if judgment is None or not self.config.ablation.intent:
            return ResolvedIntent(intent="current", low_confidence=False, judged=None)
        raw = judgment.intent.choice
        judged: Intent = raw if raw in ("current", "historical", "both") else "current"  # type: ignore[assignment]
        if judgment.intent.confidence < self.config.read.intent_confidence:
            return ResolvedIntent(intent="both", low_confidence=True, judged=judged)
        return ResolvedIntent(intent=judged, low_confidence=False, judged=judged)

    def effective_validity(self, validity: Validity) -> Validity:
        a = self.config.ablation
        if validity is Validity.SUPERSEDED and not a.supersession:
            return Validity.CURRENT
        if validity in (Validity.EXPIRED, Validity.OVERRIDDEN) and not a.temporal:
            return Validity.CURRENT
        return validity

    def eligible(self, facts: CandidateFacts, intent: ResolvedIntent) -> bool:
        """Whether lifecycle state allows this memory to be used for this query at all."""
        validity = self.effective_validity(facts.validity)
        if validity is Validity.ARCHIVED or facts.instruction_like:
            return False
        if validity.is_current or self.config.supersede_mode == "annotate":
            return True
        return self._stale_reason(validity, facts, intent) is None

    def decide(
        self,
        judgment: CandidateJudgment,
        facts: CandidateFacts,
        intent: ResolvedIntent,
        eligible_relevance: Mapping[str, float],
    ) -> ReadDecision:
        """Decide one candidate.

        `eligible_relevance` maps the ids of *eligible* candidates (see `eligible`) to their
        judged relevance; it is used to decide whether a conflict partner is in play.
        """
        t = self.config.read
        rel, util = judgment.relevance, judgment.utility
        validity = self.effective_validity(facts.validity)
        historical = not validity.is_current
        annotations = ["possibly outdated"] if facts.possibly_outdated else []

        def make(decision: Decision, reason: str, *extra: str) -> ReadDecision:
            return ReadDecision(
                memory_id=facts.memory_id,
                decision=decision,
                reason=reason,
                relevance=rel,
                utility=util,
                validity=validity,
                historical=historical and decision is not Decision.STALE,
                annotations=[*annotations, *extra],
            )

        if validity is Validity.ARCHIVED:
            return make(Decision.DROP, "archived")
        if facts.instruction_like:
            return make(Decision.DROP, "instruction-like content (possible injection)")
        if rel < t.relevance - t.band:
            return make(Decision.DROP, "not relevant")

        if historical:
            stale_reason = self._stale_reason(validity, facts, intent)
            if stale_reason is None:
                annotations.append(f"historical ({validity.value})")
            elif self.config.supersede_mode == "annotate":
                annotations.append(f"possibly updated ({validity.value})")
            else:
                return make(Decision.STALE, stale_reason)

        if self.config.ablation.contradiction and rel >= t.relevance:
            partners = [
                p
                for p in facts.conflict_partner_ids
                if eligible_relevance.get(p, 0.0) >= t.relevance
            ]
            if partners:
                return make(Decision.CONFLICT, "conflicts with a relevant memory", "conflicting")

        useful = util >= t.utility if self.config.ablation.utility else True
        if rel >= t.relevance and useful:
            return make(Decision.USE, "relevant and useful")
        if rel < t.relevance or util >= t.utility - t.band:
            return make(Decision.UNCERTAIN, "inside uncertainty band")
        return make(Decision.KEEP, "relevant but not useful")

    def _stale_reason(
        self, validity: Validity, facts: CandidateFacts, intent: ResolvedIntent
    ) -> str | None:
        """Why a non-current memory must be withheld for this query, or None if eligible."""
        if intent.intent == "current":
            return f"{validity.value} and query is about the present"
        if intent.low_confidence and not facts.immediate_predecessor_of_current:
            return f"{validity.value}; intent uncertain so only the latest prior version is kept"
        return None

    def fallback(self, facts: CandidateFacts, rank: int, k: int, reason: str) -> ReadDecision:
        """Judge unavailable: keep retriever order for the top k, with lifecycle annotations."""
        validity = self.effective_validity(facts.validity)
        annotations = [] if validity.is_current else [f"possibly outdated ({validity.value})"]
        decision = (
            Decision.UNJUDGED if rank < k and validity is not Validity.ARCHIVED else Decision.DROP
        )
        return ReadDecision(
            memory_id=facts.memory_id,
            decision=decision,
            reason=f"fallback: {reason}",
            validity=validity,
            annotations=annotations,
        )
