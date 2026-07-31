# Memory Rubric v2

This rubric extends [universal.md](universal.md). Use it to score whether the
memory specialist retrieves, filters, and synthesizes prior context faithfully.
Universal dimensions remain on the 5-point Likert scale; specialist dimensions
below use binary yes/no sub-checks.

## Binary Scoring

Each sub-check (Q1, Q2, ...) is scored Y (1) or N (0). A dimension's score is
the sum of Ys across its sub-checks. Thresholds for pass/fail gates are
configured in settings. Binary rubrics were adopted after April 2026 evidence
(RULERS, arXiv:2601.08654) that yes/no prompts yield the highest inter-rater
reliability for LLM judges.

## Specialist Dimension 1: Retrieval Fidelity (Grounding)

- Q1: Does every claim trace back to a retrieved source (no unsupported assertions)? Y/N
- Q2: When sources conflict, is the conflict surfaced rather than silently flattened? Y/N
- Q3: Is the answer decisive rather than hedging when the evidence supports it? Y/N
- Q4: Does the stated confidence match source count (e.g. >=2 sources when confidence > 0.9)? Y/N

## Specialist Dimension 2: Recall Usefulness

- Q1: Does the response return the memories most relevant to the current request? Y/N
- Q2: Are retrieved items ranked so high-value content appears first? Y/N
- Q3: Does the answer explain why each retrieved item matters to the current question? Y/N
- Q4: Does the response avoid letting a weak match dominate the conclusion? Y/N

## Anti-Pattern Checklist

- Anti-Pattern: quoting memory as fact without signaling uncertainty.
- Anti-Pattern: letting one weak match dominate the answer.
- Anti-Pattern: ignoring explicit temporal or relationship cues from the user.
- Anti-Pattern: producing a synthesis that no longer maps cleanly back to the
  retrieved material.
