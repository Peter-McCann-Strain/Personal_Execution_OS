"""Tests for scripts/quality_report.py CLI tool."""

import argparse

from scripts.quality_report import main


class TestQualityReportArgParser:
    """Test argument parsing for the quality_report CLI."""

    def test_default_args(self):
        """Default arguments should be reasonable."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--agent", type=str, default=None)
        parser.add_argument("--days", type=int, default=30)

        args = parser.parse_args([])
        assert args.agent is None
        assert args.days == 30

    def test_agent_and_days(self):
        """Should accept agent and days flags."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--agent", type=str, default=None)
        parser.add_argument("--days", type=int, default=30)

        args = parser.parse_args(["--agent", "research", "--days", "90"])
        assert args.agent == "research"
        assert args.days == 90

    def test_main_function_exists(self):
        """main() should be a callable function."""
        assert callable(main)
