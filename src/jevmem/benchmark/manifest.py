"""Reproducibility manifest for a benchmark run."""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_versions(
    names: tuple[str, ...] = (
        "jevmem",
        "httpx",
        "pydantic",
        "numpy",
        "sentence-transformers",
        "torch",
        "transformers",
    ),
) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def build_manifest(**sections: Any) -> dict[str, Any]:
    status = _git("status", "--porcelain")
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(status) if status is not None else None,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": package_versions(),
        **sections,
    }
