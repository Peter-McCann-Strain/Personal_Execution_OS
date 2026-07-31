"""Small built-in filesystem MCP server for production-safe file access."""

import argparse
from fnmatch import fnmatch
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Filesystem")
_ROOT: Path | None = None


def _root() -> Path:
    if _ROOT is None:
        raise RuntimeError("Filesystem MCP root is not configured.")
    return _ROOT


def _resolve_relative_path(path: str) -> Path:
    root = _root()
    candidate = (root / path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Path is outside the allowed root directory.")
    return candidate


@mcp.tool()
def read_file(path: str) -> str:
    """Read a UTF-8 text file under the configured root directory."""
    resolved = _resolve_relative_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not resolved.is_file():
        raise IsADirectoryError(f"Path is not a file: {path}")
    return resolved.read_text(encoding="utf-8")


@mcp.tool()
def list_files(path: str = ".", pattern: str = "*", recursive: bool = False) -> list[str]:
    """List files under the configured root directory."""
    resolved = _resolve_relative_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Directory not found: {path}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")

    iterator = resolved.rglob(pattern) if recursive else resolved.glob(pattern)
    root = _root()
    return sorted(str(item.relative_to(root)) for item in iterator if item.is_file())


@mcp.tool()
def search_files(
    query: str,
    path: str = ".",
    pattern: str = "*.md",
    max_results: int = 20,
) -> list[dict[str, str | int]]:
    """Search text files under the configured root directory."""
    resolved = _resolve_relative_path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Directory not found: {path}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {path}")

    results: list[dict[str, str | int]] = []
    root = _root()
    lowered_query = query.casefold()

    for file_path in sorted(resolved.rglob("*")):
        if len(results) >= max_results:
            break
        if not file_path.is_file():
            continue
        if not fnmatch(file_path.name, pattern):
            continue

        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(lines, start=1):
            if lowered_query not in line.casefold():
                continue
            results.append(
                {
                    "path": str(file_path.relative_to(root)),
                    "line_number": line_number,
                    "line": line.strip(),
                }
            )
            if len(results) >= max_results:
                break

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Filesystem MCP server")
    parser.add_argument("root", help="Root directory that tools may access")
    args = parser.parse_args()

    global _ROOT
    _ROOT = Path(args.root).resolve()
    _ROOT.mkdir(parents=True, exist_ok=True)

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
