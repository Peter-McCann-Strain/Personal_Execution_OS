# Project Rubric v2

This rubric extends [universal.md](universal.md). It measures whether the
project specialist plans realistically, sequences work coherently, and respects
dependencies instead of producing generic planning language. Universal
dimensions remain on the 5-point Likert scale; specialist dimensions below use
binary yes/no sub-checks.

## Binary Scoring

Each sub-check (Q1, Q2, ...) is scored Y (1) or N (0). A dimension's score is
the sum of Ys across its sub-checks. Thresholds for pass/fail gates are
configured in settings. Binary rubrics were adopted after April 2026 evidence
(RULERS, arXiv:2601.08654) that yes/no prompts yield the highest inter-rater
reliability for LLM judges.

## Specialist Dimension 1: Feasibility

- Q1: Does the plan respect the stated time horizon and resource constraints? Y/N
- Q2: Are the individual tasks specified concretely enough to execute? Y/N
- Q3: Does the plan account for known blockers or external dependencies? Y/N
- Q4: Does the plan avoid recommending work that conflicts with stated constraints? Y/N

## Specialist Dimension 2: Prioritization Quality

- Q1: Are tasks ordered so dependencies resolve before dependents? Y/N
- Q2: Is the critical path identified (not every task framed as equally important)? Y/N
- Q3: Is there a concrete, executable next step at the top? Y/N
- Q4: Are integration risks and hand-offs surfaced rather than hidden? Y/N

## Anti-Pattern Checklist

- Anti-Pattern: treating all tasks as equally important.
- Anti-Pattern: skipping dependencies and integration risks.
- Anti-Pattern: recommending work that conflicts with known constraints.
- Anti-Pattern: delivering abstract planning language without an executable next step.
