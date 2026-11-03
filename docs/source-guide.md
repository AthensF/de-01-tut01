# Source investigation and live-mode gate

The course starts with synthetic records so that engineering exercises remain repeatable. Live work has a separate gate: retrieve publisher evidence, inspect it, and confirm that the chosen sources satisfy the course's access and daily-refresh requirements.

## Candidate sources

| Dataset | Publisher target | Expected grain to verify |
|---|---|---|
| Crashes | [NYPD Motor Vehicle Collisions — Crashes](https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95) | One reported collision |
| Vehicles | [NYPD Motor Vehicle Collisions — Vehicles](https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Vehicles/bm4k-52h4) | One vehicle-involvement record |

The expected crash key is `collision_id`; the vehicle candidate key is `unique_id`, with `collision_id` linking to the parent. These are contract expectations to verify against current metadata and observed records, not a substitute for inspection.

The metadata endpoints are:

- `https://data.cityofnewyork.us/api/views/h9gi-nx95.json`
- `https://data.cityofnewyork.us/api/views/bm4k-52h4.json`

Data requests use the corresponding `/resource/<dataset-id>.json` endpoints.

## What counts as source verification

Run:

```bash
uv run python -m roadsafety verify-sources --data-dir live-data
```

Inspect the resulting source-verification report. It must distinguish technical probes from unresolved publisher facts. Record the agency owner, observed columns and types, sample-access result, update-frequency statement, documentation links, terms evidence, and limitations.

An accessible sample establishes access at that time. It does not prove that the dataset is complete, that every page is accessible, or that daily acquisition yields new events every day. Do not equate a metadata modification timestamp with a guaranteed row-level correction cursor.

Review the publisher's terms and attribution requirements before acknowledging them:

```bash
uv run python -m roadsafety verify-sources --data-dir live-data --accept-source-terms
```

Acknowledgment records the operator's review; it does not manufacture a licence when metadata omitted one. If the terms, required fields, or update cadence do not support the intended public service, resolve that before live publication.

Then acquire and run:

```bash
uv run python -m roadsafety pipeline --mode live --data-dir live-data
```

Use a different data directory from the teaching fixture. The published manifest and API responses must continue to identify their source mode.

## Network requirements

The data and metadata endpoints require `data.cityofnewyork.us`. Publisher documentation may require `www.nyc.gov` and `opendata.cityofnewyork.us`. Socrata query documentation is at `dev.socrata.com`.

If the proxy returns a destination-policy denial, configure these domains through the environment settings. Do not bypass the inherited proxy, disable TLS verification, or treat the fixture as a live replacement. A denied probe should remain visible as an unverified result.

## Corrections, boundaries, and pagination

The source can contain records whose occurrence date precedes their acquisition or correction date. The daily job revisits 90 days; the weekly reconciliation covers the full rolling 24-month horizon. An older correction may appear in the service only after reconciliation.

Use stable key ordering and bounded requests. Record acquisition start/end times, page counts, row counts, and hashes. A paginated download need not be an atomic database snapshot; detect repeated pages, missing required columns, conflicting keys, and interrupted extraction. A failed or incomplete extraction must not authorize record removal or publication.

## Interpret the data carefully

- Missing borough or location belongs in an explicit unknown group. Report how many records cannot support geographic analysis.
- Contributing factors and categories are reported values, not established causal conclusions.
- Several vehicle rows can belong to one crash. Sum injuries at crash grain before joining analytical outputs.
- Counts of reported crashes are not estimates of road danger without an appropriate exposure denominator.
- Preserve source columns in landing/bronze; use reviewed mappings for clean names and types.
- Deliberately renamed fields and corrupted records used in lessons are labelled test fixtures, not claims about publisher behavior.

