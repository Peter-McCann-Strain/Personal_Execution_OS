from pathlib import Path

from scripts.check_docs import REQUIRED_DOCUMENTS, check_documentation


def _write_required_docs(root: Path) -> None:
    for relative in REQUIRED_DOCUMENTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")


def test_check_documentation_accepts_valid_links_anchors_and_mermaid(tmp_path: Path) -> None:
    _write_required_docs(tmp_path)
    source = tmp_path / "src" / "app"
    source.mkdir(parents=True)
    (source / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "\n".join(
            [
                "# Project",
                "",
                "[Architecture](docs/ARCHITECTURE.md#system-view)",
                "",
                "`src/app/main.py:create_app`",
                "",
                "```mermaid",
                "flowchart LR",
                '    A["one"] --> B["two"]',
                "```",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "docs" / "ARCHITECTURE.md").write_text(
        "# Architecture\n\n## System view\n", encoding="utf-8"
    )

    assert check_documentation(tmp_path) == []


def test_check_documentation_reports_broken_contracts(tmp_path: Path) -> None:
    _write_required_docs(tmp_path)
    (tmp_path / "README.md").write_text(
        "\n".join(
            [
                "# Project",
                "",
                "[Missing](docs/ARCHITECTURE.md#absent)",
                "",
                "`src/app/missing.py:run`",
                "",
                "```mermaid",
                "```",
                "",
                "```sh",
                "echo unfinished",
            ]
        ),
        encoding="utf-8",
    )

    messages = [problem.message for problem in check_documentation(tmp_path)]

    assert "Markdown anchor does not exist: docs/ARCHITECTURE.md#absent" in messages
    assert "referenced repository path does not exist: src/app/missing.py" in messages
    assert "Mermaid code fence must not be empty" in messages
    assert "unclosed Markdown code fence" in messages


def test_check_documentation_allows_generated_private_identity_path(tmp_path: Path) -> None:
    _write_required_docs(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Project\n\nCopy `config/IDENTITY.local.md` from the tracked template.\n",
        encoding="utf-8",
    )

    assert check_documentation(tmp_path) == []
