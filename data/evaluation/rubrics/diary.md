# Diary Rubric v2

This rubric extends [universal.md](universal.md). Apply the universal
dimensions first (still scored on the 5-point Likert scale), then use the
specialist dimensions below to judge whether the diary specialist reflected
accurately and captured the right emotional signal.

## Binary Scoring

Each sub-check (Q1, Q2, ...) is scored Y (1) or N (0). A dimension's score is
the sum of Ys across its sub-checks. Thresholds for pass/fail gates are
configured in settings (e.g. a dimension must score at or above its threshold
for the interaction to pass). Binary rubrics were adopted after April 2026
evidence (RULERS, arXiv:2601.08654) that yes/no prompts yield the highest
inter-rater reliability for LLM judges.

## Specialist Dimension 1: Emotional Attunement

- Q1: Did the response acknowledge the emotional tone of the entry? Y/N
- Q2: Did it avoid generic affirmations such as "Great job!" or "You've got this!"? Y/N
- Q3: Did it connect to a specific detail in the entry (not a generic summary)? Y/N
- Q4: Did it match the operator's configured voice without saccharine or hyperbolic language? Y/N

## Specialist Dimension 2: Reflection Depth

- Q1: Did the response surface a pattern, meaning, or reflection prompt beyond simple summary? Y/N
- Q2: Did it avoid inventing analysis unsupported by the entry's content? Y/N
- Q3: Did it refrain from pushing advice when reflection was the primary need? Y/N
- Q4: Did it preserve structured capture opportunities (action items, people,
  tags) when clearly available? Y/N

## Anti-Pattern Checklist

- Anti-Pattern: generic wellness platitudes instead of engaging with the entry.
- Anti-Pattern: inventing events, relationships, or feelings not present.
- Anti-Pattern: pushing advice when the user primarily needed reflection.
- Anti-Pattern: skipping structured capture opportunities such as action items,
  people mentioned, or useful tags when they are clearly available.
