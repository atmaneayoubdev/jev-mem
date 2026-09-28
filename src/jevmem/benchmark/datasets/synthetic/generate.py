"""Build the synthetic dataset: families → seeded instances → JSONL per split.

The split is decided by which module a family lives in. The test module is authored only
after the question schema is frozen (see docs/methodology.md); until then it may not exist.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jevmem.benchmark.datasets.schema import Case, Split
from jevmem.benchmark.datasets.synthetic.dsl import DATASET, Family

SEED = 20260928
INSTANCES_PER_FAMILY = 6
_MODULES: dict[Split, str] = {
    "dev": "jevmem.benchmark.datasets.synthetic.families_dev",
    "calib": "jevmem.benchmark.datasets.synthetic.families_calib",
    "test": "jevmem.benchmark.datasets.synthetic.families_test",
}


def families(split: Split) -> list[Family]:
    try:
        module = importlib.import_module(_MODULES[split])
    except ModuleNotFoundError:
        return []
    found: list[Family] = module.FAMILIES
    return found


def build_split(split: Split, n: int = INSTANCES_PER_FAMILY, seed: int = SEED) -> list[Case]:
    fams = families(split)
    ids = [f.id for f in fams]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate family ids in {split}")
    return [case for fam in fams for case in fam.instances(n, split, seed)]


def dataset_hash(cases: list[Case]) -> str:
    h = hashlib.sha256()
    for case in cases:
        h.update(case.model_dump_json().encode())
    return h.hexdigest()


def write_split(cases: list[Case], out_dir: Path, split: Split) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{split}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for case in cases:
            fh.write(case.model_dump_json() + "\n")
    return {
        "dataset": DATASET,
        "split": split,
        "cases": len(cases),
        "families": len({c.family for c in cases}),
        "categories": dict(sorted(Counter(c.category for c in cases).items())),
        "sha256": dataset_hash(cases),
        "seed": SEED,
    }


def load_split(path: Path) -> list[Case]:
    with path.open(encoding="utf-8") as fh:
        return [Case.model_validate_json(line) for line in fh if line.strip()]


def build_all(
    out_dir: Path, splits: tuple[Split, ...] = ("dev", "calib", "test")
) -> dict[str, Any]:
    manifest: dict[str, Any] = {}
    all_families: dict[str, str] = {}
    for split in splits:
        cases = build_split(split)
        if not cases:
            continue
        for fam in {c.family for c in cases}:
            if fam in all_families:
                raise ValueError(f"family {fam} appears in both {all_families[fam]} and {split}")
            all_families[fam] = split
        manifest[split] = write_split(cases, out_dir, split)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest
