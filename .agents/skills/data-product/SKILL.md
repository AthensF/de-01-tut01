---
name: data-product
description: Document a published analytical dataset and API for consumers, including metric semantics, access, quality, freshness, and compatibility. Use before sharing the road-safety API or changing its consumer contract.
---

# Package data for consumers

## Inputs and permitted outputs

Read the published model/snapshot, metric definitions, API implementation, quality results, release information, and reviewed consumer requirements. This procedure may generate product documentation and a consumer-contract proposal. It must not deploy services, change API behaviour, publish snapshots, or invent ownership/service promises.

Run from the repository root:

```bash
python -m roadsafety data-product --data-dir data
```

If the CLI version does not expose this command, inspect `python -m roadsafety --help` and report the missing integration rather than silently substituting an unrelated report.

## Procedure

1. Identify the product, intended questions, audience, data version, and source mode. A fixture result is not live NYC data.
2. Explain each model's row grain and valid join keys. Keep crash counts/injury totals separate from vehicle involvement so consumers do not multiply measures across one-to-many joins.
3. Define filters, aggregation rules, missing/unknown categories, observation coverage, and exclusions. Reported collisions are not exposure-adjusted road risk.
4. Provide the API entry point, parameter constraints, executable starter queries/client commands, expected result shape, and how to read version/freshness metadata. Use only a verified deployed URL; otherwise identify local instructions as local.
5. Describe acquisition time, reporting window, reconciliation policy, quality status, and known limitations separately. Do not equate a successful request with a complete recent source refresh.
6. Include releases, compatibility changes, and a proposed consumer contract. Distinguish it from the source contract that governs incoming records. Leave unassigned owner or unsupported service guarantees unresolved.

## Evidence and completion

Return the documentation path and a reproducible consumer question. Verify its result against the published snapshot using an independent query. Do not claim external accessibility without a successful external request.
