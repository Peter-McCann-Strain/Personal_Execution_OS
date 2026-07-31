# Review Rubric v2

This rubric extends [universal.md](universal.md). It evaluates whether the
review specialist surfaced the right problems, prioritized them well, and kept
the focus on risk rather than fluff. Universal dimensions remain on the
5-point Likert scale; specialist dimensions below use binary yes/no sub-checks.

## Binary Scoring

Each sub-check (Q1, Q2, ...) is scored Y (1) or N (0). A dimension's score is
the sum of Ys across its sub-checks. Thresholds for pass/fail gates are
configured in settings. Binary rubrics were adopted after April 2026 evidence
(RULERS, arXiv:2601.08654) that yes/no prompts yield the highest inter-rater
reliability for LLM judges.

## Specialist Dimension 1: Issue Validity

- Q1: Is each finding tied to concrete evidence (specific behavior, diff, or log)? Y/N
- Q2: Does each finding describe a plausible failure path rather than a hypothetical? Y/N
- Q3: Does each finding explain *why* it matters (risk / impact)? Y/N
- Q4: Does the review avoid obviously wrong or misleading findings? Y/N

## Specialist Dimension 2: Prioritization Quality

- Q1: Are findings ordered with the most severe or highest-impact first? Y/N
- Q2: Do severity labels match the real risk (no padding, no deflation)? Y/N
- Q3: Are style nits kept separate from functional breakage? Y/N
- Q4: Is the critical path or top risk called out unambiguously? Y/N

## Anti-Pattern Checklist

- Anti-Pattern: praising style while skipping functional risk.
- Anti-Pattern: reporting hypothetical issues without a plausible failure path.
- Anti-Pattern: burying the most severe issue below secondary comments.
- Anti-Pattern: giving line-level advice without explaining why it matters.
