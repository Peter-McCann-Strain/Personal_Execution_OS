# Notification Rubric v2

This rubric extends [universal.md](universal.md). Use it to judge whether the
notification specialist filtered noise, preserved urgency, and respected the
user's attention budget. Universal dimensions remain on the 5-point Likert
scale; specialist dimensions below use binary yes/no sub-checks.

## Binary Scoring

Each sub-check (Q1, Q2, ...) is scored Y (1) or N (0). A dimension's score is
the sum of Ys across its sub-checks. Thresholds for pass/fail gates are
configured in settings. Binary rubrics were adopted after April 2026 evidence
(RULERS, arXiv:2601.08654) that yes/no prompts yield the highest inter-rater
reliability for LLM judges.

## Specialist Dimension 1: Signal vs Noise

- Q1: Does the notification surface something the user needs to act on or know *now*? Y/N
- Q2: Is low-value clutter suppressed (not batched into the notification)? Y/N
- Q3: Is the most important item placed first rather than buried? Y/N
- Q4: Does the notification explain why it matters now (why today / why this minute)? Y/N

## Specialist Dimension 2: Timing Appropriateness

- Q1: Does the urgency level match the real need (no false emergencies)? Y/N
- Q2: Does the delivery channel match urgency (e.g. push vs digest)? Y/N
- Q3: Does the notification respect the user's stated focus / DND state? Y/N
- Q4: Does the notification avoid dangerous suppression of truly urgent items? Y/N

## Anti-Pattern Checklist

- Anti-Pattern: escalating informational events as if they were urgent.
- Anti-Pattern: hiding urgent commitments inside a long notification batch.
- Anti-Pattern: failing to mention why the notification matters now.
- Anti-Pattern: sending vague nudges that the user cannot act on.
