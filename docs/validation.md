# Implementation validation

Validation was performed in this workspace using Python 3.12 and the committed frozen dependency lock.

| Check | Observed result |
|---|---|
| Frozen dependency installation | `uv sync --frozen --extra dev` passed |
| Automated tests | 104 passed; one upstream Starlette/AnyIO deprecation warning |
| Numbered chapter scripts | All 16 exited successfully on labelled synthetic inputs |
| Workflow validation | actionlint 1.7.7 passed; binary checksum verified against its official release |
| Local HTTP service | Readiness, collision summary, vehicle summary, and data status requests passed |
| Docker build | Passed with TLS verification and an optional mounted CA bundle; no CA copied into layers |
| Non-root container HTTP service | `/ready` and collision summary passed with expected fixture totals |
| Incident exercise | Required-field rename detected; previous publication retained |
| Recovery capstone | Duplicate vehicle key detected; corrected fixture restored original analytical content; API returned HTTP 200 |
| Live NYC source gate | Initially denied by the proxy; subsequently verified and exercised in the live pilot below |
| GitHub API access | Read-only repository API request denied; no release or workflow execution claimed |
| Public hosting and paid inference | Not executed; required external configuration is outstanding |

Independent fixture totals are 6 collisions, 3 injuries, 1 fatality, 6 involved vehicles, 1 unknown borough, and 2 missing/invalid locations. These are invented teaching records, not NYC observations.

The automated checks include pagination/retries and partial acquisition, malformed and renamed fields, duplicate identifiers, old corrections and removals, idempotence, failed-manifest rollback, unknown geography and join fanout, checksums and snapshot refresh/restart, API bounds, metadata provenance, reviewed incident reuse, conservative inference budgets, missing/stale run evidence, release upload ordering, and exact archival-byte recovery.

The hosted investigator is a bounded, tool-free Responses API adaptation. It is not an executed Codex GitHub Action. Interactive Codex procedures remain available under `.agents/skills/`.

## External activation

Follow `runbook.md` and `source-guide.md`. The initial domain-change save returned `draft_not_editable`; a later draft saved the settings, and NYC access subsequently succeeded. Required source domains include `data.cityofnewyork.us` and `www.nyc.gov`; GitHub API/release operations need their documented destinations. Use secure provider settings for credentials, never this repository or chat.

Re-run source verification and inspect current publisher documentation before acknowledging source terms. Fixture success cannot satisfy that gate. Complete a manual live acquisition, validated release, Render deployment, and external functional request before describing the API as publicly deployed.

## First live pilot

The source-use documentation was reviewed, current metadata identified both pagination keys as text, and a seven-day batch (October 25–31, 2026) was acquired successfully: 1,472 crashes and 2,860 vehicle records across three and six pages respectively. Required candidate rules passed with no quarantined records. Profiling measured missing optional attributes and preserved leading-zero identifiers. See `first-live-exercise.md` for the scope and findings.

The live run exposed a numeric-key assumption not represented by the original HTTP mocks. Metadata-aware cursor handling and new regression cases corrected it. The suite then passed 115 tests; live continuation requests also succeeded. This establishes bounded live acquisition/profile capability, not a complete 24-month warehouse or a deployed service.
