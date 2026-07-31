"""Tests for evaluation rubric files — verify all rubrics exist and are well-formed."""

from pathlib import Path

RUBRICS_DIR = Path("data/evaluation/rubrics")

_EXPECTED_RUBRICS = [
    "universal.md",
    "communications.md",
    "diary.md",
    "memory.md",
    "plan_day.md",
    "project.md",
    "research.md",
    "review.md",
    "notification.md",
    "save.md",
    "socratic.md",
    "tools.md",
]


class TestRubricFilesExist:
    """Verify all expected rubric files exist."""

    def test_rubrics_directory_exists(self):
        assert RUBRICS_DIR.is_dir(), f"Rubrics directory not found: {RUBRICS_DIR}"

    def test_universal_rubric_exists(self):
        assert (RUBRICS_DIR / "universal.md").is_file()

    def test_all_agent_rubrics_exist(self):
        for rubric in _EXPECTED_RUBRICS:
            path = RUBRICS_DIR / rubric
            assert path.is_file(), f"Missing rubric: {rubric}"

    def test_rubric_count(self):
        """Should have exactly 12 rubric files (1 universal + 11 specialists)."""
        md_files = list(RUBRICS_DIR.glob("*.md"))
        assert len(md_files) == 12


class TestRubricContent:
    """Verify rubric files have minimum required content."""

    def test_universal_has_four_dimensions(self):
        content = (RUBRICS_DIR / "universal.md").read_text()
        for dimension in ("Relevance", "Actionability", "Tone", "Conciseness"):
            assert dimension in content, f"Missing dimension: {dimension}"

    def test_universal_has_score_anchors(self):
        content = (RUBRICS_DIR / "universal.md").read_text()
        # Each dimension should have 5-point scale anchors
        for score in ("| 5 |", "| 4 |", "| 3 |", "| 2 |", "| 1 |"):
            assert score in content, f"Missing score anchor: {score}"

    def test_agent_rubrics_reference_universal(self):
        """Each agent rubric should reference the universal dimensions."""
        for rubric in _EXPECTED_RUBRICS:
            if rubric == "universal.md":
                continue
            content = (RUBRICS_DIR / rubric).read_text()
            assert "universal.md" in content, f"{rubric} should reference universal.md"

    def test_agent_rubrics_have_specialist_dimensions(self):
        """Each agent rubric should define at least one specialist dimension."""
        for rubric in _EXPECTED_RUBRICS:
            if rubric == "universal.md":
                continue
            content = (RUBRICS_DIR / rubric).read_text()
            assert "Specialist Dimension" in content, f"{rubric} should have specialist dimensions"

    def test_agent_rubrics_have_anti_patterns(self):
        """Each agent rubric should list anti-patterns."""
        for rubric in _EXPECTED_RUBRICS:
            if rubric == "universal.md":
                continue
            content = (RUBRICS_DIR / rubric).read_text()
            assert "Anti-Pattern" in content, f"{rubric} should list anti-patterns"

    def test_rubrics_are_non_trivial(self):
        """Each rubric should have substantial content (>500 chars)."""
        for rubric in _EXPECTED_RUBRICS:
            content = (RUBRICS_DIR / rubric).read_text()
            assert len(content) > 500, f"{rubric} is too short ({len(content)} chars)"
