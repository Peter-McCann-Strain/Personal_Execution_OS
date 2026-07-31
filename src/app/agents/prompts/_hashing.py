"""Prompt-content hashing helpers — separated from __init__.py to avoid
circular imports when prompt submodules call ``_compute_prompt_hash`` at
module load time.

Every prompt module declares::

    from src.app.agents.prompts._hashing import _compute_prompt_hash

    PROMPT_VERSION = "vN"
    PROMPT_CONTENT_HASH = _compute_prompt_hash(__name__)

The helper hashes the module's on-disk source, stripping the
``PROMPT_CONTENT_HASH = ...`` line so the hash isn't self-referential.
"""

from __future__ import annotations

import hashlib
import importlib
import re
import sys
from pathlib import Path

_HASH_ASSIGNMENT_PATTERN = re.compile(r"^PROMPT_CONTENT_HASH\s*=.*$", re.MULTILINE)


def _compute_prompt_hash(module_name: str) -> str:
    """Return a 16-char sha256 of the module's source, excluding the hash line.

    See ``src/app/agents/prompts/__init__.py`` for design rationale.
    """
    module = sys.modules.get(module_name)
    if module is None:
        module = importlib.import_module(module_name)
    file_path = getattr(module, "__file__", None)
    if not file_path:
        raise RuntimeError(f"Cannot compute prompt hash for {module_name}: no __file__ attribute")

    source = Path(file_path).read_text(encoding="utf-8")
    stripped = _HASH_ASSIGNMENT_PATTERN.sub("", source)
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:16]


__all__ = ["_compute_prompt_hash"]
