# Model price tables

This directory contains versioned, reviewed price snapshots used for local cost
attribution. Runtime code never fetches live prices or exchange rates.

Files are named `anthropic_YYYY-MM-DD.json`. The lexically latest dated file is
loaded by `src/app/core/llm_pricing.py`. Each file records:

- a version date;
- the USD-to-GBP conversion factor used for that snapshot;
- input and output prices per million tokens by exact model identifier;
- prompt-cache read and write multipliers.

Price tables are operational estimates, not invoices. Provider billing rules,
cache behavior, taxes, credits, regional pricing, and exchange rates may
change.

## Updating a table

1. Verify current prices against the provider's official pricing source.
2. Copy the most recent file to a new dated filename.
3. Update exact model identifiers, prices, multipliers, date, and conversion
   factor.
4. Keep the previous file as an audit trail.
5. Add or update tests for new models and multiplier behavior.
6. Run cost-attribution and alert tests.
7. Document the source and review date in the pull request without copying
   account-specific billing data.

For an unknown model, the estimator returns zero and logs a warning. Zero does
not mean the usage is free. Add the model to the price table before relying on
cost ceilings.
