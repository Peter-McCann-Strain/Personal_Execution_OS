"""Tests for evaluation assets that are intentionally packaged in source."""

from pathlib import Path

_EVAL_ROOT = Path("data/evaluation")

_EXPECTED_DIRS = [
    "rubrics",
    "datasets",
    "baselines",
]


class TestEvalDirectoryStructure:
    """Verify the evaluation data directory structure exists."""

    def test_eval_root_exists(self):
        assert _EVAL_ROOT.is_dir(), f"Evaluation root not found: {_EVAL_ROOT}"

    def test_all_subdirs_exist(self):
        for subdir in _EXPECTED_DIRS:
            path = _EVAL_ROOT / subdir
            assert path.is_dir(), f"Missing directory: {path}"

    def test_directory_count(self):
        """Runtime output directories are not required in the source tree."""
        source_dirs = {d.name for d in _EVAL_ROOT.iterdir() if d.is_dir()}
        assert set(_EXPECTED_DIRS).issubset(source_dirs)
