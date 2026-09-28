"""Recover option probabilities from token logprobs of JSON-constrained output.

For a response like `{"relevance": "yes", "utility": "no"}`, the distribution over a
field's options is read from the top-k alternatives at the token where that field's value
begins. Options within one field must have distinct leading characters (all JevMem option
sets do), so the first value token identifies the option.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from jevmem.providers.qwen import TokenLogprob


def field_distribution(
    tokens: Sequence[TokenLogprob], field: str, options: Sequence[str]
) -> dict[str, float] | None:
    """Normalized probabilities over `options` for `field`, or None if not recoverable."""
    raw = "".join(t.token for t in tokens)
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"', raw)
    if match is None:
        return None
    value_start = match.end()

    position = 0
    for token in tokens:
        end = position + len(token.token)
        if end > value_start:
            break
        position = end
    else:
        return None
    prefix = raw[position:value_start]

    alternatives = dict(token.top)
    alternatives.setdefault(token.token, token.logprob)
    mass: dict[str, float] = {}
    for text, logprob in alternatives.items():
        if not text.startswith(prefix):
            continue
        rest = text[len(prefix) :].rstrip('"').lower()
        if not rest:
            continue
        hits = [o for o in options if o.lower().startswith(rest) or rest.startswith(o.lower())]
        if len(hits) == 1:
            mass[hits[0]] = mass.get(hits[0], 0.0) + math.exp(logprob)
    total = sum(mass.values())
    if total <= 0.0:
        return None
    return {o: mass.get(o, 0.0) / total for o in options}
