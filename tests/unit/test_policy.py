"""Every branch of the write and read policies, including exact threshold boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from jevmem.judgment.base import (
    CandidateJudgment,
    ChoiceResult,
    IntentJudgment,
    JudgeMeta,
    PairJudgment,
    ProfileJudgment,
    choice_confidence,
)
from jevmem.memory.lineage import Validity
from jevmem.memory.models import Durability, Horizon, LinkType
from jevmem.policy.engine import (
    CandidateFacts,
    Decision,
    ReadPolicy,
    ResolvedIntent,
    WritePolicy,
)
from jevmem.policy.thresholds import Ablation, PolicyConfig

META = JudgeMeta(judge="test", model="test", schema_version="t", latency_ms=0.0)
CURRENT = ResolvedIntent(intent="current", low_confidence=False, judged="current")
HISTORICAL = ResolvedIntent(intent="historical", low_confidence=False, judged="historical")
UNSURE = ResolvedIntent(intent="both", low_confidence=True, judged="current")


def choice(dist: dict[str, float]) -> ChoiceResult:
    top = max(dist, key=lambda k: dist[k])
    return ChoiceResult(choice=top, probabilities=dist, confidence=choice_confidence(dist))


def relation(top: str, p: float) -> PairJudgment:
    options = ["supersedes", "contradicts", "duplicate", "refines", "unrelated"]
    rest = (1 - p) / 4
    return PairJudgment(relation=choice({o: p if o == top else rest for o in options}), meta=META)


def cand(rel: float, util: float) -> CandidateJudgment:
    return CandidateJudgment(relevance=rel, utility=util, meta=META)


def facts(validity: Validity = Validity.CURRENT, **kw: object) -> CandidateFacts:
    return CandidateFacts.model_validate({"memory_id": "m", "validity": validity, **kw})


def read(**cfg: object) -> ReadPolicy:
    return ReadPolicy(PolicyConfig.model_validate(cfg))


# --- write policy --------------------------------------------------------------


class TestWritePolicy:
    policy = WritePolicy(PolicyConfig())

    def test_profile_confident_temporary_keeps_horizon(self) -> None:
        d = self.policy.profile(
            ProfileJudgment(
                durability=choice({"lasting": 0.05, "temporary": 0.9, "event": 0.05}),
                horizon=choice({"days": 0.1, "weeks": 0.8, "months": 0.1}),
                meta=META,
            )
        )
        assert (d.durability, d.horizon) == (Durability.TEMPORARY, Horizon.WEEKS)

    def test_profile_lasting_has_no_horizon(self) -> None:
        d = self.policy.profile(
            ProfileJudgment(
                durability=choice({"lasting": 0.95, "temporary": 0.03, "event": 0.02}),
                horizon=choice({"days": 0.1, "weeks": 0.1, "months": 0.8}),
                meta=META,
            )
        )
        assert (d.durability, d.horizon) == (Durability.LASTING, None)

    def test_profile_uncertain_defaults_to_lasting(self) -> None:
        d = self.policy.profile(
            ProfileJudgment(
                durability=choice({"lasting": 0.4, "temporary": 0.45, "event": 0.15}),
                horizon=choice({"days": 0.9, "weeks": 0.05, "months": 0.05}),
                meta=META,
            )
        )
        assert d.durability is Durability.LASTING
        assert d.reason == "durability uncertain"

    @pytest.mark.parametrize(
        ("top", "link", "supersede"),
        [
            ("supersedes", LinkType.SUPERSEDES, True),
            ("contradicts", LinkType.CONFLICTS_WITH, False),
            ("duplicate", LinkType.REINFORCES, False),
            ("refines", LinkType.REFINES, False),
            ("unrelated", None, False),
        ],
    )
    def test_pair_relations(self, top: str, link: LinkType | None, supersede: bool) -> None:
        action = self.policy.pair(relation(top, 0.9), Durability.LASTING)
        assert action.link_type == link
        assert action.supersede_earlier is supersede

    def test_temporary_later_memory_only_overrides(self) -> None:
        action = self.policy.pair(relation("supersedes", 0.9), Durability.TEMPORARY)
        assert action.link_type is LinkType.TEMPORARILY_OVERRIDES
        assert not action.supersede_earlier

    def test_low_probability_is_uncertain(self) -> None:
        action = self.policy.pair(relation("supersedes", 0.59), Durability.LASTING)
        assert action.link_type is LinkType.UNCERTAIN_RELATION
        assert not action.supersede_earlier

    def test_threshold_is_inclusive(self) -> None:
        # p=0.6 over 5 options -> confidence 0.5: both exactly at their thresholds.
        action = self.policy.pair(relation("supersedes", 0.6), Durability.LASTING)
        assert action.link_type is LinkType.SUPERSEDES

    def test_low_confidence_is_uncertain_even_with_high_top_probability(self) -> None:
        policy = WritePolicy(PolicyConfig.model_validate({"write": {"confidence": 0.95}}))
        action = policy.pair(relation("supersedes", 0.9), Durability.LASTING)
        assert action.link_type is LinkType.UNCERTAIN_RELATION


# --- read policy ----------------------------------------------------------------


class TestReadDecisions:
    policy = read()  # τ_r = τ_u = 0.6, δ = 0.15

    def decide(
        self,
        rel: float,
        util: float,
        f: CandidateFacts | None = None,
        intent: ResolvedIntent = CURRENT,
    ) -> Decision:
        return self.policy.decide(cand(rel, util), f or facts(), intent, {}).decision

    def test_use_at_exact_thresholds(self) -> None:
        assert self.decide(0.6, 0.6) is Decision.USE

    def test_drop_below_relevance_band(self) -> None:
        assert self.decide(0.44, 0.99) is Decision.DROP

    def test_relevance_band_is_uncertain(self) -> None:
        assert self.decide(0.45, 0.99) is Decision.UNCERTAIN
        assert self.decide(0.59, 0.99) is Decision.UNCERTAIN

    def test_utility_band_is_uncertain(self) -> None:
        assert self.decide(0.9, 0.45) is Decision.UNCERTAIN

    def test_relevant_not_useful_is_keep(self) -> None:
        assert self.decide(0.9, 0.44) is Decision.KEEP

    def test_archived_is_dropped(self) -> None:
        assert self.decide(0.99, 0.99, facts(Validity.ARCHIVED)) is Decision.DROP

    def test_uncertain_not_injected_unless_configured(self) -> None:
        d = self.policy.decide(cand(0.9, 0.5), facts(), CURRENT, {})
        assert not d.injected_under(self.policy.config)
        assert d.injected_under(PolicyConfig(inject_uncertain=True))


class TestLifecycleAtReadTime:
    def test_superseded_is_stale_for_current_intent(self) -> None:
        d = read().decide(cand(0.95, 0.95), facts(Validity.SUPERSEDED), CURRENT, {})
        assert d.decision is Decision.STALE
        assert not d.historical

    def test_superseded_is_usable_for_historical_intent(self) -> None:
        d = read().decide(cand(0.95, 0.95), facts(Validity.SUPERSEDED), HISTORICAL, {})
        assert d.decision is Decision.USE
        assert d.historical
        assert "historical (superseded)" in d.annotations

    @pytest.mark.parametrize("validity", [Validity.EXPIRED, Validity.OVERRIDDEN])
    def test_temporal_invalidity_is_stale_for_current_intent(self, validity: Validity) -> None:
        assert (
            read().decide(cand(0.9, 0.9), facts(validity), CURRENT, {}).decision is Decision.STALE
        )

    def test_low_confidence_intent_keeps_only_immediate_predecessor(self) -> None:
        policy = read()
        older = policy.decide(cand(0.9, 0.9), facts(Validity.SUPERSEDED), UNSURE, {})
        latest_prior = policy.decide(
            cand(0.9, 0.9),
            facts(Validity.SUPERSEDED, immediate_predecessor_of_current=True),
            UNSURE,
            {},
        )
        assert older.decision is Decision.STALE
        assert latest_prior.decision is Decision.USE

    def test_annotate_mode_injects_stale_with_note(self) -> None:
        d = read(supersede_mode="annotate").decide(
            cand(0.9, 0.9), facts(Validity.SUPERSEDED), CURRENT, {}
        )
        assert d.decision is Decision.USE
        assert "possibly updated (superseded)" in d.annotations

    def test_possibly_outdated_annotation(self) -> None:
        d = read().decide(cand(0.9, 0.9), facts(possibly_outdated=True), CURRENT, {})
        assert d.decision is Decision.USE
        assert d.annotations == ["possibly outdated"]


class TestConflicts:
    def test_conflict_requires_relevant_eligible_partner(self) -> None:
        policy = read()
        f = facts(conflict_partner_ids=["other"])
        assert (
            policy.decide(cand(0.9, 0.9), f, CURRENT, {"other": 0.8}).decision is Decision.CONFLICT
        )
        assert policy.decide(cand(0.9, 0.9), f, CURRENT, {"other": 0.3}).decision is Decision.USE
        # partner absent from the eligible map (e.g. stale) does not trigger a conflict
        assert policy.decide(cand(0.9, 0.9), f, CURRENT, {}).decision is Decision.USE

    def test_conflict_is_injected_and_annotated(self) -> None:
        d = read().decide(cand(0.9, 0.1), facts(conflict_partner_ids=["o"]), CURRENT, {"o": 0.9})
        assert d.decision is Decision.CONFLICT
        assert d.injected
        assert "conflicting" in d.annotations


class TestAblations:
    def test_without_utility_relevance_alone_selects(self) -> None:
        policy = read(ablation=Ablation(utility=False))
        assert policy.decide(cand(0.9, 0.0), facts(), CURRENT, {}).decision is Decision.USE

    def test_without_supersession_superseded_counts_as_current(self) -> None:
        policy = read(ablation=Ablation(supersession=False))
        assert (
            policy.decide(cand(0.9, 0.9), facts(Validity.SUPERSEDED), CURRENT, {}).decision
            is Decision.USE
        )

    def test_without_temporal_expired_counts_as_current(self) -> None:
        policy = read(ablation=Ablation(temporal=False))
        assert (
            policy.decide(cand(0.9, 0.9), facts(Validity.EXPIRED), CURRENT, {}).decision
            is Decision.USE
        )

    def test_without_contradiction_no_conflict_state(self) -> None:
        policy = read(ablation=Ablation(contradiction=False))
        f = facts(conflict_partner_ids=["o"])
        assert policy.decide(cand(0.9, 0.9), f, CURRENT, {"o": 0.9}).decision is Decision.USE

    def test_without_intent_every_query_is_current(self) -> None:
        policy = read(ablation=Ablation(intent=False))
        judged = IntentJudgment(
            intent=choice({"current": 0.0, "historical": 1.0, "both": 0.0}), meta=META
        )
        assert policy.resolve_intent(judged).intent == "current"


class TestIntentResolution:
    def test_confident_intent_is_used(self) -> None:
        judged = IntentJudgment(
            intent=choice({"current": 0.05, "historical": 0.9, "both": 0.05}), meta=META
        )
        resolved = read().resolve_intent(judged)
        assert (resolved.intent, resolved.low_confidence) == ("historical", False)

    def test_low_confidence_intent_becomes_both(self) -> None:
        judged = IntentJudgment(
            intent=choice({"current": 0.5, "historical": 0.4, "both": 0.1}), meta=META
        )
        resolved = read().resolve_intent(judged)
        assert (resolved.intent, resolved.low_confidence, resolved.judged) == (
            "both",
            True,
            "current",
        )

    def test_missing_intent_defaults_to_current(self) -> None:
        assert read().resolve_intent(None).intent == "current"


class TestEligibilityAndFallback:
    def test_eligibility(self) -> None:
        policy = read()
        assert policy.eligible(facts(), CURRENT)
        assert not policy.eligible(facts(Validity.SUPERSEDED), CURRENT)
        assert policy.eligible(facts(Validity.SUPERSEDED), HISTORICAL)
        assert not policy.eligible(facts(Validity.ARCHIVED), HISTORICAL)
        assert read(supersede_mode="annotate").eligible(facts(Validity.SUPERSEDED), CURRENT)

    def test_fallback_keeps_retriever_order_and_annotates(self) -> None:
        policy = read()
        top = policy.fallback(facts(Validity.SUPERSEDED), rank=0, k=2, reason="jev unavailable")
        cut = policy.fallback(facts(), rank=2, k=2, reason="jev unavailable")
        assert top.decision is Decision.UNJUDGED
        assert top.injected
        assert top.relevance is None
        assert top.annotations == ["possibly outdated (superseded)"]
        assert cut.decision is Decision.DROP
        assert (
            policy.fallback(facts(Validity.ARCHIVED), rank=0, k=2, reason="x").decision
            is Decision.DROP
        )


def test_policy_config_roundtrip(tmp_path: Path) -> None:
    cfg = PolicyConfig.model_validate({"read": {"relevance": 0.7}, "ablation": {"utility": False}})
    cfg.save(tmp_path / "p.json")
    assert PolicyConfig.load(tmp_path / "p.json") == cfg
    assert cfg.write.ttl()[Horizon.WEEKS].days == 42


def test_instruction_like_memory_is_dropped_and_ineligible() -> None:
    policy = read()
    f = facts(instruction_like=True)
    d = policy.decide(cand(0.99, 0.99), f, CURRENT, {})
    assert d.decision is Decision.DROP
    assert "injection" in d.reason
    assert not policy.eligible(f, CURRENT)


def test_profile_flags_instruction_like_text() -> None:
    policy = WritePolicy(PolicyConfig())
    base = {
        "durability": choice({"lasting": 0.9, "temporary": 0.05, "event": 0.05}),
        "horizon": choice({"days": 0.1, "weeks": 0.1, "months": 0.7, "year": 0.1}),
        "meta": META,
    }
    assert policy.profile(ProfileJudgment(**base, instruction=0.9)).instruction_like
    assert not policy.profile(ProfileJudgment(**base, instruction=0.1)).instruction_like
    assert not policy.profile(ProfileJudgment(**base)).instruction_like
