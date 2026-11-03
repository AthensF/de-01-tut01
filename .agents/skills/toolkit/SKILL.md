---
name: toolkit
description: Rebuild an engineering documentation site from the actual project, metadata, pipeline results, and published data. Use to inspect architecture, lineage, code relationships, catalogue, and quality history.
---

# Generate the engineering toolkit

## Inputs and permitted outputs

Read pipeline code, metadata/contracts, database catalogue, run records, quality results, and publication manifests. This procedure may rebuild generated documentation. It must not alter source data, pipeline behaviour, or publication state.

Run from the repository root:

```bash
python -m roadsafety toolkit --data-dir data
```

## Procedure

1. Identify the evidence version and source mode. Ensure synthetic observations and simulated histories are visible as such throughout generated pages.
2. Build architecture and lineage from actual implemented layers and transformations. Do not add aspirational dependencies to a diagram presented as the running system.
3. Generate or inspect the code call graph, conceptual/data model, searchable table/column catalogue, run history, and quality results. Label declared dependencies separately from statically discovered edges when their provenance differs.
4. Link data objects to responsible transformations, their grain/key expectations, and relevant quality results. State missing evidence rather than filling the page with invented descriptions or numbers.
5. Keep pages locally readable and self-contained; no runtime network requests or remote scripts are needed to inspect evidence. Escape source values before rendering HTML.
6. Rebuild after a controlled metadata or report-input change and verify the page reflects that change. Generated documentation must be reproducible from retained inputs.

## Evidence and completion

Return the generated entry-page path and evidence limitations. Trace one published measure upstream through its table, transformation, source batch, and quality result. A rendered diagram alone is not evidence that its edges or statistics are correct.
