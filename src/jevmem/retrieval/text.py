"""Lexical normalisation for BM25: lowercase word tokens, stopword removal, light stemming."""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from
    further had has have having he her here hers herself him himself his how i if in into is it
    its itself just me more most my myself no nor not now of off on once only or other our ours
    ourselves out over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up very was we were
    what when where which while who whom why will with would you your yours yourself yourselves
    im ive id ill youre dont doesnt didnt isnt arent wasnt werent cant wont""".split()  # noqa: SIM905
)


def stem(token: str) -> str:
    """Conservative suffix stripping (plurals, -ing, -ed). Deliberately simple and predictable."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith("sses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        token = token[:-1]
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    return token


def tokenize(text: str) -> list[str]:
    words = _WORD.findall(text.lower().replace("'", ""))
    return [stem(w) for w in words if w not in STOPWORDS]
