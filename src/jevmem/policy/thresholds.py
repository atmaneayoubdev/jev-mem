"""Centralised policy parameters.

The free parameters are kept deliberately few (τ_r, τ_u, δ, τ_w, c_w, c_intent, and the
TTL table) so calibration on the calib split cannot overfit. Defaults are starting
points only; calibrated values are written to a JSON file and recorded in every run
manifest together with POLICY_VERSION.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from jevmem.memory.models import Horizon

POLICY_VERSION = "p1.2"


class ReadThresholds(BaseModel):
    relevance: float = Field(default=0.6, ge=0.0, le=1.0)  # τ_r
    utility: float = Field(default=0.6, ge=0.0, le=1.0)  # τ_u
    band: float = Field(default=0.15, ge=0.0, le=0.5)  # δ: half-width of the UNCERTAIN band
    intent_confidence: float = Field(default=0.5, ge=0.0, le=1.0)  # c_intent


class WriteThresholds(BaseModel):
    relation: float = Field(default=0.6, ge=0.0, le=1.0)  # τ_w: min p(chosen option)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)  # c_w: min choice confidence
    instruction: float = Field(default=0.5, ge=0.0, le=1.0)  # τ_i: injection flag
    ttl_days: dict[Horizon, float] = Field(
        default_factory=lambda: {
            # Set a priori from the horizon definitions (upper end of each bucket), not tuned:
            # the judge's `memory_status` input depends on it, so it cannot be tuned offline.
            Horizon.DAYS: 7.0,
            Horizon.WEEKS: 42.0,
            Horizon.MONTHS: 180.0,
            Horizon.YEAR: 365.0,
        }
    )

    def ttl(self) -> dict[Horizon, timedelta]:
        return {h: timedelta(days=d) for h, d in self.ttl_days.items()}


class Ablation(BaseModel):
    """Switches for dimension ablations (spec §35). All on = the full JevMem policy."""

    utility: bool = True
    supersession: bool = True
    contradiction: bool = True
    temporal: bool = True  # expiry and temporary overrides
    intent: bool = True  # without intent, every query is treated as `current`


class PolicyConfig(BaseModel):
    version: str = POLICY_VERSION
    read: ReadThresholds = Field(default_factory=ReadThresholds)
    write: WriteThresholds = Field(default_factory=WriteThresholds)
    ablation: Ablation = Field(default_factory=Ablation)
    inject_uncertain: bool = False
    # `exclude`: stale memories are withheld. `annotate`: they are injected with a
    # "possibly updated" note (used where a memory unit holds several facts, e.g. LongMemEval).
    supersede_mode: Literal["exclude", "annotate"] = "exclude"

    @classmethod
    def load(cls, path: Path) -> PolicyConfig:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8", newline="\n")
