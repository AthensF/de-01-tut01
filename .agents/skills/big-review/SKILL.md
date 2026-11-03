---
name: big-review
description: Review the road-safety platform using measured workload, storage, code, quality, and operational evidence. Use to prioritise improvements without automatically deleting or rewriting anything.
---

# Review the platform

## Inputs and permitted outputs

Read the database/catalogue, code, documentation, published snapshots, run/quality history, and available query/workload logs. This procedure may generate benchmark evidence and a platform-review report. It must not delete data, modify infrastructure, rewrite code, change retention, or publish replacements.

Run from the repository root:

```bash
python -m roadsafety platform-review --data-dir data
```

## Procedure

1. Describe the observation period, workload provenance, source mode, and missing logs. Label controlled benchmark queries and simulated usage history; neither establishes actual friend/consumer behaviour.
2. Measure database/snapshot size and representative query performance with reproducible commands. Report timings as measurements from this run, with target, row count, and relevant limitations.
3. Examine repeated logic, apparently unused code or fields, documentation drift, quality history, model complexity, retention, and publication/recovery behaviour. Trace each substantive finding to a concrete artifact.
4. Interpret usage cautiously. "Not observed in the available logs" is not "safe to remove". Seasonal, reconciliation, backfill, and recovery workflows may be essential despite infrequent execution.
5. Recommend improvements with expected benefit, risk, effort, dependencies, and a validation/rollback approach. Distinguish measured storage from hypothetical provider charges; do not invent cloud savings.
6. Keep suggestions proportional to this small public project. Do not introduce a distributed system merely to mimic an enterprise diagram.

## Evidence and completion

Return the review path and prioritised proposals. Reproduce one performance or storage finding and explain the observation limits behind one usage finding. Retain all existing data and code until a separate implementation task authorizes a reviewed change.
