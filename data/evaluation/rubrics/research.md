# Research Rubric v2

This rubric extends [universal.md](universal.md). Apply it when judging whether
the research specialist asked sharp questions, used sources responsibly, and
returned a synthesis the user can trust. Universal dimensions remain on the
5-point Likert scale; specialist dimensions below use binary yes/no sub-checks.

## Binary Scoring

Each sub-check (Q1, Q2, ...) is scored Y (1) or N (0). A dimension's score is
the sum of Ys across its sub-checks. Thresholds for pass/fail gates are
configured in settings. Binary rubrics were adopted after April 2026 evidence
(RULERS, arXiv:2601.08654) that yes/no prompts yield the highest inter-rater
reliability for LLM judges.

## Specialist Dimension 1: Source Quality

- Q1: Does every claim trace to a retrieved finding or cited source? Y/N
- Q2: Are sources credible and relevant to the current request? Y/N
- Q3: Is uncertainty signalled clearly when evidence is mixed or stale? Y/N
- Q4: Are citations attached to the specific claims they support (not dumped at the end)? Y/N

## Specialist Dimension 2: Synthesis Depth

- Q1: Does the synthesis cite at least three independent findings? Y/N
- Q2: Are counter-arguments or alternative interpretations considered? Y/N
- Q3: Is the final answer decisive (recommendation / conclusion) rather than hedging? Y/N
- Q4: Does the tone follow the configured style without AI-isms or list-dumping notes? Y/N
- Q5: Does the synthesis resolve the user's need rather than leaving raw notes? Y/N

## Anti-Pattern Checklist

- Anti-Pattern: listing sources without integrating them.
- Anti-Pattern: implying certainty when the evidence is mixed or time-sensitive.
- Anti-Pattern: citing stale or irrelevant material for a current recommendation.
- Anti-Pattern: burying the practical answer beneath raw notes.
