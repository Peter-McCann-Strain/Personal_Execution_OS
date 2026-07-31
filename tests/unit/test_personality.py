"""Tests for personality loader — SOUL.md + IDENTITY.md loading and caching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.app.core.personality import clear_cache, get_personality_prefix, load_personality


@pytest.fixture(autouse=True)
def _clear_personality_cache():
    """Ensure each test starts with a fresh cache."""
    clear_cache()
    yield
    clear_cache()


class TestLoadPersonality:
    def test_loads_both_files(self, tmp_path: Path):
        """When both SOUL.md and IDENTITY.md exist, combines them."""
        soul = tmp_path / "SOUL.md"
        identity = tmp_path / "IDENTITY.md"
        soul.write_text("You are helpful.", encoding="utf-8")
        identity.write_text("User: Alex", encoding="utf-8")

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            result = load_personality()

        assert "You are helpful." in result
        assert "User: Alex" in result
        # Both parts joined with double newline
        assert result == "You are helpful.\n\nUser: Alex"

    def test_loads_soul_only(self, tmp_path: Path):
        """When only SOUL.md exists, returns its content."""
        soul = tmp_path / "SOUL.md"
        identity = tmp_path / "IDENTITY.md"  # does not exist
        soul.write_text("Soul content", encoding="utf-8")

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            result = load_personality()

        assert result == "Soul content"

    def test_loads_identity_only(self, tmp_path: Path):
        """When only IDENTITY.md exists, returns its content."""
        soul = tmp_path / "SOUL.md"  # does not exist
        identity = tmp_path / "IDENTITY.md"
        identity.write_text("Identity content", encoding="utf-8")

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            result = load_personality()

        assert result == "Identity content"

    def test_returns_empty_when_no_files(self, tmp_path: Path):
        """When neither file exists, returns empty string."""
        soul = tmp_path / "SOUL.md"
        identity = tmp_path / "IDENTITY.md"

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            result = load_personality()

        assert result == ""

    def test_strips_whitespace(self, tmp_path: Path):
        """Whitespace around file content is stripped."""
        soul = tmp_path / "SOUL.md"
        soul.write_text("  \n  Soul content  \n  ", encoding="utf-8")
        identity = tmp_path / "IDENTITY.md"

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            result = load_personality()

        assert result == "Soul content"


class TestCaching:
    def test_caches_result(self, tmp_path: Path):
        """Second call returns cached result without re-reading files."""
        soul = tmp_path / "SOUL.md"
        identity = tmp_path / "IDENTITY.md"
        soul.write_text("Cached soul", encoding="utf-8")

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            first = load_personality()
            # Modify the file — cached value should persist
            soul.write_text("Modified soul", encoding="utf-8")
            second = load_personality()

        assert first == second
        assert second == "Cached soul"

    def test_clear_cache_allows_reload(self, tmp_path: Path):
        """After clear_cache(), the next load re-reads files."""
        soul = tmp_path / "SOUL.md"
        identity = tmp_path / "IDENTITY.md"
        soul.write_text("Original", encoding="utf-8")

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            first = load_personality()
            soul.write_text("Updated", encoding="utf-8")
            clear_cache()
            second = load_personality()

        assert first == "Original"
        assert second == "Updated"


class TestGetPersonalityPrefix:
    def test_wraps_in_xml_tags(self, tmp_path: Path):
        """Personality content is wrapped in <personality> tags."""
        soul = tmp_path / "SOUL.md"
        identity = tmp_path / "IDENTITY.md"
        soul.write_text("Be direct.", encoding="utf-8")

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            prefix = get_personality_prefix()

        assert prefix.startswith("<personality>\n")
        assert "Be direct." in prefix
        assert prefix.endswith("</personality>\n\n")

    def test_returns_empty_when_no_personality(self, tmp_path: Path):
        """When no personality files exist, returns empty string."""
        soul = tmp_path / "SOUL.md"
        identity = tmp_path / "IDENTITY.md"

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            prefix = get_personality_prefix()

        assert prefix == ""

    def test_includes_both_files(self, tmp_path: Path):
        """Prefix includes content from both SOUL and IDENTITY."""
        soul = tmp_path / "SOUL.md"
        identity = tmp_path / "IDENTITY.md"
        soul.write_text("Soul rules", encoding="utf-8")
        identity.write_text("Identity info", encoding="utf-8")

        with (
            patch("src.app.core.personality._SOUL_PATH", soul),
            patch("src.app.core.personality._IDENTITY_PATH", identity),
        ):
            prefix = get_personality_prefix()

        assert "Soul rules" in prefix
        assert "Identity info" in prefix
