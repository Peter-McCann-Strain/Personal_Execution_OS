"""Tests for scripts/evaluate.py CLI tool."""

import argparse

from scripts.evaluate import main


class TestEvaluateArgParser:
    """Test argument parsing for the evaluate CLI."""

    def test_export_subcommand_defaults(self):
        """Export subcommand should have correct defaults."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        export_parser = subparsers.add_parser("export")
        export_parser.add_argument("--agent", type=str, default=None)
        export_parser.add_argument("--last", type=int, default=50)
        export_parser.add_argument("--days", type=int, default=None)

        args = parser.parse_args(["export"])
        assert args.command == "export"
        assert args.agent is None
        assert args.last == 50
        assert args.days is None

    def test_export_with_agent_filter(self):
        """Export subcommand should accept --agent flag."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        export_parser = subparsers.add_parser("export")
        export_parser.add_argument("--agent", type=str, default=None)
        export_parser.add_argument("--last", type=int, default=50)

        args = parser.parse_args(["export", "--agent", "diary", "--last", "100"])
        assert args.agent == "diary"
        assert args.last == 100

    def test_store_subcommand_requires_file(self):
        """Store subcommand should require --file flag."""
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")

        store_parser = subparsers.add_parser("store")
        store_parser.add_argument("--file", type=str, required=True)

        args = parser.parse_args(["store", "--file", "path/to/scores.json"])
        assert args.command == "store"
        assert args.file == "path/to/scores.json"

    def test_main_function_exists(self):
        """main() should be a callable function."""
        assert callable(main)
