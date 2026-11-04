# First live exercise: understand the source

Your next task is to explain the real-data profile and propose its first quality rules. Focus on grain, identifiers, missingness, and evidence before building the warehouse.

## The batch we acquired

The pilot covers **October 25–31, 2026**, inclusive. Both NYC datasets report Daily updates; their latest observed event date when checked was October 31. Event dates, retrieval time, and publication time are separate facts.

| Measured property | Observed result |
|---|---:|
| Crash records | 1,472 |
| Vehicle-involvement records | 2,860 |
| Crash pages / vehicle pages, at 500 rows per page | 3 / 6 |
| Missing or duplicate crash/vehicle keys | 0 |
| Crash / vehicle identifiers starting with zero | 96 / 190 |
| Crashes without a borough | 48 |
| Crashes without usable coordinates under the course check | 53 |
| Vehicle records without a vehicle type | 317 |
| Vehicle records without a parent crash in this batch | 0 |
| Crashes without a vehicle record in this batch | 1 |

These are measured pilot results, not fixtures or permanent expectations. The preliminary source can be revised. A seven-day unique key is not proof of uniqueness across the full history. Passing required-key/date/count checks does not imply complete geography or descriptive fields. No production snapshot or public API was published by the pilot.

## Inspect and reproduce

In the prepared workspace, files and reports are under `/workspace/roadsafety-live-pilot`. From the repository root:

```bash
uv run python -m roadsafety profile --data-dir /workspace/roadsafety-live-pilot
uv run python -m roadsafety metadata --data-dir /workspace/roadsafety-live-pilot
```

Inspect `reports/profile.html`, `reports/profile.json`, `reports/metadata.yaml`, and `pilot-validation.json`. Original HTTP pages and hashes are under `landing/live/`; copies used for profiling are under `raw/`.

To acquire another bounded pilot, first verify sources and review current terms as described in [the source guide](source-guide.md), then run:

```bash
uv run python -m roadsafety live-pilot \
  --data-dir /workspace/roadsafety-live-pilot \
  --start-date 2026-10-25 --end-date 2026-10-31
```

The command accepts at most 31 inclusive days, exercises continuation pages, and reports `required_rule_outcome`. It never builds or publishes a warehouse. Inspect `quarantine/` if required rules are blocked. The seven-day pilot does not complete the production backfill.

## The first genuine engineering incident

The connector initially sent `collision_id > -1`. The live source rejected that comparison because its declared key type is **text**. The connector now reads the metadata type, omits a cursor on the first page, and quotes subsequent text cursors. Tests cover leading zeros, lexical ordering, quoted values, numeric keys, and missing/unsupported/changed types.

This was an implementation assumption exposed by live validation. We did not observe a publisher schema change. Keep an identifier such as `"001"` as a string, even when it looks numeric.

## Your exercise

1. State what one row represents in each source. Identify each candidate key and the parent/child join.
2. Calculate the missing-borough and missing-vehicle-type percentages. Propose whether each should warn, reject a field/row, or block publication. Explain the consumer impact.
3. Explain why zero orphan vehicles does not imply every crash has a vehicle record. Confirm with sets of identifiers from the acquired files.
4. Explain why joining vehicles before summing crash-level injuries can multiply the result. Define both metric grains.
5. Compare source-declared types with observed JSON types. Where should date/count parsing occur, and why do identifiers stay strings?
6. List what this pilot has not established: full-history completeness, delivery guarantees, exposure-adjusted road risk, or public service availability.

Completion check: missing borough is approximately **3.26%** and missing vehicle type approximately **11.08%**. Keep unknown geography in overall totals and preserve crash-level measures. Distinguish missing optional attributes from missing required identifiers or counts.

Once these decisions are recorded, move to Chapters 4–6: metadata/contracts, acquisition, then cleaning/integration. The 24-month backfill and hosted deployment follow those checks.

## Source-use evidence

[NYC's official FAQ](https://www.nyc.gov/opendata/get-started/FAQs) states: “Open Data belongs to all New Yorkers. There are no restrictions on the use of Open Data.” Dataset metadata does not name a licence; do not invent one. Both descriptions identify preliminary police-reported data and warn that revised crash details can amend records. For the most up-to-date fatality statistics, consult NYPD's linked traffic statistics rather than treating this independent project as official reporting.

Recommended notice: “Source: NYC Open Data / Police Department (NYPD), Motor Vehicle Collisions—Crashes and Vehicles. Preliminary police-reported data; records may be revised. Independent project; not an official NYC service.”
