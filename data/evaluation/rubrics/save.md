# Save Rubric v2

This rubric extends [universal.md](universal.md). It scores whether the save
specialist captured the right durable information without storing noise or
misclassifying ephemeral chat content. Universal dimensions remain on the
5-point Likert scale; specialist dimensions below use binary yes/no sub-checks.

## Binary Scoring

Each sub-check (Q1, Q2, ...) is scored Y (1) or N (0). A dimension's score is
the sum of Ys across its sub-checks. Thresholds for pass/fail gates are
configured in settings. Binary rubrics were adopted after April 2026 evidence
(RULERS, arXiv:2601.08654) that yes/no prompts yield the highest inter-rater
reliability for LLM judges.

## Specialist Dimension 1: Capture Precision

- Q1: Did the agent save a durable signal (fact, preference, commitment) rather than transient chatter? Y/N
- Q2: Did it avoid over-capturing unrelated context alongside the target item? Y/N
- Q3: Is the saved content a faithful representation of what the user said (not distorted)? Y/N
- Q4: Did it preserve explicit preferences, deadlines, or commitments when present? Y/N

## Specialist Dimension 2: Classification Accuracy

- Q1: Was the correct memory type or PARA bucket assigned? Y/N
- Q2: Does the saved structure support later retrieval (tags, entities, links intact)? Y/N
- Q3: Was duplication or conflict with existing memory resolved correctly? Y/N
- Q4: Was the classification consistent with prior decisions for similar items? Y/N

## Anti-Pattern Checklist

- Anti-Pattern: storing transient chatter that has no future value.
- Anti-Pattern: missing explicit preferences, deadlines, or commitments.
- Anti-Pattern: saving a distorted version of the user's statement.
- Anti-Pattern: failing to preserve enough structure for later retrieval.
