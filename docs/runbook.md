# Operation and recovery runbook

Use this runbook after completing the local chapters. Live operation requires verified source access and terms, configured deployment accounts, and successful validation of the actual hosted service.

## Local reference run

```bash
uv sync --extra dev
uv run python -m roadsafety pipeline --mode fixture --as-of 2026-11-01
uv run pytest
uv run uvicorn roadsafety.api:app --host 0.0.0.0 --port 8000
```

Query a known date range and compare it with the independently checked fixture results. Verify that `/v1/data-status` says fixture mode. Stop only processes you started.

For live operation, complete the [source gate](source-guide.md), use a separate `ROADSAFETY_DATA_DIR`, and confirm that live publication identifies itself accordingly.

## Deployment preparation

1. Keep the course code and permitted published analytical data in the user's public GitHub repository.
2. Review the repository's workflow files and Render configuration. Confirm current free-plan eligibility, resource limits, cold starts, and storage behavior in the provider account.
3. Create the Render service from the provided configuration. Its process runs FastAPI; pipeline processing remains on GitHub Actions.
4. Configure the API's published-manifest URL. The URL must point to a successfully uploaded manifest and matching snapshot, not an expiring CI artifact.
5. Store deployment and inference credentials in the appropriate provider's secret settings. Never place them in a manifest, release asset, report, or repository file.
6. Invoke a manual pipeline run before relying on the schedule. Validate the resulting release, checksum, API version, response values, and data status from outside the development machine.

Render's host check uses `/ready`: it succeeds when a verified snapshot can be
queried, including an older snapshot retained after an upstream failure. `/health`
is the richer diagnostic check and returns a degraded status for stale data,
failed refreshes, or unreadable snapshots. Keeping these separate prevents an
upstream data incident from causing a healthy serving process to restart
repeatedly. Inspect `/v1/data-status` to decide whether the data is suitable for
your request.

The existence of configuration files does not establish that an account was created, a workflow ran, or a public service deployed.

## Publication rules

Each candidate is built separately. The snapshot and required evidence are uploaded first; the latest-successful manifest changes last. The API opens only verified serving databases and checks for newer manifests while running.

Keep the previous successful publication when acquisition, validation, upload, or checksum verification fails. A previous snapshot can be served with its actual publication age and limitations. A fresh process with no valid snapshot must return unavailable rather than an empty success response.

The serving host's local files are a cache. A restart must recover from the remote publication and its checksum. Do not run a second DuckDB writer inside the API process.

## Evidence storage capacity

Recovery archives contain the warehouse, run evidence, investigation ledger,
prior publication manifest, and the two newest batches from each of `raw/` and
`landing/live/`. Before omitting an older batch, the uploader saves its exact
bytes in a separate immutable, content-addressed evidence release and confirms
its checksum. It never deletes local raw files or remote evidence assets.

`evidence-index.json` is retained in recovery state. It records each archived
batch's original path, immutable download URL, SHA-256, file count, and size.
For an older investigation, find the batch in this index, download its archive,
verify the recorded SHA-256, and inspect/extract it into a separate directory.
Do not overwrite current operational state when examining old evidence.

The seven newest operational recovery archives are retained; old evidence
releases are not pruned. Upload failure prevents a recovery archive from omitting
the affected batch. The per-asset and expanded recovery limit remains 1.9 GB,
so exceptionally large individual batches or warehouse growth still require
storage review. Resolve capacity without deleting evidence to make a job pass.

## Scheduled operation

Daily processing revisits 90 days. Weekly reconciliation refreshes the full 24-month horizon, including older corrections and removals established by a complete extraction.

The investigation schedule is separate from the pipeline schedule. Missing run
evidence, an incomplete/running latest run, or latest completion evidence older
than 36 hours is explicitly unavailable. With current evidence, the investigator
selects the newest unattempted failed run from the last seven days, even if a
later run succeeded, and includes that later outcome in its evidence. Credential
or budget refusals do not mark the failure processed. Paid or uncertain attempts
remain deduplicated by their durable reservations. It must not infer success
merely because the pipeline's scheduled time has passed.

GitHub schedules are best effort: jobs can be delayed or omitted, and inactive public repositories can have their schedules disabled. Monitor publication age and retain manual run/backfill procedures. Record schedule interpretation in UTC and America/New_York when configuring exact execution times.

## Incident procedure

1. Capture the failed run ID, source mode, acquisition window, error, and last successful publication.
2. Inspect raw inputs and checks without modifying them. Compare the candidate schema or values with the accepted contract and previous evidence.
3. Trace consumer impact: which outputs remain available, their age, and which intended updates are absent.
4. Run the incident procedure to compare a targeted workaround with a durable correction. Keep source-owner and consumer communication as drafts.
5. Review and implement the chosen code/configuration correction in the appropriate change workflow.
6. Rerun the same probe and the relevant regression tests. Publish only after the checks pass.
7. Retain the reviewed cause, remedy, evidence, and verified result in incident knowledge.

After reviewing the evidence and rerun yourself, explicitly retain your decision:

```bash
uv run python -m roadsafety record-incident --data-dir data --summary 'Reviewed required-field mapping; regression and rerun passed' --approve
```

This writes `incidents/reviewed.json`, which subsequent incident reports search. The incident-report command never approves its own recommendations.

A quarantine strategy must expose incomplete or stale publication status; it must not turn a failed refresh into an unqualified success.

## Common failure paths

| Observation | Response |
|---|---|
| Source-policy denial or inaccessible metadata | Preserve the failed verification result; fix the configured domain/access prerequisite and repeat the affected probe. |
| Missing or renamed required field | Keep the raw batch, block publication, compare schemas, and review the mapping/contract change. |
| Additional field | Record the drift and inspect its meaning; do not invent metadata. |
| Missing locations | Retain the crash in overall totals; expose unknown geography and analytical exclusions. |
| Interrupted pages or conflicting keys | Fail extraction; do not infer deletions from the partial result. |
| Historical totals change | Compare reconciliation evidence and source vintages before treating it as a pipeline defect. |
| Bad remote checksum | Retain the current verified snapshot; investigate the publication and retry only after a meaningful correction. |
| API restart | Download and verify the latest successful publication; verify the version through `/v1/data-status`. |
| AI credential, quota, or model failure | Preserve deterministic diagnostics and mark investigation unavailable; do not block diagnostic access or auto-repair. |

## AI usage controls

Interactive course work uses the owner's Codex subscription. Unattended hosted calls require separate API credentials and usage funding.

The automatic investigator calls the OpenAI Responses API with `gpt-4.1-mini`.
It is a bounded report generator with no tools, rather than a hosted Codex agent;
the workflow does not invoke the Codex GitHub Action. It collects selected run
fields, limits evidence to 12,000 bytes, caps output at 1,000 tokens, and permits
at most one paid investigation per UTC day. This adaptation keeps unattended
cost and execution scope explicit while preserving the tutorial's investigation
concepts. Interactive Codex and the seven reusable skills remain available for
deeper engineering work.

Use the application's monthly ledger and reservations, deduplicate repeated failure IDs, bound evidence and output tokens, and cap automated investigation frequency. The project targets $5/month. Provider budget alerts alone are not proof of a hard cap; inspect application enforcement and usage records.

Each attempt reserves $0.10 before a request and retains that reservation for
failed or uncertain calls. Hosted execution must save the reservation remotely
before inference. The price contract is explicit in the code and must be reviewed
before changing models or prices; a model without that contract is refused.

No public endpoint may initiate inference. Reports remain recommendations. Scheduled investigation must not execute generated code, merge changes, send communication, or replace publications.

## Recovery demonstration

The capstone is complete only after a controlled fault has produced a failed run, preserved the previous data version, yielded a grounded diagnosis, and been corrected with a verified rerun. Restart the API and prove that the recovered publication is still served.

For platform review, label replayed workloads and simulated history. A table unobserved in a short log window is not automatically unused or safe to remove.

