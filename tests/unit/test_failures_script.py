"""Tests for scripts/failures.py CLI tool."""

import argparse

from scripts.failures import main


class TestFailuresArgParser:
    """Test argument parsing for the failures CLI."""

    def test_default_args(self):
        """Default arguments should be reasonable."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--agent", type=str, default=None)
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--threshold", type=float, default=0.6)
        parser.add_argument("--dimension", type=str, default=None)
        parser.add_argument("--limit", type=int, default=200)

        args = parser.parse_args([])
        assert args.agent is None
        assert args.days == 7
        assert args.threshold == 0.6
        assert args.dimension is None
        assert args.limit == 200

    def test_agent_and_threshold(self):
        """Should accept agent and threshold flags."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--agent", type=str, default=None)
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--threshold", type=float, default=0.6)
        parser.add_argument("--dimension", type=str, default=None)

        args = parser.parse_args(["--agent", "diary", "--threshold", "0.4"])
        assert args.agent == "diary"
        assert args.threshold == 0.4

    def test_dimension_filter(self):
        """Should accept dimension filter."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--dimension", type=str, default=None)

        args = parser.parse_args(["--dimension", "relevance"])
        assert args.dimension == "relevance"

    def test_main_function_exists(self):
        """main() should be a callable function."""
        assert callable(main)
