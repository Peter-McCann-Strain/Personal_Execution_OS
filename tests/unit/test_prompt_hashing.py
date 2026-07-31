"""Tests for prompt-content hash validation (P4.7)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.agents.prompts import (
    PROMPT_CONTENT_HASHES,
    PROMPT_VERSIONS,
    validate_prompt_hashes,
)
from src.app.agents.prompts._hashing import _compute_prompt_hash

# ---------------------------------------------------------------------------
# _compute_prompt_hash: determinism / drift detection
# ---------------------------------------------------------------------------


def test_compute_prompt_hash_is_deterministic_for_same_module() -> None:
    h1 = _compute_prompt_hash("src.app.agents.prompts.diary")
    h2 = _compute_prompt_hash("src.app.agents.prompts.diary")
    assert h1 == h2
    assert len(h1) == 16
    # sha256 hex prefix → only hex chars.
    assert all(c in "0123456789abcdef" for c in h1)


def test_compute_prompt_hash_differs_across_modules() -> None:
    diary_hash = _compute_prompt_hash("src.app.agents.prompts.diary")
    memory_hash = _compute_prompt_hash("src.app.agents.prompts.memory")
    assert diary_hash != memory_hash


def test_compute_prompt_hash_strips_self_reference(tmp_path: Path, monkeypatch) -> None:
    """A module with a *different* PROMPT_CONTENT_HASH literal should produce
    the same hash as the original — the self-referential line is stripped
    before hashing.
    """
    import sys
    import types

    # Build a fake module file with two variants that differ only in the
    # PROMPT_CONTENT_HASH literal.
    base_source = (
        "from src.app.agents.prompts._hashing import _compute_prompt_hash\n"
        '\nPROMPT_VERSION = "v1"\nPROMPT_CONTENT_HASH = "{placeholder}"\n'
        '\nPROMPT_TEXT = "hello world"\n'
    )

    mod1_path = tmp_path / "fake_prompt_a.py"
    mod1_path.write_text(base_source.format(placeholder="aaaaaaaaaaaaaaaa"))
    mod2_path = tmp_path / "fake_prompt_b.py"
    mod2_path.write_text(base_source.format(placeholder="bbbbbbbbbbbbbbbb"))

    # Fake two modules in sys.modules that point to the two files.
    mod_a = types.ModuleType("fake_prompt_a")
    mod_a.__file__ = str(mod1_path)
    mod_b = types.ModuleType("fake_prompt_b")
    mod_b.__file__ = str(mod2_path)
    sys.modules["fake_prompt_a"] = mod_a
    sys.modules["fake_prompt_b"] = mod_b
    try:
        h_a = _compute_prompt_hash("fake_prompt_a")
        h_b = _compute_prompt_hash("fake_prompt_b")
        # Same content except the hash-line → same hash.
        assert h_a == h_b
    finally:
        del sys.modules["fake_prompt_a"]
        del sys.modules["fake_prompt_b"]


def test_compute_prompt_hash_changes_when_prompt_text_changes(
    tmp_path: Path,
) -> None:
    """If PROMPT_TEXT (or any non-hash content) changes, the hash must change."""
    import sys
    import types

    mod_a_src = (
        'PROMPT_VERSION = "v1"\nPROMPT_CONTENT_HASH = "x"\nPROMPT_TEXT = "original prompt text"\n'
    )
    mod_b_src = (
        'PROMPT_VERSION = "v1"\nPROMPT_CONTENT_HASH = "x"\nPROMPT_TEXT = "MUTATED prompt text"\n'
    )
    (tmp_path / "mod_a.py").write_text(mod_a_src)
    (tmp_path / "mod_b.py").write_text(mod_b_src)

    mod_a = types.ModuleType("mod_a")
    mod_a.__file__ = str(tmp_path / "mod_a.py")
    mod_b = types.ModuleType("mod_b")
    mod_b.__file__ = str(tmp_path / "mod_b.py")
    sys.modules["mod_a"] = mod_a
    sys.modules["mod_b"] = mod_b
    try:
        h_a = _compute_prompt_hash("mod_a")
        h_b = _compute_prompt_hash("mod_b")
        assert h_a != h_b
    finally:
        del sys.modules["mod_a"]
        del sys.modules["mod_b"]


def test_compute_prompt_hash_stable_when_only_hash_literal_changes(
    tmp_path: Path,
) -> None:
    """Redundant but critical: the hash-line is stripped, so flipping only
    its literal value must not change the computed hash.
    """
    import sys
    import types

    src_a = 'X = 1\nPROMPT_CONTENT_HASH = "deadbeef"\nY = 2\n'
    src_b = 'X = 1\nPROMPT_CONTENT_HASH = "cafef00d"\nY = 2\n'
    (tmp_path / "stable_a.py").write_text(src_a)
    (tmp_path / "stable_b.py").write_text(src_b)

    for name, fname in (("stable_a", "stable_a.py"), ("stable_b", "stable_b.py")):
        mod = types.ModuleType(name)
        mod.__file__ = str(tmp_path / fname)
        sys.modules[name] = mod
    try:
        assert _compute_prompt_hash("stable_a") == _compute_prompt_hash("stable_b")
    finally:
        del sys.modules["stable_a"]
        del sys.modules["stable_b"]


# ---------------------------------------------------------------------------
# Hash map completeness
# ---------------------------------------------------------------------------


def test_prompt_content_hashes_registered_for_every_agent() -> None:
    # PROMPT_VERSIONS is the source of truth for "which agents exist".
    assert set(PROMPT_CONTENT_HASHES.keys()) == set(PROMPT_VERSIONS.keys())


def test_every_live_hash_is_16_char_hex() -> None:
    for agent, h in PROMPT_CONTENT_HASHES.items():
        assert len(h) == 16, f"{agent} hash length != 16"
        assert all(c in "0123456789abcdef" for c in h), f"{agent} non-hex hash"


# ---------------------------------------------------------------------------
# validate_prompt_hashes behaviour
# ---------------------------------------------------------------------------


def test_validate_prompt_hashes_empty_expected_is_noop() -> None:
    assert validate_prompt_hashes({}) == []
    # strict=True doesn't fire when expected is empty.
    assert validate_prompt_hashes({}, strict=True) == []


def test_validate_prompt_hashes_all_matching_returns_empty() -> None:
    # Pass in the live hashes as "expected" → zero drift.
    drift = validate_prompt_hashes(PROMPT_CONTENT_HASHES.copy())
    assert drift == []


def test_validate_prompt_hashes_reports_drift_per_agent() -> None:
    # Mutate a single expected hash — that agent should be reported drifted.
    expected = PROMPT_CONTENT_HASHES.copy()
    expected["diary"] = "0" * 16
    drift = validate_prompt_hashes(expected)
    assert len(drift) == 1
    assert "diary" in drift[0]
    assert "prompt content changed" in drift[0]


def test_validate_prompt_hashes_strict_raises_on_drift() -> None:
    expected = PROMPT_CONTENT_HASHES.copy()
    expected["diary"] = "0" * 16
    with pytest.raises(RuntimeError, match="drift detected"):
        validate_prompt_hashes(expected, strict=True)


def test_validate_prompt_hashes_flags_unknown_agents() -> None:
    expected = {"nonexistent_agent": "a" * 16}
    drift = validate_prompt_hashes(expected)
    assert len(drift) == 1
    assert "no live hash registered" in drift[0]


# ---------------------------------------------------------------------------
# Preflight integration
# ---------------------------------------------------------------------------


def test_preflight_skips_when_expected_hashes_empty() -> None:
    from src.app.core.preflight import _check_prompt_hashes

    settings = SimpleNamespace(expected_prompt_hashes={})
    check = _check_prompt_hashes(settings)
    assert check.status == "skipped"
    assert check.required is False


def test_preflight_ok_when_expected_matches_live() -> None:
    from src.app.core.preflight import _check_prompt_hashes

    settings = SimpleNamespace(expected_prompt_hashes=PROMPT_CONTENT_HASHES.copy())
    check = _check_prompt_hashes(settings)
    assert check.status == "ok"


def test_preflight_fails_on_drift() -> None:
    from src.app.core.preflight import _check_prompt_hashes

    expected = PROMPT_CONTENT_HASHES.copy()
    expected["diary"] = "deadbeefdeadbeef"
    settings = SimpleNamespace(expected_prompt_hashes=expected)
    check = _check_prompt_hashes(settings)
    assert check.status == "fail"
    assert check.required is True
    assert "drift" in check.details
    assert any("diary" in msg for msg in check.details["drift"])
