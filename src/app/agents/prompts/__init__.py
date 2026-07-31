"""Agent system prompts — production-quality prompts for all 8 specialist agents.

Updated March 2026 with Anthropic Claude prompt engineering best practices:
- XML tags for semantic boundaries
- Few-shot examples in <example> tags
- Anti-hallucination guardrails (quote-grounding, "I don't know" permission)
- Structured JSON output schemas (enforced via output_config.format at API level)
- Long context at TOP of prompt per Anthropic guidance
- Role + Goal + Instructions + Constraints + Examples structure

Prompt hash validation (P4.7)
-----------------------------
Every prompt module declares two top-level constants::

    PROMPT_VERSION = "vN"
    PROMPT_CONTENT_HASH = _compute_prompt_hash(__name__)

``_compute_prompt_hash`` (in ``_hashing.py``) reads the module's source from
disk, strips the ``PROMPT_CONTENT_HASH = ...`` line (so the hash doesn't
reference itself), and returns ``sha256(source).hexdigest()[:16]``. On app
startup we compare each module's live hash to
``settings.expected_prompt_hashes`` — if a prompt changed without a
``PROMPT_VERSION`` bump, we fail loudly so silent drift never reaches
production. Empty expected_prompt_hashes = skip validation (dev mode).
"""

from __future__ import annotations

from src.app.agents.prompts._hashing import _compute_prompt_hash
from src.app.agents.prompts.communications import (
    DRAFT_PROMPT,
    THREAD_ANALYSIS_PROMPT,
    TRIAGE_PROMPT,
)
from src.app.agents.prompts.communications import (
    PROMPT_CONTENT_HASH as COMMUNICATIONS_PROMPT_CONTENT_HASH,
)
from src.app.agents.prompts.communications import (
    PROMPT_VERSION as COMMUNICATIONS_PROMPT_VERSION,
)
from src.app.agents.prompts.diary import (
    DIARY_CONTEXT_HEADER,
    DIARY_SYSTEM_PROMPT,
)
from src.app.agents.prompts.diary import (
    PROMPT_CONTENT_HASH as DIARY_PROMPT_CONTENT_HASH,
)
from src.app.agents.prompts.diary import (
    PROMPT_VERSION as DIARY_PROMPT_VERSION,
)
from src.app.agents.prompts.memory import (
    ENTITY_SUMMARY_PROMPT,
    MEMORY_ANSWER_PROMPT,
)
from src.app.agents.prompts.memory import (
    PROMPT_CONTENT_HASH as MEMORY_PROMPT_CONTENT_HASH,
)
from src.app.agents.prompts.memory import (
    PROMPT_VERSION as MEMORY_PROMPT_VERSION,
)
from src.app.agents.prompts.notification import (
    DIGEST_FORMAT_PROMPT,
    NOTIFICATION_EVAL_PROMPT,
)
from src.app.agents.prompts.notification import (
    PROMPT_CONTENT_HASH as NOTIFICATION_PROMPT_CONTENT_HASH,
)
from src.app.agents.prompts.notification import (
    PROMPT_VERSION as NOTIFICATION_PROMPT_VERSION,
)
from src.app.agents.prompts.project import (
    PROJECT_BREAKDOWN_PROMPT,
    WSJF_PROMPT,
)
from src.app.agents.prompts.project import (
    PROMPT_CONTENT_HASH as PROJECT_PROMPT_CONTENT_HASH,
)
from src.app.agents.prompts.project import (
    PROMPT_VERSION as PROJECT_PROMPT_VERSION,
)
from src.app.agents.prompts.research import (
    PROMPT_CONTENT_HASH as RESEARCH_PROMPT_CONTENT_HASH,
)
from src.app.agents.prompts.research import (
    PROMPT_VERSION as RESEARCH_PROMPT_VERSION,
)
from src.app.agents.prompts.research import (
    QUERY_GENERATION_PROMPT,
    SYNTHESIS_PROMPT,
)
from src.app.agents.prompts.review import (
    PROMPT_CONTENT_HASH as REVIEW_PROMPT_CONTENT_HASH,
)
from src.app.agents.prompts.review import (
    PROMPT_VERSION as REVIEW_PROMPT_VERSION,
)
from src.app.agents.prompts.review import (
    QUARTERLY_REVIEW_PROMPT,
    WEEKLY_REVIEW_PROMPT,
)
from src.app.agents.prompts.routing import (
    PROMPT_CONTENT_HASH as ROUTING_PROMPT_CONTENT_HASH,
)
from src.app.agents.prompts.routing import (
    PROMPT_VERSION as ROUTING_PROMPT_VERSION,
)
from src.app.agents.prompts.routing import (
    ROUTING_SYSTEM_PROMPT,
)
from src.app.agents.prompts.tools import (
    PROMPT_CONTENT_HASH as TOOLS_PROMPT_CONTENT_HASH,
)
from src.app.agents.prompts.tools import (
    PROMPT_VERSION as TOOLS_PROMPT_VERSION,
)
from src.app.agents.prompts.tools import (
    TOOL_PLANNING_PROMPT,
    TOOL_RESULT_SUMMARY_PROMPT,
)

PROMPT_VERSIONS: dict[str, str] = {
    "communications": COMMUNICATIONS_PROMPT_VERSION,
    "diary": DIARY_PROMPT_VERSION,
    "memory": MEMORY_PROMPT_VERSION,
    "notification": NOTIFICATION_PROMPT_VERSION,
    "project": PROJECT_PROMPT_VERSION,
    "research": RESEARCH_PROMPT_VERSION,
    "review": REVIEW_PROMPT_VERSION,
    "routing": ROUTING_PROMPT_VERSION,
    "tools": TOOLS_PROMPT_VERSION,
}

# Map of agent → live sha256-16 content hash for startup validation (P4.7).
PROMPT_CONTENT_HASHES: dict[str, str] = {
    "communications": COMMUNICATIONS_PROMPT_CONTENT_HASH,
    "diary": DIARY_PROMPT_CONTENT_HASH,
    "memory": MEMORY_PROMPT_CONTENT_HASH,
    "notification": NOTIFICATION_PROMPT_CONTENT_HASH,
    "project": PROJECT_PROMPT_CONTENT_HASH,
    "research": RESEARCH_PROMPT_CONTENT_HASH,
    "review": REVIEW_PROMPT_CONTENT_HASH,
    "routing": ROUTING_PROMPT_CONTENT_HASH,
    "tools": TOOLS_PROMPT_CONTENT_HASH,
}


def validate_prompt_hashes(
    expected: dict[str, str],
    *,
    strict: bool = False,
) -> list[str]:
    """Compare live prompt hashes against an expected map.

    Returns a list of human-readable drift messages (empty if all match).
    In ``strict`` mode raises ``RuntimeError`` on any drift — used at
    startup when ``settings.expected_prompt_hashes`` is non-empty.

    Empty ``expected`` map means skip validation (dev mode).
    """
    if not expected:
        return []
    drift: list[str] = []
    for agent, expected_hash in expected.items():
        live_hash = PROMPT_CONTENT_HASHES.get(agent)
        if live_hash is None:
            drift.append(f"{agent}: no live hash registered (check prompts/__init__.py)")
            continue
        if live_hash != expected_hash:
            drift.append(
                f"{agent}: prompt content changed "
                f"(expected={expected_hash}, live={live_hash}). "
                "Bump PROMPT_VERSION and update settings.expected_prompt_hashes."
            )
    if drift and strict:
        raise RuntimeError("Prompt content drift detected:\n" + "\n".join(drift))
    return drift


__all__ = [
    "DIARY_CONTEXT_HEADER",
    "DIARY_SYSTEM_PROMPT",
    "DIGEST_FORMAT_PROMPT",
    "DRAFT_PROMPT",
    "ENTITY_SUMMARY_PROMPT",
    "MEMORY_ANSWER_PROMPT",
    "NOTIFICATION_EVAL_PROMPT",
    "PROJECT_BREAKDOWN_PROMPT",
    "PROMPT_CONTENT_HASHES",
    "PROMPT_VERSIONS",
    "QUARTERLY_REVIEW_PROMPT",
    "QUERY_GENERATION_PROMPT",
    "ROUTING_SYSTEM_PROMPT",
    "SYNTHESIS_PROMPT",
    "THREAD_ANALYSIS_PROMPT",
    "TOOL_PLANNING_PROMPT",
    "TOOL_RESULT_SUMMARY_PROMPT",
    "TRIAGE_PROMPT",
    "WEEKLY_REVIEW_PROMPT",
    "WSJF_PROMPT",
    "_compute_prompt_hash",
    "validate_prompt_hashes",
]
