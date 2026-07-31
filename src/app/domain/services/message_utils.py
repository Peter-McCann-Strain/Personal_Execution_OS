"""Shared helpers for extracting the user-visible message text."""

from __future__ import annotations


def extract_current_message(content: str) -> str:
    """Return the raw current user message from assembled context text."""
    current = content
    if "Current message:" in current:
        current = current.split("Current message:")[-1].strip()
    if "[System note:" in current:
        current = current.split("[System note:")[0].strip()
    return current.strip()
