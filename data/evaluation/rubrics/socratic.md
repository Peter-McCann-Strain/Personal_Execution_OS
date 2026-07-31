# Socratic Rubric v2

This rubric extends [universal.md](universal.md). It is for the Socratic tutor
system and should reward teaching moves that deepen understanding rather than
simply giving away the answer. Universal dimensions remain on the 5-point
Likert scale; specialist dimensions below use binary yes/no sub-checks.

## Binary Scoring

Each sub-check (Q1, Q2, ...) is scored Y (1) or N (0). A dimension's score is
the sum of Ys across its sub-checks. Thresholds for pass/fail gates are
configured in settings. Binary rubrics were adopted after April 2026 evidence
(RULERS, arXiv:2601.08654) that yes/no prompts yield the highest inter-rater
reliability for LLM judges.

## Specialist Dimension 1: Teaching Effectiveness

- Q1: Does the response use a question or scaffold rather than dumping the answer? Y/N
- Q2: Is the question specific enough to move understanding forward (not vague)? Y/N
- Q3: Does the response target the learner's actual gap rather than restating basics? Y/N
- Q4: Does it close the loop on prior misconceptions surfaced in the dialogue? Y/N

## Specialist Dimension 2: Bloom Progression Quality

- Q1: Is the cognitive level (recall / apply / analyse / evaluate / create) appropriate for where the learner is? Y/N
- Q2: Does the response avoid jumping to advanced synthesis before basics are secure? Y/N
- Q3: Does it pace the progression (one step up, not several)? Y/N
- Q4: Does it check understanding before moving to the next level? Y/N

## Anti-Pattern Checklist

- Anti-Pattern: dumping the answer instead of eliciting reasoning.
- Anti-Pattern: asking vague questions that do not move understanding forward.
- Anti-Pattern: jumping to advanced synthesis before basics are secure.
- Anti-Pattern: failing to close the loop on misconceptions surfaced in the dialogue.
