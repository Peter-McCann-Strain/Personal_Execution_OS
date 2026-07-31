"""Pattern detection — identifies behavioural patterns from diary data using Claude.

Analyzes recent diary entries to find mood trends, energy patterns, recurring themes,
stress correlations, and productivity patterns. Uses Haiku for cost-effective analysis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.app.core.llm_helpers import call_and_parse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger()


class DetectedPattern(BaseModel):
    """A single behavioural pattern detected from diary entries."""

    pattern_type: str = Field(
        description=(
            "Category: mood_trend, energy_pattern, recurring_theme,"
            " stress_correlation, productivity_pattern"
        )
    )
    description: str = Field(description="Human-readable description of the pattern")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    evidence: list[str] = Field(
        default_factory=list,
        description="Specific diary excerpts or data points supporting this pattern",
    )
    trend: str = Field(description="Direction: improving, declining, stable, or cyclical")


class PatternAnalysis(BaseModel):
    """Full pattern analysis result from Claude."""

    patterns: list[DetectedPattern] = Field(default_factory=list)
    summary: str = Field(default="", description="Brief overall summary of patterns found")


_SYSTEM_PROMPT = """\
You are a behavioural pattern analyst for a personal assistant system.
You analyse diary entries to detect meaningful patterns in mood, energy,
themes, stress, and productivity.

<rules>
- Only report patterns with genuine evidence from the data
- Do not invent patterns that aren't supported by the entries
- Confidence should reflect how strongly the data supports the pattern
- Be specific in evidence — reference actual entries, dates, or scores
- Focus on actionable insights the user can act on
- If the data is insufficient to detect patterns, return an empty patterns list
</rules>

<output_format>
Respond with valid JSON matching this schema:
{
  "patterns": [
    {
      "pattern_type": "mood_trend | energy_pattern | recurring_theme | ...",
      "description": "Clear description of the pattern",
      "confidence": 0.0-1.0,
      "evidence": ["specific data point 1", "specific data point 2"],
      "trend": "improving | declining | stable | cyclical"
    }
  ],
  "summary": "Brief overall summary"
}

If insufficient data, return:
{"patterns": [], "summary": "Insufficient data for pattern detection."}
</output_format>"""


def _format_episodes_for_analysis(episodes: list[dict]) -> str:
    """Format episode data as structured text for Claude analysis."""
    if not episodes:
        return "No diary entries found for the analysis period."

    lines = [f"Diary entries from the last 14 days ({len(episodes)} entries):\n"]

    for ep in episodes:
        date_str = ep["created_at"].strftime("%Y-%m-%d %H:%M") if ep["created_at"] else "unknown"
        mood = f"mood={ep['mood_score']}/10" if ep["mood_score"] is not None else "mood=N/A"
        energy = (
            f"energy={ep['energy_rating']}/10" if ep["energy_rating"] is not None else "energy=N/A"
        )
        tags_str = ", ".join(ep["tags"]) if ep.get("tags") else "no tags"
        summary = ep.get("summary") or "no summary"

        lines.append(f"[{date_str}] ({mood}, {energy}) [{tags_str}]")
        lines.append(f"  {summary}")
        lines.append("")

    # Append aggregate stats
    mood_scores = [ep["mood_score"] for ep in episodes if ep["mood_score"] is not None]
    energy_scores = [ep["energy_rating"] for ep in episodes if ep["energy_rating"] is not None]

    lines.append("--- Aggregate Stats ---")
    lines.append(f"Total entries: {len(episodes)}")
    if mood_scores:
        avg_m = sum(mood_scores) / len(mood_scores)
        lines.append(f"Mood: avg={avg_m:.1f}, min={min(mood_scores)}, max={max(mood_scores)}")
    if energy_scores:
        avg_e = sum(energy_scores) / len(energy_scores)
        lines.append(f"Energy: avg={avg_e:.1f}, min={min(energy_scores)}, max={max(energy_scores)}")

    return "\n".join(lines)


async def detect_patterns(ctx: dict) -> list[dict]:
    """Detect behavioural patterns from recent episodes using Claude.

    Analyzes the last 2 weeks of diary entries to find:
    - Mood trends (improving/declining/stable)
    - Energy patterns (when are you most/least energetic)
    - Recurring themes (topics mentioned repeatedly)
    - Stress correlations (what coincides with low mood)
    - Productivity patterns (deep work timing)

    Returns list of pattern dicts: {pattern_type, description, confidence, evidence, trend}
    """
    logger.info("pattern_detection_started")

    session_factory: async_sessionmaker[AsyncSession] | None = ctx.get("session_factory")
    settings = ctx.get("settings")

    if not session_factory:
        msg = "pattern_detection_no_session_factory"
        raise RuntimeError(msg)

    if not settings:
        msg = "pattern_detection_no_settings"
        raise RuntimeError(msg)

    now = datetime.now(tz=UTC)
    two_weeks_ago = now - timedelta(days=14)

    # Fetch recent episodes
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT summary, mood_score, energy_rating, tags, created_at
                FROM episodes
                WHERE created_at >= :start AND created_at < :end
                ORDER BY created_at ASC
            """),
            {"start": two_weeks_ago, "end": now},
        )
        episodes = [dict(row) for row in result.mappings().all()]

    if not episodes:
        logger.info("pattern_detection_no_episodes", period_days=14)
        return []

    # Format data for Claude
    episode_text = _format_episodes_for_analysis(episodes)

    # Call Claude Haiku for pattern detection
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
    model = settings.classifier_model

    try:
        analysis = await call_and_parse(
            client,
            model=model,
            max_tokens=settings.pattern_detection_max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": episode_text}],
            response_model=PatternAnalysis,
            error_context="pattern_detection",
        )
    except Exception:
        logger.exception("pattern_detection_llm_failed")
        raise

    patterns = [p.model_dump() for p in analysis.patterns]

    logger.info(
        "pattern_detection_completed",
        patterns_found=len(patterns),
        episode_count=len(episodes),
        summary_length=len(analysis.summary or ""),
    )

    return patterns
