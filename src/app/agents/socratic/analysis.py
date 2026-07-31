"""Post-tutorial analysis — Sonnet-powered transcript analysis.

Runs after the tutorial ends. Produces:
1. Bloom's taxonomy progression
2. Knowledge gaps (addressed and unaddressed)
3. Reasoning quality metrics
4. Engagement patterns
5. Recommendations for future sessions
6. Unresolved topics (candidates for spaced repetition)
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from anthropic import AsyncAnthropic

from src.app.agents.socratic.prompts.analysis import TUTORIAL_ANALYSIS_PROMPT
from src.app.agents.socratic.state import TutorialAnalysis
from src.app.config import get_settings
from src.app.core.llm_helpers import call_and_parse

logger = structlog.get_logger()


async def analyse_tutorial(
    state: dict[str, Any],
    client: AsyncAnthropic,
    model: str | None = None,
    max_tokens: int | None = None,
) -> TutorialAnalysis:
    """Analyse a completed tutorial transcript.

    No fallback. If Claude fails, the error propagates.
    """
    settings = get_settings()
    model = model or settings.socratic_analysis_model
    max_tokens = max_tokens or settings.socratic_analysis_max_tokens

    # Build transcript text from dialogue history
    dialogue = state.get("dialogue_history", [])
    transcript_lines = []
    for turn in dialogue:
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        transcript_lines.append(f"[{role}]: {content}")

    transcript_text = "\n\n".join(transcript_lines)

    # Build assessor log summary
    assessor_log = state.get("assessor_log", [])
    assessor_text = json.dumps(assessor_log, indent=2) if assessor_log else "No assessor log."

    # Build propositions text
    propositions = state.get("propositions", [])
    props_text = json.dumps(propositions, indent=2) if propositions else "No propositions."

    prompt = TUTORIAL_ANALYSIS_PROMPT.format(
        topic=state.get("topic", "Unknown"),
        work_type=state.get("work_type", "other"),
        num_turns=len(dialogue),
        propositions=props_text,
        transcript=transcript_text,
        assessor_log=assessor_text,
    )

    analysis = await call_and_parse(
        client,
        model=model,
        max_tokens=max_tokens,
        system="You are an expert educational analyst. Respond with valid JSON only.",
        messages=[{"role": "user", "content": prompt}],
        response_model=TutorialAnalysis,
        error_context="tutorial analysis",
        inject_personality=False,
    )

    logger.info(
        "tutorial_analysis_complete",
        session_id=state.get("session_id"),
        gaps_found=len(analysis.knowledge_gaps),
        recommendations=len(analysis.recommendations),
    )

    return analysis


def format_analysis_report(analysis: TutorialAnalysis, topic: str) -> str:
    """Format the analysis into a human-readable report for Telegram delivery."""
    lines = [
        f"**Tutorial Analysis: {topic}**\n",
        analysis.summary,
        "",
    ]

    if analysis.strong_areas:
        lines.append("**Strong Areas:**")
        for area in analysis.strong_areas:
            lines.append(f"  - {area.get('topic', '')}: {area.get('evidence', '')}")
        lines.append("")

    if analysis.knowledge_gaps:
        lines.append("**Knowledge Gaps:**")
        for gap in analysis.knowledge_gaps:
            addressed = "addressed" if gap.get("addressed") else "**unresolved**"
            lines.append(f"  - {gap.get('topic', '')} ({gap.get('severity', '')}, {addressed})")
        lines.append("")

    if analysis.recommendations:
        lines.append("**Recommendations:**")
        for rec in analysis.recommendations:
            lines.append(f"  - {rec}")
        lines.append("")

    if analysis.unresolved_topics:
        lines.append("**Topics for Future Review:**")
        for topic_name in analysis.unresolved_topics:
            lines.append(f"  - {topic_name}")
        lines.append("")

    # Engagement metrics
    metrics = analysis.engagement_metrics
    if metrics:
        student_pct = metrics.get("speaking_ratio_student_pct", "?")
        lines.append(f"**Engagement:** {student_pct}% student speaking ratio, ")
        lines.append(f"  {metrics.get('self_directed_questions', 0)} self-directed questions, ")
        lines.append(f"  {metrics.get('aha_moments', 0)} breakthrough moments")

    return "\n".join(lines)
