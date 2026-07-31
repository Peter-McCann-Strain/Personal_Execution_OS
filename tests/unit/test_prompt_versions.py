"""Tests for prompt versioning across all agent modules."""

import re


class TestPromptVersionConstants:
    """Verify every agent prompt module has a PROMPT_VERSION constant."""

    def test_diary_has_version(self):
        from src.app.agents.prompts.diary import PROMPT_VERSION

        assert isinstance(PROMPT_VERSION, str)
        assert re.match(r"^v\d+", PROMPT_VERSION)

    def test_memory_has_version(self):
        from src.app.agents.prompts.memory import PROMPT_VERSION

        assert isinstance(PROMPT_VERSION, str)
        assert re.match(r"^v\d+", PROMPT_VERSION)

    def test_research_has_version(self):
        from src.app.agents.prompts.research import PROMPT_VERSION

        assert isinstance(PROMPT_VERSION, str)
        assert re.match(r"^v\d+", PROMPT_VERSION)

    def test_review_has_version(self):
        from src.app.agents.prompts.review import PROMPT_VERSION

        assert isinstance(PROMPT_VERSION, str)
        assert re.match(r"^v\d+", PROMPT_VERSION)

    def test_notification_has_version(self):
        from src.app.agents.prompts.notification import PROMPT_VERSION

        assert isinstance(PROMPT_VERSION, str)
        assert re.match(r"^v\d+", PROMPT_VERSION)

    def test_tools_has_version(self):
        from src.app.agents.prompts.tools import PROMPT_VERSION

        assert isinstance(PROMPT_VERSION, str)
        assert re.match(r"^v\d+", PROMPT_VERSION)

    def test_project_has_version(self):
        from src.app.agents.prompts.project import PROMPT_VERSION

        assert isinstance(PROMPT_VERSION, str)
        assert re.match(r"^v\d+", PROMPT_VERSION)

    def test_communications_has_version(self):
        from src.app.agents.prompts.communications import PROMPT_VERSION

        assert isinstance(PROMPT_VERSION, str)
        assert re.match(r"^v\d+", PROMPT_VERSION)

    def test_routing_has_version(self):
        from src.app.agents.prompts.routing import PROMPT_VERSION

        assert isinstance(PROMPT_VERSION, str)
        assert re.match(r"^v\d+", PROMPT_VERSION)


class TestPromptVersionsDict:
    """Verify the aggregated PROMPT_VERSIONS dictionary."""

    def test_contains_all_agents(self):
        from src.app.agents.prompts import PROMPT_VERSIONS

        expected_keys = {
            "communications",
            "diary",
            "memory",
            "notification",
            "project",
            "research",
            "review",
            "routing",
            "tools",
        }
        assert set(PROMPT_VERSIONS.keys()) == expected_keys

    def test_all_values_are_strings(self):
        from src.app.agents.prompts import PROMPT_VERSIONS

        for agent, version in PROMPT_VERSIONS.items():
            assert isinstance(version, str), f"{agent} version is not a string"

    def test_all_versions_match_pattern(self):
        from src.app.agents.prompts import PROMPT_VERSIONS

        for agent, version in PROMPT_VERSIONS.items():
            assert re.match(r"^v\d+", version), (
                f"{agent} version '{version}' doesn't match vN pattern"
            )

    def test_versions_are_present_and_well_formed(self):
        """Every registered agent must have a non-empty vN version string.

        (Previously this asserted `v1` for every agent — but routing has been
        bumped to v2 as prompts evolve, and that's expected.)
        """
        from src.app.agents.prompts import PROMPT_VERSIONS

        assert PROMPT_VERSIONS, "PROMPT_VERSIONS must not be empty"
        for agent, version in PROMPT_VERSIONS.items():
            assert re.match(r"^v\d+$", version), (
                f"{agent} version '{version}' doesn't match vN pattern"
            )
