"""Personality loader with privacy-safe local identity fallback."""

from __future__ import annotations

from pathlib import Path

import structlog

logger = structlog.get_logger()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SOUL_PATH = _PROJECT_ROOT / "config" / "SOUL.md"
_IDENTITY_LOCAL_PATH = _PROJECT_ROOT / "config" / "IDENTITY.local.md"
_IDENTITY_EXAMPLE_PATH = _PROJECT_ROOT / "config" / "IDENTITY.example.md"
# Backward-compatible test seam; production resolves local first, then example.
_IDENTITY_PATH = _IDENTITY_LOCAL_PATH

_cached_personality: str | None = None


def load_personality() -> str:
    """Load and cache SOUL plus local identity, falling back to the example.

    Returns a combined string suitable for prepending to agent system prompts.
    """
    global _cached_personality
    if _cached_personality is not None:
        return _cached_personality

    parts: list[str] = []

    if _IDENTITY_PATH.exists():
        identity_path = _IDENTITY_PATH
    elif _IDENTITY_PATH == _IDENTITY_LOCAL_PATH:
        identity_path = _IDENTITY_EXAMPLE_PATH
    else:
        identity_path = _IDENTITY_PATH
    for path in (_SOUL_PATH, identity_path):
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            parts.append(content)
            logger.info("personality_loaded", file=str(path), length=len(content))
        else:
            logger.warning("personality_file_missing", file=str(path))

    _cached_personality = "\n\n".join(parts) if parts else ""
    return _cached_personality


def get_personality_prefix() -> str:
    """Get the personality prefix for injection into specialist prompts.

    Wraps the personality content in XML tags for clear prompt structure.
    """
    personality = load_personality()
    if not personality:
        return ""
    return f"<personality>\n{personality}\n</personality>\n\n"


def clear_cache() -> None:
    """Clear cached personality (for testing)."""
    global _cached_personality
    _cached_personality = None
