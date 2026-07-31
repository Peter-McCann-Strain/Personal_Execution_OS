"""Tests for the coverage summary CLI helper."""

from __future__ import annotations

from pathlib import Path

from scripts.coverage_summary import (
    enforce_thresholds,
    main,
    parse_coverage_xml,
    render_summary,
)


def _write_xml(path: Path) -> None:
    path.write_text(
        """<?xml version="1.0" ?>
<coverage line-rate="0.9349" branch-rate="0.8575"
    lines-covered="9331" lines-valid="9981"
    branches-covered="1468" branches-valid="1712">
  <packages>
    <package name=".">
      <classes>
        <class filename="foo.py" line-rate="0.50" branch-rate="0.25" />
        <class filename="bar.py" line-rate="1.00" branch-rate="0.90" />
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )


def test_parse_coverage_xml(tmp_path: Path):
    xml_path = tmp_path / "coverage.xml"
    _write_xml(xml_path)

    summary = parse_coverage_xml(xml_path)

    assert summary.line_rate == 0.9349
    assert summary.branch_rate == 0.8575
    assert summary.lines_covered == 9331
    assert summary.files[0].filename == "foo.py"


def test_render_summary_orders_lowest_coverage_first(tmp_path: Path):
    xml_path = tmp_path / "coverage.xml"
    _write_xml(xml_path)

    summary = parse_coverage_xml(xml_path)
    output = render_summary(summary, min_line_rate=0.9, min_branch_rate=0.8, top=2)

    assert "Coverage Summary" in output
    assert "| `foo.py` | 50.00% | 25.00% |" in output
    assert output.index("foo.py") < output.index("bar.py")


def test_enforce_thresholds_reports_failures(tmp_path: Path):
    xml_path = tmp_path / "coverage.xml"
    _write_xml(xml_path)

    summary = parse_coverage_xml(xml_path)
    failures = enforce_thresholds(summary, min_line_rate=0.95, min_branch_rate=0.9)

    assert len(failures) == 2
    assert "Line coverage" in failures[0]
    assert "Branch coverage" in failures[1]


def test_main_returns_failure_when_thresholds_not_met(tmp_path: Path, capsys):
    xml_path = tmp_path / "coverage.xml"
    _write_xml(xml_path)

    exit_code = main(
        [
            "--xml",
            str(xml_path),
            "--min-line-rate",
            "0.95",
            "--min-branch-rate",
            "0.9",
            "--top",
            "1",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "foo.py" in captured.out
    assert "ERROR:" in captured.err


def test_main_returns_success_when_thresholds_met(tmp_path: Path):
    xml_path = tmp_path / "coverage.xml"
    _write_xml(xml_path)

    exit_code = main(
        [
            "--xml",
            str(xml_path),
            "--min-line-rate",
            "0.90",
            "--min-branch-rate",
            "0.80",
        ]
    )

    assert exit_code == 0
