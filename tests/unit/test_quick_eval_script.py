"""Tests for scripts/quick_eval.py CLI tool."""

import argparse

from scripts.quick_eval import main


class TestQuickEvalArgParser:
    """Test argument parsing for the quick_eval CLI."""

    def test_default_args(self):
        """Default arguments should be reasonable."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--agent", type=str, default=None)
        parser.add_argument("--samples", type=int, default=20)
        parser.add_argument("--days", type=int, default=14)
        parser.add_argument("--max-score", type=float, default=None)

        args = parser.parse_args([])
        assert args.agent is None
        assert args.samples == 20
        assert args.days == 14
        assert args.max_score is None

    def test_agent_and_samples(self):
        """Should accept agent and samples flags."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--agent", type=str, default=None)
        parser.add_argument("--samples", type=int, default=20)
        parser.add_argument("--max-score", type=float, default=None)

        args = parser.parse_args(["--agent", "diary", "--samples", "10", "--max-score", "0.7"])
        assert args.agent == "diary"
        assert args.samples == 10
        assert args.max_score == 0.7

    def test_main_function_exists(self):
        """main() should be a callable function."""
        assert callable(main)
