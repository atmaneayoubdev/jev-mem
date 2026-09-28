"""Family-level (cluster) bootstrap confidence intervals.

Instances of one template family are correlated, so resampling individual cases would
understate uncertainty. We resample *families* with replacement and recompute the
case-weighted mean.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from pydantic import BaseModel


class Estimate(BaseModel):
    mean: float | None
    lo: float | None
    hi: float | None
    n: int  # number of cases contributing

    def fmt(self, pct: bool = True, digits: int = 1) -> str:
        if self.mean is None:
            return "-"
        scale = 100.0 if pct else 1.0
        if self.lo is None or self.hi is None or self.lo == self.hi:
            return f"{self.mean * scale:.{digits}f}"
        lo, hi = self.lo * scale, self.hi * scale
        return f"{self.mean * scale:.{digits}f} [{lo:.{digits}f}, {hi:.{digits}f}]"


def cluster_bootstrap(
    by_cluster: Mapping[str, Sequence[float]],
    *,
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> Estimate:
    clusters = [np.asarray(v, dtype=float) for v in by_cluster.values() if len(v)]
    n = int(sum(len(c) for c in clusters))
    if not clusters:
        return Estimate(mean=None, lo=None, hi=None, n=0)
    sums = np.array([c.sum() for c in clusters])
    counts = np.array([len(c) for c in clusters], dtype=float)
    mean = float(sums.sum() / counts.sum())
    if len(clusters) < 2:
        return Estimate(mean=mean, lo=None, hi=None, n=n)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(clusters), size=(n_boot, len(clusters)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    alpha = (1 - level) / 2
    return Estimate(
        mean=mean, lo=float(np.quantile(boots, alpha)), hi=float(np.quantile(boots, 1 - alpha)), n=n
    )


class PairedEstimate(BaseModel):
    diff: float
    lo: float
    hi: float
    p_not_better: float  # fraction of bootstrap resamples with diff <= 0
    n_clusters: int


def paired_cluster_bootstrap(
    a: Mapping[str, Sequence[float]],
    b: Mapping[str, Sequence[float]],
    *,
    n_boot: int = 5000,
    seed: int = 0,
    level: float = 0.95,
) -> PairedEstimate:
    """Difference of case-weighted means (a - b) over clusters present in both."""
    keys = sorted(set(a) & set(b))
    if len(keys) < 2:
        raise ValueError("need at least two shared clusters")
    sa = np.array([np.sum(a[k]) for k in keys], dtype=float)
    sb = np.array([np.sum(b[k]) for k in keys], dtype=float)
    ca = np.array([len(a[k]) for k in keys], dtype=float)
    cb = np.array([len(b[k]) for k in keys], dtype=float)
    diff = float(sa.sum() / ca.sum() - sb.sum() / cb.sum())
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(n_boot, len(keys)))
    boots = sa[idx].sum(1) / ca[idx].sum(1) - sb[idx].sum(1) / cb[idx].sum(1)
    alpha = (1 - level) / 2
    return PairedEstimate(
        diff=diff,
        lo=float(np.quantile(boots, alpha)),
        hi=float(np.quantile(boots, 1 - alpha)),
        p_not_better=float(np.mean(boots <= 0)),
        n_clusters=len(keys),
    )
