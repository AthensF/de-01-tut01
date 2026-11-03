# The executable road-safety course

This course assumes that you can write a Python function, use SQL joins and aggregates, and inspect a Git diff. Its goal is one working application whose engineering behavior you can explain and reproduce.

## Prepare once

Run commands from the checkout root:

```bash
uv sync --extra dev
uv run python -m roadsafety pipeline --mode fixture --as-of 2026-11-01
uv run pytest
```

The fixed fixture is synthetic. Every course result must retain that provenance. Read [source-guide.md](source-guide.md) before using live data and [runbook.md](runbook.md) before activating external jobs.

Each numbered script calls `roadsafety.lessons.run_lesson`, which uses the shared application functions. Default execution uses local, deterministic evidence and does not deploy services or make paid model calls. `--live` opts into the lesson's source-access path; external publication and paid inference still require their dedicated commands and configured prerequisites.

Use a separate directory for an exercise, for example:

```bash
uv run python -m roadsafety pipeline --mode fixture --as-of 2026-11-01 --data-dir exercise-data
uv run python course/chapter_03_profile.py --data-dir exercise-data
```

A chapter's JSON output identifies its artifacts and checks. Inspect the artifacts, complete the exercise, and establish its completion check before continuing. Installation or a process exit alone is not a data-correctness check.

## Independently check the teaching fixture

The default fixture has the following six invented crashes. The IDs are strings;
their leading zeros are intentional. These rows are teaching inputs, not NYC
observations.

| Crash | Borough | Injured | Killed | Involved vehicle records |
|---|---|---:|---:|---:|
| `001` | BROOKLYN | 2 | 0 | 2 |
| `002` | UNKNOWN | 1 | 0 | 1 |
| `003` | QUEENS | 0 | 0 | 1 |
| `004` | MANHATTAN | 0 | 1 | 1 |
| `005` | BRONX | 0 | 0 | 1 |
| `006` | STATEN ISLAND | 0 | 0 | 0 |

For the full fixture date range, calculate **6 collisions, 3 injured, 1 killed,
and 6 involved vehicle records**. One collision has unknown borough; two have
missing or invalid locations. Crash `001` is the useful fanout example: its two
injuries must remain two even though it has two vehicle records. Crash `006`
must remain in crash totals despite having no matching vehicle row.

## Chapter 1 — Verify the source contract

An API URL is not a source contract. We need publisher evidence for access, fields, grain, update behavior, correction rules, and permitted reuse before designing a public service.

**Run**

```bash
uv run python course/chapter_01_sources.py --data-dir data
```

**Inspect:** The default lesson records the source-verification plan without contacting NYC. Add --live only when you are ready to probe the publisher endpoints.

**Exercise:** Open the proposed metadata endpoints and compare their current columns with the expected crash and vehicle keys. Record one meaning that cannot be established from a column name alone.

**Completion check:** The offline result is explicitly unverified. A live result records failed probes and unresolved terms instead of treating them as successful source verification.

**Tutorial mapping:** REQ-01; foundation for all live work.

## Chapter 2 — Create a runnable Python project

A production project needs one dependency definition, stable commands, configuration, and tests. The numbered lessons delegate to the same package used by scheduled jobs and the API.

**Run**

```bash
uv run python course/chapter_02_project.py --data-dir data
```

**Inspect:** Inspect the application entry points and configuration reported by the lesson. Run the fixture pipeline from a clean data directory.

**Exercise:** Change the data directory and show that the API and scripts use that same configured directory. Read AGENTS.md and identify the boundary between persistent context and task-specific procedures.

**Completion check:** You can install from the lockfile, run the shared CLI, and locate a completed run manifest without editing a lesson script.

**Tutorial mapping:** REQ-01.

## Chapter 3 — Measure before validating

Profiling discovers what a source contains; validation checks an agreed expectation. Measure counts, missingness, uniqueness, categories, dates, and parent-child relationships before choosing rules.

**Run**

```bash
uv run python course/chapter_03_profile.py --data-dir data
```

**Inspect:** Generate the profile report from the fixture source and inspect the measured evidence. Repeat on the second table to exercise the same reusable procedure.

**Exercise:** Independently count a small selection of fixture rows. Identify one duplicate or missing-value check and explain whether it is a discovery, a warning, or a publication blocker.

**Completion check:** The independently counted result matches the report. The reusable profile produces the same structure for crashes and vehicles and leaves the input unchanged.

**Tutorial mapping:** REQ-02, REQ-03; profile skill.

## Chapter 4 — Describe structure and meaning

Technical metadata can be extracted from data. Business descriptions require documentation. A plausible sentence is not evidence, and a key name does not prove uniqueness.

**Run**

```bash
uv run python course/chapter_04_metadata.py --data-dir data
```

**Inspect:** Generate metadata and inspect its observed columns, types, key evidence, and unresolved descriptions. Read the source contract separately from the consumer contract introduced later.

**Exercise:** Choose an undocumented field and leave its meaning unresolved. For a documented field, retain its source reference. Explain why string identifiers must not be converted just because they look numeric.

**Completion check:** Metadata matches the observed source, a documented description has provenance, and an undocumented description remains visibly unknown.

**Tutorial mapping:** REQ-06; metadata skill.

## Chapter 5 — Acquire repeatable batches

Acquisition is complete only after every requested page passes its checks. Raw bytes and checksums allow later investigation; a partial page sequence cannot justify deleting or publishing data.

**Run**

```bash
uv run python course/chapter_05_acquire.py --data-dir data
```

**Inspect:** Run the fixture acquisition path and inspect its batch provenance. For live work, inspect the verification gate before enabling network acquisition.

**Exercise:** Compare repeated acquisitions and identify which fields describe the request, the observed data, and the execution. Simulate an interrupted live response with the existing mocked acquisition tests.

**Completion check:** The raw acquisition has a completion state and checksum evidence. An interrupted or repeated page sequence fails and leaves the previous publication intact.

**Tutorial mapping:** Pipeline foundation.

## Chapter 6 — Clean, integrate, and reconcile

Bronze retains source values. Silver-clean establishes usable types and keys; silver-core represents related business records. Daily overlap and full reconciliation solve different revision problems.

**Run**

```bash
uv run python course/chapter_06_integrate.py --data-dir data
```

**Inspect:** Build the fixture warehouse and inspect the separate crash and vehicle grains, quarantine evidence, retention horizon, and publication result.

**Exercise:** Run the same input twice. Then use the historical-correction tests to compare a daily refresh with full reconciliation. Explain when an old correction becomes visible.

**Completion check:** Business-key counts and measures do not double after a rerun. Full reconciliation repairs an older correction; an incomplete extraction cannot remove records.

**Tutorial mapping:** Pipeline foundation.

## Chapter 7 — Define the analytical product

A metric requires a grain, eligible records, aggregation rule, and limitations. Counting vehicles is different from counting crashes, and joining them can multiply injury totals.

**Run**

```bash
uv run python course/chapter_07_measures.py --data-dir data
```

**Inspect:** Build gold crash and vehicle summaries. Read the generated product documentation and its metric definitions.

**Exercise:** Manually calculate a small fixture total before reading the query output. Compare a crash with several vehicles and show why its injury count must be counted once.

**Completion check:** Your independent totals match the gold summaries; unknown borough remains represented and every published measure states its grain.

**Tutorial mapping:** REQ-08; data-product skill.

## Chapter 8 — Serve bounded analytical queries

The consumer should not need to guess join keys or execute arbitrary SQL. The API accepts documented filters, uses a read-only snapshot, and identifies the data version in results.

**Run**

```bash
uv run python course/chapter_08_api.py --data-dir data
```

**Inspect:** Exercise the shared API against the fixture publication. Start the API separately with the README command to make your own requests.

The API nests analytical values under `totals`. For the full fixture range,
`totals.collisions` is 6, `totals.injured` is 3, and `totals.killed` is 1.
`/ready` checks whether a verified snapshot is queryable; `/health` also diagnoses
data freshness and refresh failures.

**Exercise:** Request two date ranges and compare them with gold-table results. Try an invalid range, unsupported granularity, and an excessive limit. Inspect /v1/data-status.

**Completion check:** Valid responses reconcile with independently checked metrics. Invalid requests fail clearly, and fixture data cannot masquerade as a live public product.

**Tutorial mapping:** REQ-08.

## Chapter 9 — Make runs and quality observable

A finished process is not proof of a correct refresh. Record acquisition, transformation, validation, and publication outcomes separately, with timestamps and evidence.

**Run**

```bash
uv run python course/chapter_09_quality.py --data-dir data
```

**Inspect:** Inspect the run history, checks, quarantine results, and current publication metadata produced by the fixture pipeline.

**Exercise:** Identify occurrence time, acquisition time, publication time, and reconciliation time. Explain which should be used to assess a delayed refresh.

**Completion check:** You can determine whether a batch passed and whether it replaced the publication. The last successful version is traceable to a run and checks.

**Tutorial mapping:** Operations foundation.

## Chapter 10 — Investigate a controlled failure

A useful incident report identifies the failed step, evidence, consumer impact, cause, workaround, durable fix, and verification plan. Incident knowledge is separate from raw execution logs.

**Run**

```bash
uv run python course/chapter_10_incident.py --data-dir data
```

**Inspect:** Run the labelled incident exercise and read the generated evidence-based report. Compare its recommendation with the failed run and raw/schema evidence.

**Exercise:** Propose a targeted correction and a preventive change. Draft separate consumer and source-owner messages, without sending them. Review the incident record before retaining it as knowledge.

**Completion check:** The report traces its diagnosis to evidence, describes the last usable publication, and does not claim a rerun or fix that was not executed.

**Tutorial mapping:** REQ-04; incident skill.

## Chapter 11 — Generate engineering documentation

Architecture, lineage, a call graph, models, catalogue, runs, and quality history describe different relationships. Their edges and statistics must come from project evidence.

**Run**

```bash
uv run python course/chapter_11_toolkit.py --data-dir data
```

**Inspect:** Rebuild the engineering toolkit from application metadata and run/check results.

**Exercise:** Choose one published measure, trace its upstream model and transformation, and locate its quality evidence. Rebuild after a controlled metadata change in a separate exercise directory.

**Completion check:** The trace points to actual project objects and current evidence; rebuilding changes the generated documentation without hand-editing the site.

**Tutorial mapping:** REQ-07; toolkit skill.

## Chapter 12 — Review a change against standards

Review is an evidence-based assessment of a diff. Findings need a location, violated rule, risk, and actionable suggestion, rather than a silent rewrite.

**Run**

```bash
uv run python course/chapter_12_review.py --data-dir data
```

**Inspect:** Run the review exercise on its labelled proposed change and inspect the resulting report.

**Exercise:** Find the seeded defect yourself before opening the report. Explain how a test would expose it and why the suggested change is in scope.

**Completion check:** The finding identifies the relevant change and its consequence. Producing the review does not modify, merge, or push the proposal.

**Tutorial mapping:** REQ-09; pr-review skill.

## Chapter 13 — Publish and recover a serving snapshot

The serving database is a verified publication, not the API host's durable state. Upload snapshot evidence first, publish the manifest last, and keep the prior verified version on failure.

**Run**

```bash
uv run python course/chapter_13_deploy.py --data-dir data
```

**Inspect:** Run the local publication-verification exercise. Review render.yaml and the deployment runbook before configuring external accounts.

Use `/ready` for the Render process check and inspect `/health` and
`/v1/data-status` for the data's operational condition. A retained older snapshot
can remain queryable while diagnostic health is degraded. Also review the 1.9 GB
operational-archive limit and the runbook's evidence-capacity procedure.

**Exercise:** Restart the local API and confirm its version. Use snapshot tests to offer a corrupt replacement and a valid newer one; compare resulting responses.

**Completion check:** A restart serves a verified version, a bad checksum preserves the previous version, and a warm API can adopt a newer publication. Local completion does not claim external deployment.

**Tutorial mapping:** Deployment foundation.

## Chapter 14 — Schedule bounded investigation

Pipeline execution and AI investigation have separate schedules and credentials. Healthy runs and duplicate failures should not spend model tokens; unavailable inference must not erase deterministic diagnostics.

**Run**

```bash
uv run python course/chapter_14_automation.py --data-dir data
```

**Inspect:** Run the default investigation dry-run and scheduling checks. Examine the hosted workflow configuration, ledger, and model-call conditions.

The automatic implementation uses the OpenAI Responses API and `gpt-4.1-mini`
for a bounded, tool-free report. This is the project's adaptation of the hosted
investigation mechanic; it does not run the Codex GitHub Action. Use your Codex
subscription and local skills interactively for investigations that need code
inspection or execution, while the separate hosted API budget remains bounded.

**Exercise:** Exercise healthy, new-failure, repeated-failure, exhausted-budget, and model-error cases in the automated tests. Identify where an owner supplies API credentials securely.

**Completion check:** No local lesson silently spends API credits. Hosted acceptance requires a real scheduled healthy/failure demonstration, with the report and usage outcome retained.

**Tutorial mapping:** REQ-05.

## Chapter 15 — Review the whole platform

Usage, performance, storage, and code evidence answer different questions. A short absence from logs is not proof that an object is unused, especially with seasonal workloads.

**Run**

```bash
uv run python course/chapter_15_platform_review.py --data-dir data
```

**Inspect:** Generate the platform review and inspect the observation period and provenance for each finding.

**Exercise:** Reproduce one performance or storage finding. Identify which history is measured, replayed, or simulated and what conclusions each can support.

**Completion check:** Every recommendation cites evidence and states its observation limits. The review proposes improvements rather than deleting data or code.

**Tutorial mapping:** REQ-10; big-review skill.

## Chapter 16 — Demonstrate a complete recovery

The final proof is a recovered analytical product: an unseen variant fails, a previous version stays usable, the cause is established, and corrected processing produces a verified publication.

**Run**

```bash
uv run python course/chapter_16_capstone.py --data-dir data
```

**Inspect:** Run the capstone in an isolated data directory. Let the exercise expose its failure before inspecting the labelled test fixture.

**Exercise:** Write your own diagnosis and recovery plan, then compare it with the evidence. Run the corrected pipeline, restart the API, and query the recovered version.

**Completion check:** Retain the failed run, grounded diagnosis, passing rerun, recovered manifest, and independent public/client check. Distinguish the completed local exercise from any unexecuted hosted step.

**Tutorial mapping:** REQ-01–REQ-10 acceptance.

## Finish with evidence

Keep a short learning log linking each completion check to its command, input, result, and artifact. Use the capstone to demonstrate the integrated system rather than collecting screenshots of commands that merely started.

The local course is complete when its fixture checks pass and you can explain every publication boundary. The live shared service requires an additional source-verification result, successful hosted processing, external API checks, and the configured hosted investigation. Record each outcome separately.

