"""Supervisor routing — classifies intent and dispatches to specialist agents.

Uses raw Anthropic SDK with Haiku for fast, cheap classification.
Adds a small deterministic layer for high-signal user intents that should never
depend on model phrasing.
"""

from __future__ import annotations

import re

import structlog
from anthropic import AsyncAnthropic

from src.app.agents.prompts.routing import ROUTING_SYSTEM_PROMPT
from src.app.config import get_settings
from src.app.core.exceptions import LLMError, RoutingError
from src.app.core.llm_helpers import call_and_parse_with_retry
from src.app.domain.models import Intent, IntentType, Specialist
from src.app.domain.services.message_utils import extract_current_message

logger = structlog.get_logger()

_REVIEW_KEYWORDS = (
    "bottleneck",
    "blocking me",
    "blocker",
    "what patterns",
    "pattern am i",
    "pattern do you",
    "what should i change",
    "what am i missing",
    "how am i getting on",
)
_MEMORY_META_PATTERNS = (
    "how do you work",
    "how you work",
    "explain how you work",
    "what can you do",
    "how are you set up",
    "how do you remember",
)
_MEMORY_RECALL_PATTERNS = (
    "what was i working on",
    "what did i work on",
    "what was i focused on",
    "what have i been focused on",
    "what did i get up to",
    "what did i do",
    "what do i know about",
    "what do you remember",
    "when did i",
    "where did i",
    "who did i",
    "remind me what",
)
_MEMORY_TEMPORAL_MARKERS = (
    "yesterday",
    "today",
    "last night",
    "this morning",
    "this afternoon",
    "tonight",
    "this week",
    "last week",
    "recently",
)
_SAVE_PATTERNS = (
    "add this to notes",
    "add to notes",
    "add this to nots",
    "add to nots",
    "save this to notes",
    "save to notes",
    "save in notes",
    "put this in notes",
    "note this",
    "make a note",
    "jot this down",
)
_PROJECT_TASK_PATTERNS = (
    "add a task",
    "add a todo",
    "add a to-do",
    "add task",
    "add todo",
    "add to-do",
    "new task:",
    "create a task",
    "create task",
    "log a task",
)
_PLAN_DAY_PATTERNS = (
    "plan my day",
    "plan the day",
    "plan today",
    "plan tomorrow",
    "plan today:",
    "plan tomorrow:",
    "plan my tomorrow",
    "daily plan",
    "time block",
    "time-block",
    "what should i do today",
)
_QUESTION_PREFIXES = (
    "what",
    "why",
    "how",
    "where",
    "when",
    "who",
    "which",
    "do",
    "does",
    "did",
    "is",
    "are",
    "am",
    "can",
    "could",
    "should",
    "would",
)


def _classify_obvious_intent(message: str) -> Intent | None:
    """Short-circuit a few high-signal intents that were misrouting in practice."""
    current = extract_current_message(message)
    lowered = re.sub(r"\s+", " ", current.casefold()).strip()
    if not lowered:
        return None

    is_question = "?" in lowered or any(
        lowered.startswith(f"{prefix} ") for prefix in _QUESTION_PREFIXES
    )
    if is_question and any(keyword in lowered for keyword in _REVIEW_KEYWORDS):
        return Intent(
            intent_type=IntentType.REVIEW,
            confidence=0.98,
            specialist=Specialist.REVIEW,
            reasoning="Explicit question about patterns, blockers, or bottlenecks.",
        )
    if _looks_like_save_request(lowered):
        return Intent(
            intent_type=IntentType.SAVE,
            confidence=0.99,
            specialist=Specialist.SAVE,
            reasoning="Explicit save-to-notes or save-URL command.",
        )
    if _looks_like_plan_day_request(lowered):
        return Intent(
            intent_type=IntentType.PLAN_DAY,
            confidence=0.98,
            specialist=Specialist.PLAN_DAY,
            reasoning="Explicit 'plan my/the/tomorrow' daily-planning command.",
        )
    if _looks_like_project_task_request(lowered):
        return Intent(
            intent_type=IntentType.PROJECT,
            confidence=0.97,
            specialist=Specialist.PROJECT,
            reasoning="Explicit task-create command (add/new task).",
        )
    if _looks_like_memory_query(lowered, is_question=is_question):
        return Intent(
            intent_type=IntentType.QUERY,
            confidence=0.97,
            specialist=Specialist.MEMORY,
            reasoning="Explicit recall or assistant-capability question.",
        )

    return None


def _looks_like_memory_query(lowered: str, *, is_question: bool) -> bool:
    """Detect high-signal recall/meta questions that should always route to memory."""
    if any(pattern in lowered for pattern in _MEMORY_META_PATTERNS):
        return True
    if any(pattern in lowered for pattern in _MEMORY_RECALL_PATTERNS):
        return True
    if any(marker in lowered for marker in _MEMORY_TEMPORAL_MARKERS):
        return is_question or lowered.startswith("remind me")
    return False


def _looks_like_save_request(lowered: str) -> bool:
    """Detect explicit save commands that should always route to save specialist."""
    if any(pattern in lowered for pattern in _SAVE_PATTERNS):
        return True
    if re.search(r"https?://\S+", lowered) and "save" in lowered:
        return True
    return bool(
        re.match(r"^(please\s+)?save\s+(this|that|it)\b", lowered) or lowered.startswith("/save")
    )


def _looks_like_project_task_request(lowered: str) -> bool:
    """Detect explicit task-create commands that should always route to project.

    Bug 2 regression: messages starting with 'Add a task:' were being dropped
    by the Haiku classifier (either misrouted to diary or not reaching the
    orchestrator predictably). Short-circuit here so the Project specialist
    always receives them.
    """
    return any(pattern in lowered for pattern in _PROJECT_TASK_PATTERNS)


def _looks_like_plan_day_request(lowered: str) -> bool:
    """Detect explicit 'plan (my|the|tomorrow)' commands that must route to plan_day.

    Bug 4 regression: 'Plan tomorrow: 9-11 deep work...' was misrouting to
    diary because Haiku saw the long capture-style body and defaulted to
    diary. Short-circuit here so the plan_day specialist always receives
    these, regardless of body length.
    """
    if any(pattern in lowered for pattern in _PLAN_DAY_PATTERNS):
        return True
    return bool(re.match(r"^\s*plan\s+(tomorrow|today|my\s+day|the\s+day)\b", lowered))


async def classify_intent(
    message: str,
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> Intent:
    """Classify user intent using Claude Haiku.

    No fallback. If this fails, the error propagates.
    """
    heuristic = _classify_obvious_intent(message)
    if heuristic is not None:
        return heuristic

    settings = get_settings()
    model = model or settings.routing_model
    max_tokens = max_tokens or settings.routing_max_tokens

    try:
        return await call_and_parse_with_retry(
            client,
            model=model,
            max_tokens=max_tokens,
            system=ROUTING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
            response_model=Intent,
            error_context="routing",
            inject_personality=False,
        )
    except LLMError as e:
        logger.error("routing_failed", error=str(e), model=model)
        raise RoutingError(f"Routing failed: {e}") from e
