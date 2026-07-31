"""Deterministic confirmation and cancellation heuristics."""

from __future__ import annotations

import re

_CONFIRM_RE = re.compile(
    (
        r"^\s*(yes|yes please|yep|yeah|go ahead|proceed|do it|run it|send it|"
        r"confirm|confirmed|looks good|ok|okay)\b"
    ),
    re.IGNORECASE,
)
_CANCEL_RE = re.compile(
    r"^\s*(no|no thanks|stop|cancel|don't|do not|never mind|abort)\b",
    re.IGNORECASE,
)


def is_explicit_confirmation(text: str) -> bool:
    """Return True when the user clearly confirms a pending action."""
    return bool(_CONFIRM_RE.search(text.strip()))


def is_explicit_rejection(text: str) -> bool:
    """Return True when the user clearly rejects a pending action."""
    return bool(_CANCEL_RE.search(text.strip()))
