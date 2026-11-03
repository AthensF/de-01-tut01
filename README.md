# Road-safety data engineering

An executable course and Python application for collecting crash and vehicle records, building DuckDB analytical models, and publishing a public FastAPI service.

The 16 chapters build one application. Python and SQL calculate the results; Codex helps explain, investigate, document, and review the engineering work. Start with the labelled synthetic fixture, then pass the source-verification gate before acquiring NYC data.

## Start here

Python 3.12 and [uv](https://docs.astral.sh/uv/) are the development prerequisites. From this checkout:

```bash
uv sync --extra dev
uv run python -m roadsafety pipeline --mode fixture --as-of 2026-11-01
uv run python course/chapter_01_sources.py
uv run python course/chapter_03_profile.py
uv run pytest
```

The fixture is deliberately small, synthetic, and fixed to a teaching date. Its successful run does not verify NYC access, source cadence, current schemas, or reuse terms.

Start the API in another terminal:

```bash
uv run uvicorn roadsafety.api:app --host 0.0.0.0 --port 8000
```

Use local requests for development validation:

```bash
curl 'http://127.0.0.1:8000/v1/collisions/summary?start_date=2026-10-01&end_date=2026-11-01'
curl 'http://127.0.0.1:8000/v1/data-status'
```

For the full default fixture range, the summary's relevant fields are:

```json
{
  "source_mode": "fixture",
  "totals": {"collisions": 6, "injured": 3, "killed": 1, "missing_location": 2}
}
```

OpenAPI documentation is served at `/docs`. For a different workspace, set `ROADSAFETY_DATA_DIR` consistently for the CLI and API.

## Follow the course

Read the [chapter guide](docs/course.md), run the corresponding script in [course/](course/), complete its exercise, and check the result. Each script calls the shared `roadsafety.lessons` dispatcher; the lessons do not contain separate copies of the application.

The [requirements mapping](docs/requirements-traceability.md) connects the tutorial's ten requirements to the executable chapters.

| Stage | Chapters |
|---|---|
| Establish the project | 1. Source verification · 2. Python project |
| Understand the data | 3. Profiling · 4. Metadata and contracts |
| Build the pipeline | 5. Acquisition · 6. Cleaning and integration |
| Publish a product | 7. Measures · 8. Public API |
| Operate the system | 9. Quality and runs · 10. Incidents |
| Document and review | 11. Engineering toolkit · 12. Change review |
| Deploy and automate | 13. Deployment · 14. Hosted investigation |
| Demonstrate readiness | 15. Platform review · 16. Recovery capstone |

The seven Codex procedures live under `.agents/skills/`: `profile`, `metadata`, `incident`, `toolkit`, `data-product`, `pr-review`, and `big-review`.

## Live sources and refresh semantics

The proposed sources are NYC's [Motor Vehicle Collisions — Crashes](https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Crashes/h9gi-nx95) and [Vehicles](https://data.cityofnewyork.us/Public-Safety/Motor-Vehicle-Collisions-Vehicles/bm4k-52h4). Read the [source guide](docs/source-guide.md) before enabling live mode.

The application retains a rolling 24 months. Daily runs revisit 90 days; weekly full runs reconcile the retained horizon. This catches older corrections eventually, rather than claiming complete change-data capture. Raw source responses, checksums, acquisition boundaries, and run records provide evidence.

Each published snapshot identifies whether it came from fixtures or live data. Unknown borough or location stays visible. Collision and injury totals are calculated from crash records; vehicle counts use their own grain.

## Public API

| Route | Purpose |
|---|---|
| `GET /v1/collisions/summary` | Reported collisions and injury totals |
| `GET /v1/collisions/trends` | Daily or monthly trends |
| `GET /v1/vehicles/summary` | Vehicle involvement |
| `GET /v1/data-status` | Version, quality, acquisition time, and limitations |
| `GET /ready` | Host readiness: a verified snapshot can be queried |
| `GET /health` | Diagnostic health, including stale data and refresh failures |
| `GET /docs` | Interactive request documentation |

Queries are bounded and read-only. These counts describe reported events, not exposure-adjusted road risk. Public requests do not invoke an AI model.

## Deployment and operating costs

GitHub Actions builds validated snapshots, GitHub releases retain publications, and Render serves the read-only API. The API verifies a snapshot on startup and can refresh while running; local host storage is disposable. Failed processing preserves the previous successful publication.

The repository includes deployment and scheduling configuration. Hosted operation still requires the owner's GitHub/Render setup, verified source access and terms, and separate API credentials for unattended model calls. See the [runbook](docs/runbook.md) for activation and recovery checks.

Use your Codex subscription for interactive course work. Hosted API usage is separate, with a $5/month application target and bounded investigation calls. Free service limits and account eligibility must be checked during deployment; a working local fixture is not evidence of a deployed public service.

The hosted investigator is an intentional adaptation: it sends a bounded evidence
bundle to the OpenAI Responses API using `gpt-4.1-mini`, with no tools or command
execution. The scheduled workflow does not launch the Codex GitHub Action. Your
Codex subscription and the seven local skills support interactive engineering;
hosted model requests use separate API billing and a persistent reservation ledger.

Operational recovery archives preserve raw acquisitions and evidence. Their
upload/restoration limit is 1.9 GB; reaching it fails closed rather than silently
discarding history. Review long-running evidence storage before this limit is
approached.

## Tutorial provenance

This course adapts the engineering concepts in [Data with Baraa's tutorial](https://www.youtube.com/watch?v=F5lZj1bQyUw) and its [companion repository](https://github.com/DataWithBaraa/claude-code-data-engineering-skills). It builds the platform foundations that the video assumes already exist, using a different source and Codex workflows. Source data, synthetic fixtures, injected defects, and simulated operational history are kept distinguishable.

