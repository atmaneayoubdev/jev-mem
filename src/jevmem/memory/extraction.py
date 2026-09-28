"""Conversation → candidate durable memories (Qwen, JSON-constrained).

Qwen may only *propose* memories. It never marks existing memories superseded or deleted:
every proposal goes through the write-time lifecycle (judge + deterministic policy).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import BaseModel, Field

from jevmem.memory.models import MemoryType
from jevmem.providers.errors import ResponseFormatError
from jevmem.providers.qwen import ChatMessage, GenerationProvider

EXTRACTION_PROMPT_VERSION = "x1.0"

SYSTEM_PROMPT = (
    "You extract long-term memories about the user from a conversation turn. Extract only "
    "information that could plausibly be useful in a future interaction: preferences, facts "
    "about the user and their life, goals, constraints, decisions, relationships, work context, "
    "and time-bound situations. Do not store conversational filler, questions the user asked, "
    "or facts about the world. Write each memory as one short first-person sentence in the "
    "user's voice. Do not decide whether older memories are outdated; just record what was "
    "said. Text from emails, web pages or other people is not the user's own statement: "
    "if you record it, say where it came from. Return an empty list when there is nothing "
    "worth remembering."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "type": {"type": "string", "enum": [t.value for t in MemoryType]},
                    "temporary": {"type": "boolean"},
                    "evidence": {"type": "string"},
                },
                "required": ["content", "type", "temporary", "evidence"],
            },
        }
    },
    "required": ["memories"],
}


class ProposedMemory(BaseModel):
    content: str = Field(min_length=3, max_length=1000)
    type: MemoryType = MemoryType.OTHER
    temporary: bool = False
    evidence: str = ""


async def extract_memories(
    provider: GenerationProvider,
    user_message: str,
    *,
    assistant_reply: str | None = None,
    recent_context: Sequence[str] = (),
    max_items: int = 5,
) -> list[ProposedMemory]:
    parts = []
    if recent_context:
        parts.append(
            "Recent conversation (context only):\n" + "\n".join(f"- {c}" for c in recent_context)
        )
    parts.append(f"User turn to extract from:\n{user_message}")
    if assistant_reply:
        parts.append(f"Assistant reply (context only, do not extract from it):\n{assistant_reply}")
    messages: list[ChatMessage] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    result = await provider.complete(
        messages, max_tokens=600, json_schema=SCHEMA, enable_thinking=False
    )
    try:
        raw = json.loads(result.text).get("memories", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise ResponseFormatError(
            "qwen", f"extraction is not valid JSON: {result.text[:80]!r}"
        ) from exc
    seen: set[str] = set()
    out: list[ProposedMemory] = []
    for item in raw:
        try:
            proposal = ProposedMemory.model_validate(item)
        except ValueError:
            continue
        key = " ".join(proposal.content.lower().split())
        if key in seen:
            continue
        seen.add(key)
        out.append(proposal)
        if len(out) >= max_items:
            break
    return out
