"""Plotly chart generation for visualisations (mood, habits, goals).

All functions return PNG bytes suitable for sending via Telegram or embedding
in reports.  Charts use the ``plotly_white`` template for a clean look and
are rendered to static images via kaleido.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import plotly.graph_objects as go
import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WIDTH = 800
_HEIGHT = 500
_TEMPLATE = "plotly_white"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fig_to_png(fig: go.Figure) -> bytes:
    """Render a Plotly figure to PNG bytes via kaleido."""
    buf = io.BytesIO()
    fig.write_image(buf, format="png", width=_WIDTH, height=_HEIGHT)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Mood / Energy over time
# ---------------------------------------------------------------------------


def mood_energy_chart(episodes: list[dict[str, Any]]) -> bytes:
    """Line chart with mood and energy scores over time.

    Each episode dict is expected to have:
    - ``created_at`` (datetime)
    - ``mood_score`` (float | None)
    - ``energy_rating`` (float | None)

    Returns PNG bytes, or ``b""`` if *episodes* is empty.
    """
    if not episodes:
        logger.debug("mood_energy_chart_skipped", reason="empty input")
        return b""

    dates: list[datetime] = []
    mood_scores: list[float | None] = []
    energy_ratings: list[float | None] = []

    for ep in episodes:
        dates.append(ep["created_at"])
        mood_scores.append(ep.get("mood_score"))
        energy_ratings.append(ep.get("energy_rating"))

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=mood_scores,
            mode="lines+markers",
            name="Mood",
            line={"color": "royalblue", "width": 2},
            marker={"size": 6},
            connectgaps=False,
        )
    )

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=energy_ratings,
            mode="lines+markers",
            name="Energy",
            line={"color": "darkorange", "width": 2},
            marker={"size": 6},
            connectgaps=False,
        )
    )

    fig.update_layout(
        template=_TEMPLATE,
        title="Mood & Energy Over Time",
        xaxis_title="Date",
        yaxis_title="Score",
        yaxis={"range": [0, 10]},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )

    logger.info("mood_energy_chart_generated", episodes=len(episodes))
    return _fig_to_png(fig)


# ---------------------------------------------------------------------------
# Habit streaks
# ---------------------------------------------------------------------------


def habit_streak_chart(habits: list[dict[str, Any]]) -> bytes:
    """Horizontal bar chart showing current and longest streaks per habit.

    Each habit dict is expected to have:
    - ``name`` (str)
    - ``current_streak`` (int)
    - ``longest_streak`` (int)

    Returns PNG bytes, or ``b""`` if *habits* is empty.
    """
    if not habits:
        logger.debug("habit_streak_chart_skipped", reason="empty input")
        return b""

    names = [h["name"] for h in habits]
    current = [h["current_streak"] for h in habits]
    longest = [h["longest_streak"] for h in habits]

    fig = go.Figure()

    # Longest streak shown first (lighter, acts as background)
    fig.add_trace(
        go.Bar(
            y=names,
            x=longest,
            orientation="h",
            name="Longest Streak",
            marker={
                "color": "rgba(65, 105, 225, 0.25)",
                "line": {"color": "royalblue", "width": 1.5},
            },
        )
    )

    # Current streak overlaid (solid)
    fig.add_trace(
        go.Bar(
            y=names,
            x=current,
            orientation="h",
            name="Current Streak",
            marker={"color": "royalblue"},
        )
    )

    fig.update_layout(
        template=_TEMPLATE,
        title="Habit Streaks",
        xaxis_title="Days",
        barmode="overlay",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )

    logger.info("habit_streak_chart_generated", habits=len(habits))
    return _fig_to_png(fig)


# ---------------------------------------------------------------------------
# Goal progress
# ---------------------------------------------------------------------------

_STATUS_COLORS: dict[str, str] = {
    "active": "royalblue",
    "at_risk": "darkorange",
    "completed": "green",
}


def goal_progress_chart(goals: list[dict[str, Any]]) -> bytes:
    """Horizontal bar chart showing progress for each goal.

    Each goal dict is expected to have:
    - ``title`` (str)
    - ``progress`` (float, 0-1)
    - ``status`` (str - ``"active"``, ``"at_risk"``, or ``"completed"``)

    Returns PNG bytes, or ``b""`` if *goals* is empty.
    """
    if not goals:
        logger.debug("goal_progress_chart_skipped", reason="empty input")
        return b""

    titles = [g["title"] for g in goals]
    progress = [g["progress"] * 100 for g in goals]
    colors = [_STATUS_COLORS.get(g["status"], "grey") for g in goals]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            y=titles,
            x=progress,
            orientation="h",
            marker={"color": colors},
            text=[f"{p:.0f}%" for p in progress],
            textposition="auto",
        )
    )

    fig.update_layout(
        template=_TEMPLATE,
        title="Goal Progress",
        xaxis_title="Progress (%)",
        xaxis={"range": [0, 100]},
        showlegend=False,
    )

    logger.info("goal_progress_chart_generated", goals=len(goals))
    return _fig_to_png(fig)
