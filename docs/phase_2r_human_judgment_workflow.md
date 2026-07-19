# Phase 2R.3B Human Judgment Workflow

Current workspace state adds an offline-only multilingual review workflow on top of shadow evaluation:

- blinded pairwise judgment-case generation from evaluated regional shadow artifacts
- strict import validation for completed review CSVs
- immutable reviewed-judgment snapshots
- bounded `cine-score-v2` candidate-weight evaluation against reviewed judgments

What is still true:

- production ranking remains `cine-score-v1`
- `cine-score-v2` remains shadow-only
- no API or frontend surface was added for this workflow
- no candidate configuration is auto-approved for production

Recommended next prompt seed:

- use a real completed reviewer CSV and ask for a focused comparison of control versus candidate weight configurations across Marathi, Malayalam, and Tamil
