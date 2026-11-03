> User-provided source extraction, retained for reference. This document does not configure the application or override project instructions.

# Tutorial extraction: AI-assisted data engineering

Extract the demonstrated requirements, concepts and mechanics so we can later design a practical course using independently researched data.

## 1. Scope and evidence

This is the requirements-extraction stage, not the course syllabus. No replacement dataset, database engine, cloud platform or AI subscription has been selected. No pipeline or skills have been installed.

**Video:** [How I Use Claude Code as a Data Engineer (After 17 Years in Data)](https://www.youtube.com/watch?v=F5lZj1bQyUw), Data with Baraa, published 29 October 2026, duration 29:12. The video discloses sponsorship by Anthropic.

**Companion repository:** [DataWithBaraa/claude-code-data-engineering-skills](https://github.com/DataWithBaraa/claude-code-data-engineering-skills), inspected at commit `99bfe5b43c763f384adb5159e23c55e504681fb2`, committed 29 October 2026.

Evidence labels used below:

- **[V] Video:** the published chapter markers and the complete original-English automatic captions. Caption wording can contain transcription errors; timestamps are navigation anchors, not exact boundaries for every action.
- **[R] Repository:** the author's README, seven featured skill definitions, metadata/contract examples, architecture HTML and four published example screenshots. These can clarify or extend the video; they are not independent proof of a live pipeline run.
- **[D] Current documentation:** official Claude Code documentation retrieved through Context7 to check skills and scheduling mechanics.
- **[A] Adaptation:** a proposed requirement for our eventual learning project, not a claim that the author demonstrated its implementation.

**Visual limitation:** YouTube's browser player returned a playback error. The visual cross-check used the author's published profile, incident, architecture and data-product screenshots, not a frame-by-frame inspection of the video.

**Important findings**

1. This is a demonstration of engineering workflows around an existing data platform, not a step-by-step build of that platform. [V]
2. The repository explicitly says its example company and data are fictional. Its large row counts, durations and report statistics are illustrative, not verified benchmarks or targets for our project. [R]
3. The repository contains skill instructions, example HTML, images, YAML and plugin packaging. It does not supply the underlying source deliveries, runnable warehouse pipeline or operational history shown in those reports. [R]
4. Seven skills are featured in the video; the repository contains sixteen. The extra nine are extensions, not nine additional lessons demonstrated in this video. [R]
5. The workspace was empty when inspected. There is no existing implementation or data flow here to preserve.

## 2. What the video actually covers

These are the video's sections, not a proposed chapter order for our course.

| Video interval | Demonstration | Underlying concepts | Result or artefact |
|---|---|---|---|
| 00:00–01:22 | Explains engineering work beyond writing scripts | Trust, source understanding, modelling, operations, reviews and consumer needs | Framing: AI assists the engineer; it does not own decisions |
| 01:22–03:02 | Introduces a SQL/Python project in VS Code with Claude Code, project instructions, skills and HTML outputs | Persistent project context; repeatable workflows; readable evidence | Project instructions and a skill-based working pattern |
| 03:02–07:42 | Profiles a new source before building ingestion | File formats, schema, completeness, uniqueness, identifiers, drift, freshness, deletions and personal-data identification | A source-profiling report and inputs to a source contract |
| 07:42–09:04 | Turns the refined profiling process into a skill | Codifying a repeatable procedure; bundling instructions and supporting code | Reusable `profile` skill |
| 09:04–10:52 | Introduces incident work and a persistent knowledge layer | Operational knowledge; learning from previous failures; technical logs versus incident history | YAML incident-history file |
| 10:52–15:32 | Investigates a failed silver-layer job | Root cause, schema drift, impact, workarounds, durable fixes, prevention and communication | Incident report, two fix options, email drafts and incident record |
| 15:32–16:37 | Schedules the incident workflow | Recurring automation; conditionally invoking a skill; remote execution | A cloud routine to inspect pipeline logs and report failures |
| 16:37–20:38 | Extends metadata using data files and source documentation | Technical versus business metadata, provenance, missing knowledge, generators and parallel work | YAML metadata plus a reusable Python extraction script |
| 20:38–24:56 | Builds an engineering toolkit website from the project | Architecture, lineage, call graphs, modelling, quality history and discoverability | Interactive engineering documentation |
| 24:56–26:32 | Presents consumer-facing data products | Product ownership, access, grain, metric definitions, quality, releases and consumer contracts | A product catalogue and product detail pages |
| 26:32–28:16 | Reviews a change and then the whole platform | Security, correctness, standards, usage, performance, storage and technical debt | PR-review findings and a platform-wide improvement report |
| 28:16–29:12 | Concludes with the engineer's responsibility | Human review and accountability | The engineer makes the final decision |

## 3. The architecture being examined

The video explicitly names landing, bronze, two silver layers, gold and a semantic layer around 22:21–22:31. The companion architecture example supplies the layer names and more precise responsibilities. [V, R]

```text
Source systems / delivered files
              |
              v
           Landing
              |
              v
            Bronze
              |
              v
         Silver clean
              |
              v
         Silver core
              |
              v
          Gold marts
              |
              v
      Semantic metrics / data products
              |
              v
       Analysts and other consumers

Supporting evidence:
  source contracts + metadata + pipeline code
  run records + quality results + quarantine records
  incident history + consumer query history
```

| Component | Responsibility in the companion example |
|---|---|
| Landing | Preserve delivered files, including baseline, daily-feed and month-end extracts |
| Bronze | Append the received rows; preserve raw values as text |
| Silver clean | Parse, standardise and validate data; establish clean records at the intended key |
| Silver core | Integrate cleaned sources into business entities |
| Gold marts | Publish consumption-oriented models, including a star schema and a denormalised “one big table” |
| Semantic layer | Define reusable business measures and their calculation rules |
| Quality gates and quarantine | Decide whether files, rows or downstream tables can proceed; retain rejected inputs for investigation |
| Metadata and contracts | Describe structure, meaning and expectations; support documentation and selected code generation |
| Operational evidence | Record what ran, what failed, what passed and what consumers used |

The companion example has four gates: file checks, structural/type checks, row rules, then table/key/completeness checks. Its last gate can prevent gold publication. This is repository detail, not a sequence the video teaches us to implement from scratch. [R]

The author calls the platform a lakehouse. The inspected material does not establish a mandatory database engine, table format, cloud vendor or orchestration product. We should reproduce the responsibilities before choosing products. [V, R, A]

## 4. Functional requirements to preserve

The inputs and actions below are extracted from the video and repository. Each **learning-project acceptance check** is our proposed way to demonstrate the mechanic with new data. [A]

### REQ-01 — Project context and bounded AI workflows

**Evidence:** 01:22–03:02; companion project instructions.

- Keep concise project-level instructions covering architecture, standards, paths, approvals and responsibilities.
- Separate always-relevant project context from task-specific skills.
- Define what every skill reads, writes and must not do.
- Refine a workflow before turning it into a reusable skill.
- Present substantial findings in readable reports rather than relying on chat history.
- Treat the engineer as the decision-maker; an AI-generated recommendation is not approval.

**Output:** project instructions and reusable, scoped procedures.

**Acceptance check:** in a fresh session, invoke a procedure with a new input and obtain the required evidence without re-explaining the workflow. No unapproved writes, sends or destructive actions occur.

**Portability:** the original uses `CLAUDE.md` and `.claude/skills/`. Those are descriptions of the source setup, not instructions to create them here. New Devin configuration belongs in `.devin/`; choosing the course's agent environment remains a later decision.

### REQ-02 — Profile source data before designing ingestion

**Evidence:** 03:02–07:42; `profile`.

**Inputs:** source files or tables, multiple deliveries where available, and existing metadata if present.

The profile must examine:

- File format, delimiter, quoting, encoding, decimal separators and null representations.
- Table and column inventory, row counts, observed data types and date/timestamp formats.
- Nulls, empty or constant columns, duplicate rows and candidate-key uniqueness.
- Corrupt records, out-of-range values, outliers and placeholders.
- Identifier consistency, including leading zeros and inconsistent representations.
- Schema changes across deliveries.
- Missing delivery periods, stale tables and deletion conventions.
- Potential personal or sensitive fields, without exposing their values.
- Relationships and orphan child records; the repository makes this check explicit.

Use scripts or queries to compute the findings. Rank issues and distinguish decisions for the source owner from handling required in our pipeline.

**Output:** one profiling report with measured results, evidence and contract/pipeline implications.

**Acceptance check:** independently reproduce selected counts and detect a known duplicate, a missing key and a schema change in controlled fixtures. Source files remain unchanged.

**Interpretation limits:** a gap is not automatically a delivery failure; a quiet reference table is not automatically stale. Check the source's calendar and expected update behaviour. CSV types are inferred from values, not guaranteed by the file format.

### REQ-03 — Package validated procedures as reusable skills

**Evidence:** 07:42–09:04 and repeated after subsequent demonstrations.

- Capture the successful procedure in a `SKILL.md`, with input arguments and supporting scripts/references where needed.
- Specify the output shape and evidence requirements.
- Reuse the procedure for another source or incident rather than copying an entire conversation.
- Keep task-specific procedures out of an unnecessarily large always-loaded instructions file.

**Output:** a repeatable skill, initially for profiling.

**Acceptance check:** the skill runs on a second input and preserves the same checks and report structure. Numerical computations are reproducible; identical model wording is not required.

### REQ-04 — Investigate incidents and retain organisational knowledge

**Evidence:** 09:04–15:32; `incident`.

**Inputs:** failed-run logs, pipeline code, relevant delivered data, check/quarantine records and previous incident history.

The workflow must:

1. Locate the failed job, task, layer, code and error.
2. Establish the status and impact on consumers.
3. Compare before/after evidence to identify the triggering change.
4. Search incident history for similar failures and previous remedies.
5. Propose an immediate workaround.
6. Compare a direct fix with a more durable preventive solution.
7. Identify other tables or jobs exposed to the same risk.
8. Draft separate communications for consumers and the source owner.
9. Propose an incident-history entry and retain the reviewed outcome.

**Demonstrated example:** an incoming field changes from `status_code` to `status`, while silver SQL still expects the old name. An additional field also arrives. Gold processing is affected. The report compares a targeted mapping/code change with a schema-checking and quarantine strategy. [V, R]

**Outputs:** HTML investigation report, communication drafts and a reviewed incident record.

**Acceptance check:** introduce a labelled schema-rename fixture, capture the failing run, diagnose it from evidence, obtain approval for a fix, then rerun the same probe. Record the verified outcome.

**Boundary:** the published skill proposes; it does not fix, rerun jobs or send email. It appends incident history only after approval. A quarantine strategy must not disguise incomplete or stale data as a fully successful refresh.

### REQ-05 — Schedule investigation separately from the data pipeline

**Evidence:** 15:32–16:37; official scheduling documentation.

- At a chosen time, inspect recent pipeline results.
- Invoke incident investigation if a failure is present.
- Make the report available for human review.
- Keep the pipeline's execution schedule separate from the AI investigation schedule.

The video uses `/schedule` and calls the cloud task a “routine”. Current documentation calls these **cloud scheduled tasks**, formerly routines. They can run while the local computer is off. Local desktop tasks and CLI `/loop` have different execution and availability requirements. [D]

**Prerequisites for equivalent cloud behaviour:** the hosted environment must have authorised access to the repository, required skills, dependencies and relevant logs/data. A GitHub connection does not make local-only files available automatically.

**Acceptance check:** exercise both a successful-run case and a failed-run case. A hosted run produces the correct result without relying on a live local session.

**Scope:** scheduling is demonstrated, but we do not need to purchase a service or enable unattended actions during requirements extraction.

### REQ-06 — Build metadata from evidence, not plausible prose

**Evidence:** 16:37–20:38; `metadata`.

**Inputs:** source files, a manually checked example metadata entry, profiling results and explicitly supplied source documents.

- Extract table/column names and observed types with Python.
- Preserve identifiers as strings when appropriate, including leading zeros.
- Validate proposed keys against profiling evidence; do not infer keys from names alone.
- Use source documentation for business descriptions.
- Leave undocumented meanings blank and report the gaps.
- Produce consistent YAML, following the checked example.
- Retain the extraction code for later deliveries.
- Use reviewed metadata to drive documentation or repetitive code generation.

**Outputs:** metadata per source, a technical extraction script and a list of unresolved descriptions/types.

**Acceptance check:** metadata matches the actual columns, preserves an identifier with leading zeros and leaves a deliberately undocumented field's description blank. Document-derived descriptions can be traced to their source.

**Optional scaling mechanic:** the video delegates independent sources to multiple agents. Parallelism is an optimisation, not a prerequisite; budget and review are still required. No such agents were launched for this extraction.

### REQ-07 — Generate an engineering toolkit from the project

**Evidence:** 20:38–24:56; `toolkit`.

The video presents an overview plus six tools:

1. **Architecture:** high-level layers and more detailed flows.
2. **Data lineage:** clickable upstream/downstream table dependencies.
3. **Call graph:** relationships between code functions.
4. **Data model:** conceptual entities and a more detailed star schema.
5. **Data quality:** checks and results across dates.
6. **Data catalogue:** searchable table/column inventory and descriptions.

The repository also supplies a separate **Runs** page and requires a rebuildable site-builder script. Those are useful companion additions, not a seventh tool explicitly toured in the video.

**Inputs:** metadata, transformation code, run/check results and reviewed project knowledge.

**Output:** a browsable engineering documentation site. The repository favours locally usable pages without runtime network fetches.

**Acceptance check:** choose a published table, trace it upstream, find the responsible transformation and inspect its quality results. Change a test input to the builder and confirm that rebuilding updates the documentation.

**Boundary:** diagrams and quality numbers must come from project evidence. A convincing visualisation is not proof that its dependency edges or statistics are correct.

### REQ-08 — Package data for consumers

**Evidence:** 24:56–26:32; `data-product`.

**Inputs:** a consumption-ready table/model, transformation SQL, metric definitions, quality results, releases and consumer requirements.

Provide:

- A discoverable product listing.
- Purpose, owner/audience, grain, freshness and service expectations.
- Access and getting-started guidance.
- A data model showing valid joins.
- Metric definitions and aggregation rules.
- Useful starter queries.
- Quality status and known limitations.
- Release notes and compatibility changes.
- A contract with consumers.

**Output:** a product entry with overview, guide, model, metrics, queries, quality, releases and contract.

**Acceptance check:** someone can answer a defined analytical question using the documentation and starter queries, with the expected result, without guessing join keys or metric definitions.

**Important distinction:** a source contract governs what enters the platform; a consumer contract governs what the platform promises to publish. The repository uses the Open Data Contract Standard, but the video does not teach its schema in detail.

### REQ-09 — Review changes against project standards

**Evidence:** 26:32–26:57; `pr-review`.

- Scope the diff or proposed change.
- Review security, correctness, duplicated logic and conformance to agreed standards/architecture.
- Report actionable findings rather than silently rewriting the change.

The repository extends the checklist with tests, data contracts, portability, rerun/backfill behaviour, performance, documentation and style. Findings include risk, file/line, the violated rule and a suggested change. Declined findings remain visible.

**Output:** a review report with a verdict.

**Acceptance check:** a deliberately faulty change is flagged with evidence. The reviewer does not push, merge or alter the change.

### REQ-10 — Review the whole platform using operational evidence

**Evidence:** 26:57–28:16; `big-review`.

**Inputs:** query history, storage/catalogue information, code, documents and quality results.

Assess:

- Most-used tables and slow queries.
- Data that appears unused during the observed period.
- Storage consumption and potential cost reductions.
- Unused functions, parameters, columns or SQL.
- Duplicated logic, outdated documentation and unnecessary complexity.
- Prioritised improvements with risk and effort.

The companion skill requests at least 90 days of query history for unused-data analysis and checks seasonal/reporting jobs. This is a caution against deleting something merely because nobody queried it yesterday.

**Output:** a platform review with proposals, not automatic clean-up.

**Acceptance check:** trace a usage/performance finding to its logs and observation period. Distinguish “not observed in these logs” from “safe to remove”. Use labelled simulated history if genuine long-running history is unavailable.

## 5. Concepts the eventual course needs to explain

| Concept | Meaning in this tutorial |
|---|---|
| Profiling versus validation | Profiling discovers characteristics and problems; validation tests agreed expectations |
| Schema versus semantics | Schema describes structure and types; semantics describes what data means |
| Schema drift | Structure changes across deliveries; compatibility depends on the change and consumer expectations |
| Data contract | An agreement about structure, delivery, quality, ownership and change handling |
| Technical metadata | Names, types, keys and other structural facts extracted or validated from data |
| Business metadata | Meaning, ownership and usage rules grounded in documentation and business knowledge |
| Data quality | Whether data meets its intended expectations, including completeness, uniqueness, validity and timeliness |
| Primary/foreign keys | Record identity and relationships; broken keys can cause missing matches or multiplied join results |
| Grain | Exactly what one row represents, such as an order versus an order line |
| Facts and dimensions | Measurements/events and their descriptive context in an analytical model |
| Semantic layer | Shared metric definitions so consumers calculate the same measure consistently |
| Lineage versus call graph | Lineage follows data dependencies; a call graph follows code execution relationships |
| Quarantine | Retain rejected inputs with reasons rather than silently discarding or publishing them |
| Root cause versus workaround | A cause explains the failure; a workaround restores useful service without necessarily removing the cause |
| Operational knowledge | Reviewed incident history and decisions, distinct from raw execution logs |
| Metadata-driven generation | Generate repeated code or documentation from a checked description of the system |
| Data as a product | Data supplied with discoverability, documentation, quality, access and clear consumer expectations |
| Human-in-the-loop AI | AI gathers evidence and proposes work; people retain responsibility for decisions and changes |

The video mentions data mesh in connection with data products. It does not demonstrate a complete data-mesh operating model, federated governance system or organisation-wide implementation.

## 6. Prerequisites and missing foundations

### Tools and materials evidenced by the tutorial

- VS Code and Claude Code for the author's working environment.
- SQL and Python for the underlying engineering work.
- YAML for metadata and incident knowledge.
- Source exports, including CSV in the metadata demonstration.
- Source documents, including a PDF, to ground business descriptions.
- HTML reports and interactive documentation.
- Git/GitHub for repository-based work, reviews and the scheduled workflow.

The companion examples also include XLSX, JSON and JSONL sources. They illustrate heterogeneity; we do not need every format in the first exercise.

### Foundations we must supply for a practical course [A]

Because the video starts with an existing platform, we will need:

1. A documented public source and a repeatable acquisition process.
2. Preserved raw inputs and at least two dated deliveries or labelled replay fixtures.
3. A small functioning SQL/Python pipeline across the chosen layers.
4. Related tables, documented keys, an explicit grain and an analytical output.
5. Execution logs and data-quality results, including a controlled failure.
6. A metadata example and enough source documentation to avoid inventing meanings.
7. A reviewed incident-history example to demonstrate knowledge reuse.
8. A genuine proposed code change for the review exercise.
9. Consumer queries and clearly labelled usage history for platform-review exercises.
10. Checks that prove results, not merely that commands finished.

Likely learner prerequisites are basic SQL selection/joins/aggregation, Python files/functions/errors, Git diffs and an understanding of tables, keys, types and nulls. The user's level has not yet been assessed.

No evidence makes Spark, Airflow, dbt, Docker, Databricks, AWS, Snowflake or a particular local database mandatory. Model brands/versions and multi-agent counts are not learning objectives. Choose those later against the desired fidelity, budget and machine constraints.

## 7. Requirements for the later dataset search

No replacement dataset has been researched or selected in this stage.

| Selection criterion | Why it matters |
|---|---|
| Publicly obtainable with clear reuse terms | We must be able to acquire, retain and use the data legitimately |
| Stable source, reproducible downloads and version/date information | Another run or learner must be able to reproduce an exercise |
| Related entities with usable keys | Enables joins, relationship checks, modelling and lineage |
| A documented event or observation grain | Makes counts and metrics defensible |
| Dates and repeated observations/deliveries | Enables freshness, missing-period checks, history and drift comparisons |
| At least one meaningful measure | Supports useful analytical questions and metric definitions |
| A data dictionary or authoritative source documentation | Supports evidence-based metadata; missing documentation must remain visible |
| Laptop-manageable subset | Keeps feedback quick without losing relational and temporal behaviour |
| Some realistic imperfections, or safe fault-injection fixtures | Makes profiling and incident exercises substantive |
| Minimal privacy risk | Public data is not automatically appropriate to expose to an AI service |
| A credible consumer use case | Allows the final output to be a useful data product, not an arbitrary table collection |

**Provisional scale, not a selection:** a few related tables and several dated batches are enough to begin. A second source can later test reuse. Do not copy the fictional demo's multi-million-row scale.

**Data provenance rule:** distinguish original source data, transformations, deliberately injected defects and simulated operational logs. Never present an injected schema change as a real change made by the publisher.

**Future discovery result:** a shortlist with authoritative URLs, licence/access notes, sample schema, join keys, date coverage, documentation, practical size and a mapping to these requirements. One giant clean CSV with no dictionary is unlikely to support the whole exercise on its own.

## 8. What is core, optional and not yet verified

### The seven featured skills

`profile`, `incident`, `metadata`, `toolkit`, `data-product`, `pr-review`, `big-review`.

The video calls the incident skill `/incidents`; the published repository calls it `/incident`. Preserve the concept rather than accidentally teaching two different skills.

### Repository-only extensions

`contract`, `quality`, `reconcile`, `impact`, `test-data`, `cost-review`, `docs`, `knowledge-refresh`, `migration`.

Some underlying concepts appear in the video, but these nine standalone workflows are not all demonstrated. They are possible later extensions, not requirements to implement immediately.

### Decisions to defer

- New dataset/domain and its actual licence, access and quality.
- Exact platform and database/storage engine.
- Exact Claude Code replication versus adapting the same workflows to Devin.
- Local-only execution versus a cloud-hosted scheduling exercise.
- AI access/cost limits and any permission to process source documentation remotely.
- Learner prerequisite gaps and lesson/exercise format.
- Whether the course should retain the two silver layers or introduce them progressively.

### Evidence and claim limits

- The full captions were reviewed, but not every video frame.
- Companion report numbers are fictional examples, not measured results from this workspace.
- The underlying platform's execution, performance and correctness could not be verified because it is not supplied.
- Documentation confirms the described cloud scheduling mechanism; account eligibility and access have not been tested.
- Automatic captions can mistranscribe names and model labels. No precise model/version requirement is inferred from them.
- There is no approved syllabus yet. The next step is to confirm this extraction's scope, then research data and turn the validated requirements into staged teaching.

## 9. Source index

- [Video and published chapter markers](https://www.youtube.com/watch?v=F5lZj1bQyUw)
- [Companion README at inspected commit](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/README.md)
- [Project instruction example](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/CLAUDE.md)
- [Profile skill](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/profile/SKILL.md)
- [Incident skill](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/incident/SKILL.md)
- [Metadata skill](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/metadata/SKILL.md)
- [Toolkit skill](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/toolkit/SKILL.md)
- [Data-product skill](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/data-product/SKILL.md)
- [PR-review skill](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/pr-review/SKILL.md)
- [Big-review skill](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/big-review/SKILL.md)
- [Example architecture](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/toolkit/references/architecture.html)
- [Example metadata](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/metadata/references/purchasing.yaml)
- [Example source contract](https://github.com/DataWithBaraa/claude-code-data-engineering-skills/blob/99bfe5b43c763f384adb5159e23c55e504681fb2/skills/contract/references/purchasing.odcs.yaml)
- [Claude Code feature comparison](https://code.claude.com/docs/en/features-overview)
- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Cloud scheduled tasks, formerly routines](https://code.claude.com/docs/en/routines)
- [Desktop scheduled tasks](https://code.claude.com/docs/en/desktop-scheduled-tasks)
