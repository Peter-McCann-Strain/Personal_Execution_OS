"""Rubric loader — parses binary-check specialist rubrics from markdown.

Each agent rubric in ``data/evaluation/rubrics/<agent>.md`` defines one or more
"Specialist Dimension" sections. Each section contains a list of yes/no
sub-checks (``- Q1: ... Y/N``). This loader turns those markdown sections into
a structured form the auto-judge can emit, score, and persist.

The universal rubric remains on a 5-point Likert scale and is not parsed here.

Binary rubrics were adopted after April 2026 evidence (RULERS,
arXiv:2601.08654) that yes/no prompts yield the highest inter-rater
reliability for LLM judges; wide Likert scales cause central-tendency bias.
"""

from __future__ import annotations

import re
from functools import cache
from itertools import pairwise

from pydantic import BaseModel, Field

from src.app.core.evaluation_registry import (
    RUBRICS_DIR,
    rubric_path_for_specialist,
)
from src.app.domain.models import Specialist

_DIMENSION_HEADING = re.compile(
    r"^##\s+Specialist Dimension\s+\d+\s*:\s*(?P<name>.+?)\s*$",
    re.MULTILINE,
)
_SUB_CHECK_LINE = re.compile(
    r"^\s*[-*]\s+(?P<id>Q\d+)\s*:\s*(?P<text>.+?)\s*(?:Y/N|\(Y/N\))\s*$",
    re.IGNORECASE,
)
_SECTION_BREAK = re.compile(r"^##\s+", re.MULTILINE)


def _slug(name: str) -> str:
    """Turn a dimension name into a stable lowercase_key (e.g. "Voice Match" -> "voice_match")."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return cleaned or "dimension"


class BinaryCheck(BaseModel):
    """One yes/no sub-check within a dimension."""

    id: str = Field(description="Local identifier such as 'Q1' or 'Q2'.")
    question: str = Field(description="The yes/no question itself, without trailing 'Y/N'.")


class RubricDimension(BaseModel):
    """A specialist dimension composed of binary sub-checks."""

    name: str = Field(description="Human-readable dimension name (e.g. 'Emotional Attunement').")
    key: str = Field(description="Stable snake_case key derived from the name.")
    checks: list[BinaryCheck] = Field(
        description="Ordered list of binary sub-checks that make up the dimension.",
    )

    @property
    def max_score(self) -> int:
        """Maximum achievable raw score for the dimension (one per Y)."""
        return len(self.checks)

    def score(self, answers: dict[str, bool]) -> int:
        """Sum of True answers keyed by check id (case-insensitive)."""
        norm = {k.upper(): bool(v) for k, v in answers.items()}
        return sum(1 for check in self.checks if norm.get(check.id.upper()) is True)

    def normalized_score(self, answers: dict[str, bool]) -> float:
        """Return the dimension score scaled to 0.0-1.0 for legacy consumers."""
        if not self.checks:
            return 0.0
        return self.score(answers) / float(self.max_score)


class SpecialistRubric(BaseModel):
    """Parsed binary rubric for one specialist."""

    specialist: Specialist
    version: str = Field(description="Rubric version extracted from the H1 heading.")
    path: str = Field(description="Source markdown path.")
    dimensions: list[RubricDimension] = Field(
        description="Ordered specialist dimensions.",
    )

    def score_dimensions(
        self,
        answers_by_dimension: dict[str, dict[str, bool]],
    ) -> dict[str, int]:
        """Return integer dimension scores keyed by dimension key."""
        out: dict[str, int] = {}
        for dim in self.dimensions:
            dim_answers = answers_by_dimension.get(dim.key, {})
            out[dim.key] = dim.score(dim_answers)
        return out


def _parse_version(text: str) -> str:
    """Extract ``v2`` etc from the first H1 heading."""
    first_line = text.lstrip().splitlines()[0] if text.strip() else ""
    match = re.search(r"v\d+", first_line)
    return match.group(0) if match else "v1"


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown by ``## `` headings and return (heading_line, body) pairs."""
    positions = [m.start() for m in _SECTION_BREAK.finditer(text)]
    positions.append(len(text))
    sections: list[tuple[str, str]] = []
    for start, end in pairwise(positions):
        block = text[start:end]
        nl = block.find("\n")
        if nl == -1:
            heading = block.rstrip()
            body = ""
        else:
            heading = block[:nl].rstrip()
            body = block[nl + 1 :]
        sections.append((heading, body))
    return sections


def parse_rubric_markdown(markdown: str, *, specialist: Specialist, path: str) -> SpecialistRubric:
    """Parse a binary rubric from its markdown source."""
    version = _parse_version(markdown)
    dimensions: list[RubricDimension] = []

    for heading, body in _split_sections(markdown):
        match = _DIMENSION_HEADING.match(heading)
        if not match:
            continue
        name = match.group("name").strip()

        # Strip any sub-section ("### ...") inside the body — only top-level list items count.
        body_until_subheading = re.split(r"^###\s+", body, maxsplit=1, flags=re.MULTILINE)[0]

        checks: list[BinaryCheck] = []
        for line in body_until_subheading.splitlines():
            sub = _SUB_CHECK_LINE.match(line)
            if not sub:
                continue
            checks.append(
                BinaryCheck(
                    id=sub.group("id").upper(),
                    question=sub.group("text").strip().rstrip("?").strip() + "?",
                )
            )

        if not checks:
            msg = (
                f"Rubric for {specialist.value} at {path}: dimension '{name}' "
                "has no binary sub-checks. Expected lines like '- Q1: ... Y/N'."
            )
            raise ValueError(msg)
        if not 3 <= len(checks) <= 5:
            msg = (
                f"Rubric for {specialist.value} at {path}: dimension '{name}' "
                f"must have 3-5 binary sub-checks, found {len(checks)}."
            )
            raise ValueError(msg)

        dimensions.append(
            RubricDimension(name=name, key=_slug(name), checks=checks),
        )

    if not dimensions:
        msg = f"Rubric for {specialist.value} at {path} has no Specialist Dimension sections."
        raise ValueError(msg)

    return SpecialistRubric(
        specialist=specialist,
        version=version,
        path=path,
        dimensions=dimensions,
    )


@cache
def load_specialist_rubric(specialist: Specialist | str) -> SpecialistRubric:
    """Load and parse the binary rubric for a specialist."""
    resolved = Specialist(specialist)
    path = rubric_path_for_specialist(resolved)
    if not path.is_file():
        msg = f"Rubric file missing for {resolved.value}: {path}"
        raise FileNotFoundError(msg)
    markdown = path.read_text(encoding="utf-8")
    return parse_rubric_markdown(markdown, specialist=resolved, path=path.as_posix())


def load_all_specialist_rubrics() -> dict[Specialist, SpecialistRubric]:
    """Load every specialist rubric available in the rubrics directory (universal excluded)."""
    result: dict[Specialist, SpecialistRubric] = {}
    for specialist in Specialist:
        try:
            rubric_path = rubric_path_for_specialist(specialist)
        except KeyError:
            continue
        if not rubric_path.is_file():
            continue
        result[specialist] = load_specialist_rubric(specialist)
    return result


def rubric_prompt_snippet(rubric: SpecialistRubric) -> str:
    """Render the binary sub-checks as a prompt-ready block for the auto-judge."""
    lines: list[str] = []
    for dim in rubric.dimensions:
        lines.append(f"### {dim.name} (key: {dim.key})")
        for check in dim.checks:
            lines.append(f"- {check.id}: {check.question}")
        lines.append("")
    return "\n".join(lines).rstrip()


__all__ = [
    "RUBRICS_DIR",
    "BinaryCheck",
    "RubricDimension",
    "SpecialistRubric",
    "load_all_specialist_rubrics",
    "load_specialist_rubric",
    "parse_rubric_markdown",
    "rubric_prompt_snippet",
]
