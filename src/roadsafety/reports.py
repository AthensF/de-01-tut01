"""Evidence-based reports used by the course and its reusable AI procedures.

Python computes facts before a model is asked to interpret them. Reports never
change source rows, repair pipelines, append incident history, or send messages.
"""

from __future__ import annotations

import ast
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import time
from typing import Any

import duckdb
import yaml


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime, Path)):
        return str(value)
    raise TypeError(type(value).__name__)


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _manifest(data_dir: Path) -> dict:
    return _read_json(data_dir / "published" / "manifest.json", {})


def _provenance(data_dir: Path) -> dict:
    manifest = _manifest(data_dir)
    batches = _raw_batches(data_dir)
    batch_evidence = _read_json(batches[-1] / "provenance.json", {}) if batches else {}
    mode = manifest.get("source_mode", batch_evidence.get("source_mode", "unknown"))
    return {
        "source_mode": mode,
        "data_origin": "synthetic" if mode == "fixture" else mode,
        "data_version": manifest.get("version"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_verification": _read_json(data_dir / "source_verification.json", {}).get("status", "unverified"),
    }


_STYLE = """
body{font:16px/1.55 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#172b3a}
a{color:#075f9a}h1,h2{line-height:1.2}pre{background:#f1f5f8;padding:1rem;overflow:auto;font-size:13px}
table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{border:1px solid #ccd7de;padding:.45rem;text-align:left}
.note{background:#fff6d9;padding:1rem;border-left:4px solid #b67c00}nav{display:flex;flex-wrap:wrap;gap:1rem}
input{font:inherit;padding:.5rem;width:90%}footer{margin-top:3rem;color:#526777}code{font-size:.9em}
"""


def _page(title: str, body: str, provenance: dict | None = None) -> str:
    note = ""
    if provenance:
        mode = provenance.get("data_origin", provenance.get("source_mode", "unknown"))
        note = f'<p class="note">Data origin: <strong>{html.escape(str(mode))}</strong>. '
        note += "Synthetic fixtures are teaching inputs, not observations from NYC. " if mode == "synthetic" else ""
        note += f'Publication: {html.escape(str(provenance.get("data_version") or "not published"))}.</p>'
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        f'<title>{html.escape(title)}</title><style>{_STYLE}</style><body><h1>{html.escape(title)}</h1>'
        f'{note}{body}<footer>Generated from project evidence; review interpretations before acting.</footer></body></html>'
    )


def _evidence_block(value: Any) -> str:
    return "<pre>" + html.escape(json.dumps(value, indent=2, default=_json_default)) + "</pre>"


def _report(data_dir: Path, name: str, title: str, evidence: dict, intro: str = "") -> Path:
    output = data_dir / "reports" / f"{name}.html"
    _write_json(output.with_suffix(".json"), evidence)
    output.write_text(_page(title, f"<p>{html.escape(intro)}</p>" + _evidence_block(evidence), evidence.get("provenance")), encoding="utf-8")
    return output


def _raw_batches(data_dir: Path) -> list[Path]:
    raw = data_dir / "raw"
    batches = [p for p in raw.iterdir() if p.is_dir() and (p / "crashes.json").exists()] if raw.exists() else []
    return sorted(batches, key=lambda p: (p.stat().st_mtime_ns, p.name))


def _records(path: Path) -> list[dict]:
    value = _read_json(path, [])
    if isinstance(value, dict):
        value = value.get("records", value.get("rows", []))
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"Expected an array of objects in {path}")
    return value


def _null(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _observed_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"  # Never destroy leading zeros by guessing a numeric type.
    return type(value).__name__


def _table_profile(rows: list[dict], key: str) -> dict:
    columns = sorted({column for row in rows for column in row})
    key_counts = Counter(str(row[key]) for row in rows if not _null(row.get(key)))
    duplicate_rows = sum(n - 1 for n in Counter(json.dumps(row, sort_keys=True) for row in rows).values())
    stats = {}
    for column in columns:
        values = [row.get(column) for row in rows]
        nonnull = [v for v in values if not _null(v)]
        stats[column] = {
            "null_or_empty": sum(_null(v) for v in values),
            "absent_field": sum(column not in row for row in rows),
            "observed_json_types": sorted({_observed_type(v) for v in values}),
            "distinct_nonnull": len({json.dumps(v, sort_keys=True) for v in nonnull}),
            "constant_nonnull": len({json.dumps(v, sort_keys=True) for v in nonnull}) == 1,
            "potential_sensitive_field": bool(re.search(r"(?:^|_)(?:name|address|email|phone)(?:_|$)", column, re.I)),
        }
    dates, invalid_dates = [], 0
    for row in rows:
        if _null(row.get("crash_date")):
            continue
        try:
            dates.append(date.fromisoformat(str(row["crash_date"])[:10]))
        except ValueError:
            invalid_dates += 1
    counts = {}
    for field in ("number_of_persons_injured", "number_of_persons_killed"):
        if field not in columns:
            continue
        invalid = negative = fractional = 0
        for row in rows:
            try:
                value = float(row[field])
                if not math.isfinite(value):
                    raise ValueError("not finite")
                negative += value < 0
                fractional += not value.is_integer()
            except (KeyError, TypeError, ValueError, OverflowError):
                invalid += 1
        counts[field] = {"not_a_finite_number": invalid, "negative": negative, "fractional": fractional,
                         "rule_basis": "Course contract expects nonnegative whole-person counts; verify publisher semantics separately."}
    numeric_key_groups: dict[str, set[str]] = {}
    for value in key_counts:
        if re.fullmatch(r"\d+", value):
            numeric_key_groups.setdefault(str(int(value)), set()).add(value)
    return {
        "rows": len(rows), "columns": columns,
        "schema_fingerprint": hashlib.sha256(json.dumps(columns).encode()).hexdigest(),
        "duplicate_rows": duplicate_rows,
        "candidate_key": {"field": key, "missing": sum(_null(row.get(key)) for row in rows),
                          "distinct_nonnull": len(key_counts), "duplicate_records": sum(n - 1 for n in key_counts.values()),
                          "validated_unique": len(key_counts) == len(rows)},
        "column_statistics": stats,
        "dates": {"min_observed_crash_date": min(dates) if dates else None,
                  "max_observed_crash_date": max(dates) if dates else None,
                  "invalid_iso_date_values": invalid_dates,
                  "interpretation": "Event dates are not acquisition dates or proof of delivery completeness."},
        "count_checks": counts,
        "identifier_checks": {"leading_zero_records": sum(n for value, n in key_counts.items() if len(value) > 1 and value.startswith("0")),
                              "distinct_keys_collapsing_if_cast_to_integer": sum(len(values) - 1 for values in numeric_key_groups.values()),
                              "interpretation": "Identifiers remain strings; apparent numeric equivalence is a review question, not an automatic merge."},
    }


def profile(data_dir: Path) -> Path:
    """Compute a profile of the newest acquired batch without changing inputs."""
    data_dir = Path(data_dir)
    batches = _raw_batches(data_dir)
    if not batches:
        raise FileNotFoundError("No raw batches. Run the fixture or live pipeline first.")
    batch = batches[-1]
    rows = {name: _records(batch / f"{name}.json") for name in ("crashes", "vehicles")}
    tables = {name: _table_profile(records, "collision_id" if name == "crashes" else "unique_id") for name, records in rows.items()}
    parent_keys = {str(row["collision_id"]) for row in rows["crashes"] if not _null(row.get("collision_id"))}
    orphans = sum(not _null(row.get("collision_id")) and str(row["collision_id"]) not in parent_keys for row in rows["vehicles"])
    changes = {}
    if len(batches) > 1:
        for name in tables:
            previous = _records(batches[-2] / f"{name}.json")
            old = {column for row in previous for column in row}
            new = set(tables[name]["columns"])
            changes[name] = {"added": sorted(new - old), "removed": sorted(old - new)}
    evidence = {"provenance": _provenance(data_dir), "batch": batch.name, "tables": tables,
                "relationships": {"vehicle_records_without_parent_in_this_batch": orphans,
                                  "interpretation": "A batch-local orphan is not proof the source is corrupt; inspect acquisition windows and retained history."},
                "schema_changes": changes,
                "limitations": ["JSON value types are observed facts, not a publisher guarantee.",
                                "No sensitive values are included in this report.",
                                "Daily cadence and freshness expectations require source documentation."]}
    return _report(data_dir, "profile", "Source profiling", evidence, "Counts come from the acquired files. Discoveries become validation rules only after review.")


def _documented_columns(data_dir: Path) -> dict:
    """Accept descriptions only with an explicit documentary source."""
    checked = _read_json(data_dir / "source_documents.json", {})
    evidence = _read_json(data_dir / "source_verification.json", {})
    results: dict[str, dict] = {"crashes": {}, "vehicles": {}}
    for name in results:
        table = checked.get(name, {})
        for field, item in table.items():
            if isinstance(item, dict) and item.get("source") and item.get("description"):
                results[name][field] = {"description": item["description"], "source": item["source"]}
    datasets = evidence.get("sources", evidence.get("datasets", {}))
    if isinstance(datasets, list):
        datasets = {item.get("name", ""): item for item in datasets}
    if isinstance(datasets, dict):
        for name, dataset in datasets.items():
            if name not in results or not isinstance(dataset, dict):
                continue
            metadata = dataset.get("metadata", dataset)
            for field, item in dataset.get("column_descriptions", {}).items():
                if isinstance(item, dict) and item.get("description") and item.get("source"):
                    results[name][field] = {"description": item["description"], "source": item["source"]}
            for column in metadata.get("columns", []):
                if not isinstance(column, dict):
                    continue
                field = column.get("fieldName")
                if field and column.get("description"):
                    results[name][field] = {"description": column["description"], "source": dataset.get("metadata_url", dataset.get("url", "downloaded source metadata"))}
    return results


def metadata(data_dir: Path) -> Path:
    data_dir = Path(data_dir)
    profile(data_dir)
    facts = _read_json(data_dir / "reports" / "profile.json")
    descriptions = _documented_columns(data_dir)
    sources = {}
    for name, table in facts["tables"].items():
        columns = []
        for field in table["columns"]:
            doc = descriptions[name].get(field, {})
            columns.append({"name": field, "observed_json_types": table["column_statistics"][field]["observed_json_types"],
                            "description": doc.get("description", ""), "description_source": doc.get("source", ""),
                            "description_status": "documented" if doc else "unknown"})
        sources[name] = {"grain": "unconfirmed until contract review", "candidate_key": table["candidate_key"], "columns": columns}
    result = {"provenance": facts["provenance"], "sources": sources,
              "unresolved": [{"table": name, "column": col["name"]} for name, table in sources.items() for col in table["columns"] if col["description_status"] == "unknown"]}
    output = data_dir / "reports" / "metadata.yaml"
    output.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    _report(data_dir, "metadata", "Evidence-based metadata", result, "Blank business descriptions are intentional gaps, not invitations to invent meaning.")
    return output


def _runs(data_dir: Path) -> list[dict]:
    directory = data_dir / "runs"
    values = []
    for file in sorted(directory.glob("*.json")) if directory.exists() else []:
        item = _read_json(file)
        if isinstance(item, dict):
            values.append({**item, "evidence_file": str(file.relative_to(data_dir))})
    return sorted(values, key=lambda r: (str(r.get("started_at", "")), str(r.get("run_id", ""))))


def incident(data_dir: Path) -> Path:
    data_dir = Path(data_dir)
    runs = _runs(data_dir)
    failures = [r for r in runs if r.get("status") in {"failed", "failure"}]
    failure = failures[-1] if failures else None
    history_path = data_dir / "knowledge" / "incidents.yaml"
    history = _read_json(data_dir / "incidents" / "reviewed.json", [])
    if not isinstance(history, list):
        history = []
    if history_path.exists():
        legacy = yaml.safe_load(history_path.read_text())
        if isinstance(legacy, list):
            history.extend(legacy)
    error = str(failure.get("error", "")) if failure else ""
    similar = [item for item in (history or []) if isinstance(item, dict) and any(word in str(item).lower() for word in re.findall(r"[a-z_]{5,}", error.lower()))]
    schema_suspected = bool(re.search(r"schema|column|missing|required|rename", error, re.I))
    evidence = {"provenance": _provenance(data_dir), "status": "investigation_required" if failure else "no_failed_run",
                "failed_run": failure, "latest_run": runs[-1] if runs else None,
                "last_publication": _manifest(data_dir), "previous_incidents": similar,
                "root_cause_status": "unconfirmed; compare raw inputs, contracts and failing code" if failure else "not applicable",
                "candidate_cause": "Required-field or schema incompatibility; verify against the captured error and batch." if schema_suspected else "Read captured failure evidence before attributing cause.",
                "fix_options": [] if not failure else [
                    {"option": "targeted correction", "action": "Review the failing mapping or operation and test a minimal correction against the same captured batch.", "tradeoff": "Fast recovery; inspect related mappings for the same exposure."},
                    {"option": "preventive change", "action": "Add a contract regression case and quarantine incompatible batches before publication.", "tradeoff": "Preserves the last good publication; freshness must remain visible."}],
                "consumer_draft": "The latest refresh failed. Check the published data version and acquisition time before using results; the last successful publication is retained." if failure else "No failing run was found.",
                "source_owner_draft": "Please confirm the documented fields and change policy. Attach reviewed field-level evidence from the failed batch; do not include credentials." if failure else "Not required.",
                "history_update": "Proposed only. Append a reviewed entry after a verified rerun; this command never changes history.",
                "actions_executed": ["read evidence", "write report"], "automatic_fix_or_send": False}
    return _report(data_dir, "incident", "Incident investigation", evidence, "A failed run is evidence, not a complete root-cause diagnosis. Communications below are drafts.")


def _database(data_dir: Path) -> Path:
    warehouse = data_dir / "warehouse.duckdb"
    if warehouse.exists():
        return warehouse
    manifest = _manifest(data_dir)
    filename = manifest.get("database", "")
    path = data_dir / "published" / filename
    if filename and Path(filename).name == filename and path.is_file():
        return path
    raise FileNotFoundError("No warehouse or published snapshot. Run the pipeline first.")


def _table_name(connection, choices: tuple[str, ...]) -> str | None:
    found = {f"{schema}.{name}" for schema, name in connection.execute("SELECT table_schema, table_name FROM information_schema.tables").fetchall()}
    return next((name for name in choices if name in found), None)


def _tables(connection) -> list[dict]:
    values = []
    for schema, name in connection.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('information_schema','pg_catalog') ORDER BY 1,2").fetchall():
        quoted = '"' + schema.replace('"', '""') + '"."' + name.replace('"', '""') + '"'
        count = connection.execute(f"SELECT count(*) FROM {quoted}").fetchone()[0]
        columns = connection.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position", [schema, name]).fetchall()
        values.append({"table": f"{schema}.{name}", "rows": count, "columns": [{"name": col, "type": dtype} for col, dtype in columns]})
    return values


def _call_graph() -> dict:
    root = Path(__file__).parent
    nodes, edges = [], []
    for file in sorted(root.glob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            caller = f"{file.stem}.{node.name}"
            nodes.append({"function": caller, "file": file.name, "line": node.lineno})
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    target = ast.unparse(child.func)
                    if isinstance(child.func, ast.Name) or (isinstance(child.func, ast.Attribute) and not target.startswith(("self.", "connection.", "conn."))):
                        edges.append({"caller": caller, "called_expression": target, "line": child.lineno})
    return {"nodes": nodes, "edges": edges, "limitations": "Static call expressions, not a runtime trace; dynamic dispatch is unresolved."}


def _lineage(data_dir: Path, tables: list[dict]) -> dict:
    manifest = _manifest(data_dir)
    documented = manifest.get("lineage", {})
    if documented:
        return {"edges": [{"downstream": target, "upstream": origin} for target, sources in documented.items() for origin in sources],
                "evidence": "published manifest lineage emitted by the pipeline"}
    edges = []
    for source in sorted(Path(__file__).parent.glob("*.py")):
        text = source.read_text(encoding="utf-8")
        for match in re.finditer(r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW)\s+(\w+\.\w+|\w+)\s+(?:AS\s+)?(.*?)(?=;|CREATE\s|$)", text, re.I | re.S):
            for upstream in re.findall(r"(?:FROM|JOIN)\s+(\w+\.\w+|\w+)", match.group(2), re.I):
                if upstream != match.group(1):
                    edges.append({"downstream": match.group(1), "upstream": upstream, "source_file": source.name})
    return {"edges": edges, "evidence": "conservative static SQL extraction", "limitations": "Dynamic SQL and dependencies not present in code are unresolved; no edges invented.", "observed_tables": [t["table"] for t in tables]}


def _anchor(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)


def _searchable_section(title: str, content: str, identity: str | None = None) -> str:
    identifier = f' id="{html.escape(_anchor(identity or title))}"'
    return f'<section class="entry"{identifier}><h2>{html.escape(title)}</h2>{content}</section>'


def _toolkit_body(name: str, evidence: dict, tables: list[dict], data_dir: Path) -> str:
    if name == "catalogue":
        sections = []
        for table in tables:
            columns = "<table><tr><th>Column</th><th>SQL type</th></tr>" + "".join(f'<tr><td>{html.escape(c["name"])}</td><td>{html.escape(c["type"])}</td></tr>' for c in table["columns"]) + "</table>"
            sections.append(_searchable_section(table["table"], f'<p>{table["rows"]} measured rows. <a href="lineage.html#{_anchor(table["table"])}">Trace dependencies</a></p>' + columns, table["table"]))
        sections.append(_searchable_section("Documented raw-source meanings", _evidence_block(evidence)))
        return "".join(sections)
    if name == "lineage":
        edges = evidence.get("edges", [])
        all_names = sorted({t["table"] for t in tables} | {e["upstream"] for e in edges} | {e["downstream"] for e in edges})
        body = "<p>Recorded dependencies are clickable. Select a table, then inspect its columns, responsible transformation, and quality history.</p>"
        for table in all_names:
            upstream = sorted({e["upstream"] for e in edges if e["downstream"] == table})
            downstream = sorted({e["downstream"] for e in edges if e["upstream"] == table})
            def links(names):
                return ", ".join(f'<a href="#{_anchor(item)}">{html.escape(item)}</a>' for item in names) or "None recorded"
            body += _searchable_section(table, f'<p>Upstream: {links(upstream)}</p><p>Downstream: {links(downstream)}</p><p><a href="catalogue.html#{_anchor(table)}">Columns</a> · <a href="architecture.html#transformations">Transformation SQL</a> · <a href="quality.html">Quality results</a></p>', table)
        return body + _searchable_section("Lineage evidence", _evidence_block(evidence))
    if name == "call-graph":
        sections = []
        for node in evidence.get("nodes", []):
            calls = [e for e in evidence.get("edges", []) if e["caller"] == node["function"]]
            content = f'<p>Source: {html.escape(node["file"])}:{node["line"]}</p>' + _evidence_block(calls)
            sections.append(_searchable_section(node["function"], content))
        return '<p>Static call expressions, not a runtime execution trace. Dynamic dispatch remains unresolved.</p>' + "".join(sections)
    if name == "runs":
        return "".join(_searchable_section(str(run.get("run_id", "unknown")), _evidence_block(run), str(run.get("run_id", "unknown"))) for run in evidence.get("runs", [])) or "<p>No execution history was found.</p>"
    body = _searchable_section(name.replace("-", " ").title(), _evidence_block(evidence))
    if name == "architecture":
        sql_path = data_dir / "transformations.sql"
        content = '<pre>' + html.escape(sql_path.read_text(encoding="utf-8")) + '</pre>' if sql_path.exists() else "<p>No persisted transformation SQL was found. Consult pipeline.py; no SQL is invented here.</p>"
        body += _searchable_section("Transformations", content, "transformations")
    return body


def toolkit(data_dir: Path) -> Path:
    data_dir = Path(data_dir)
    metadata_path = metadata(data_dir)
    with duckdb.connect(str(_database(data_dir)), read_only=True) as connection:
        tables = _tables(connection)
    runs = _runs(data_dir)
    provenance = _provenance(data_dir)
    manifest = _manifest(data_dir)
    graph = _call_graph()
    lineage = _lineage(data_dir, tables)
    catalogue = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    model = {"tables": tables, "confirmed_relationships": [], "caution": "Candidate relationships require key and orphan checks; the catalogue does not itself prove joins are valid."}
    core_names = {t["table"] for t in tables}
    if {"silver_core.crashes", "silver_core.vehicles"} <= core_names:
        model["confirmed_relationships"].append({"parent": "silver_core.crashes.collision_id", "child": "silver_core.vehicles.collision_id", "cardinality": "one-to-many", "evidence": "pipeline core model; validate relationship counts in profiling and quality results"})
    pages = {
        "architecture": {"actual_tables": tables, "pipeline_lineage": lineage, "publication": manifest},
        "lineage": lineage, "call-graph": graph, "model": model,
        "quality": {"publication_quality": manifest.get("quality", {}), "run_history": [{"run_id": r.get("run_id"), "status": r.get("status"), "quality": r.get("quality", {})} for r in runs]},
        "catalogue": catalogue, "runs": {"runs": runs},
    }
    directory = data_dir / "reports" / "toolkit"
    directory.mkdir(parents=True, exist_ok=True)
    links = '<nav><a href="index.html">Overview</a>' + "".join(f'<a href="{name}.html">{html.escape(name.replace("-", " ").title())}</a>' for name in pages) + "</nav>"
    for name, evidence in pages.items():
        _write_json(directory / f"{name}.json", evidence)
        search = '<p><label>Find in this page <input id="search" placeholder="Table, column, function, or run"></label></p>'
        script = '<script>document.getElementById("search").addEventListener("input",function(){const q=this.value.toLowerCase();document.querySelectorAll(".entry").forEach(function(s){s.hidden=q&&!s.textContent.toLowerCase().includes(q);});});</script>'
        (directory / f"{name}.html").write_text(_page(name.replace("-", " ").title(), links + search + _toolkit_body(name, evidence, tables, data_dir) + script, provenance), encoding="utf-8")
    index = directory / "index.html"
    index.write_text(_page("Engineering toolkit", links + "<p>Explore actual tables, their recorded dependencies, responsible code, metadata, quality results, and execution history. Rebuild after each publication.</p>" + _evidence_block({"tables": len(tables), "runs": len(runs), "generated_at": provenance["generated_at"]}), provenance), encoding="utf-8")
    return index


_SEEDED_DIFF = """diff --git a/sql/unsafe_summary.sql b/sql/unsafe_summary.sql
--- a/sql/unsafe_summary.sql
+++ b/sql/unsafe_summary.sql
@@ -0,0 +1,4 @@
+SELECT c.borough, SUM(c.injured) AS injured
+FROM silver_core.crashes c
+JOIN silver_core.vehicles v USING (collision_id)
+GROUP BY c.borough;
"""


def review(data_dir: Path, diff_path: Path | None = None) -> Path:
    data_dir = Path(data_dir)
    text = Path(diff_path).read_text(encoding="utf-8") if diff_path else _SEEDED_DIFF
    added = []
    filename, line = "unknown", 0
    for value in text.splitlines():
        if value.startswith("+++ "):
            filename = value[4:].removeprefix("b/")
        elif value.startswith("@@"):
            match = re.search(r"\+(\d+)", value)
            line = int(match.group(1)) - 1 if match else line
        elif value.startswith("+"):
            line += 1
            added.append({"file": filename, "line": line, "code": value[1:]})
        elif not value.startswith("-"):
            line += 1
    joined = "\n".join(row["code"] for row in added)
    findings = []
    if re.search(r"sum\s*\([^)]*(?:injured|killed)", joined, re.I) and re.search(r"join\s+(?:silver_core\.)?vehicles", joined, re.I):
        location = next(row for row in added if re.search(r"sum\s*\(", row["code"], re.I))
        findings.append({"risk": "high", "file": location["file"], "line": location["line"], "rule": "Aggregate crash measures at crash grain before joining one-to-many vehicle records.",
                         "evidence": location["code"], "finding": "The join can multiply injury or fatality totals for crashes involving several vehicles.",
                         "suggestion": "Calculate crash totals from the crash fact; aggregate vehicle involvement independently and combine compatible aggregates."})
    if re.search(r"except\s*:\s*(?:pass|continue)|except\s+Exception\s*:\s*pass", joined, re.I):
        findings.append({"risk": "high", "file": filename, "line": None, "rule": "Acquisition failures cannot be silently converted into complete batches.", "evidence": "bare or broad exception suppressed", "suggestion": "Record the failure and prevent publication of incomplete evidence."})
    evidence = {"provenance": _provenance(data_dir), "review_origin": "supplied_diff" if diff_path else "labelled_synthetic_fault_fixture",
                "diff_sha256": hashlib.sha256(text.encode()).hexdigest(), "findings": findings,
                "verdict": "changes_requested" if findings else "manual_review_required",
                "limitations": "This deterministic baseline catches selected course defects; it is not a complete security or correctness review.",
                "declined_findings": [], "repository_changes_made": False}
    return _report(data_dir, "review", "Change review", evidence, "Review findings identify evidence and suggested changes. This procedure never edits, pushes, or merges the change.")


def platform_review(data_dir: Path) -> Path:
    data_dir = Path(data_dir)
    database = _database(data_dir)
    measurements = []
    with duckdb.connect(str(database), read_only=True) as connection:
        tables = _tables(connection)
        gold = _table_name(connection, ("main.gold_daily", "gold.gold_daily", "gold.daily"))
        queries = ["SELECT count(*) FROM information_schema.tables"]
        if gold:
            queries += [f"SELECT SUM(collisions), SUM(injured), SUM(killed) FROM {gold}",
                        f"SELECT borough, SUM(collisions) FROM {gold} GROUP BY borough ORDER BY 2 DESC"]
        for query in queries:
            started = time.perf_counter()
            result = connection.execute(query).fetchall()
            measurements.append({"sql": query, "elapsed_ms": round((time.perf_counter() - started) * 1000, 4), "result_rows": len(result), "workload_origin": "controlled_benchmark"})
    history = _read_json(data_dir / "query_history.json", [])
    evidence = {"provenance": _provenance(data_dir), "database": database.name, "database_bytes": database.stat().st_size,
                "tables": tables, "measurements": measurements, "query_history": history,
                "observation_period": "This invocation only; no 90-day consumer history is asserted.",
                "usage_conclusion": "Controlled benchmark usage does not demonstrate which tables friends use or which tables are safe to remove.",
                "improvements": [{"priority": "review", "proposal": "Compare repeated benchmark runs and actual consumer evidence before changing storage or indexes.",
                                  "risk": "A single timing is noisy; unobserved usage does not establish disuse.", "effort": "small", "automatic_deletion": False}]}
    return _report(data_dir, "platform-review", "Platform review", evidence, "Performance and storage measurements are real; the workload is explicitly a controlled benchmark.")


def data_product(data_dir: Path) -> Path:
    data_dir = Path(data_dir)
    manifest = _manifest(data_dir)
    with duckdb.connect(str(_database(data_dir)), read_only=True) as connection:
        gold = _table_name(connection, ("main.gold_daily", "gold.gold_daily", "gold.daily"))
        if not gold:
            raise ValueError("No daily gold aggregate found")
        sql = f"SELECT SUM(collisions) AS collisions, SUM(injured) AS injured, SUM(killed) AS killed FROM {gold}"
        totals = connection.execute(sql).fetchone()
    evidence = {"provenance": _provenance(data_dir), "name": "Reported NYC collision summaries", "audience": "Friends and learners querying public aggregate endpoints",
                "owner": "Project maintainer", "grain": "One observation date and borough per daily aggregate; UNKNOWN geography remains included in overall totals.",
                "window": {"start": manifest.get("window_start"), "end": manifest.get("window_end")},
                "metrics": {"collisions": "Count of accepted crash records, not vehicle rows.", "injured": "Sum of accepted per-crash injury counts.", "killed": "Sum of accepted per-crash fatality counts."},
                "starter_query": sql, "starter_query_result": dict(zip(("collisions", "injured", "killed"), totals)),
                "api": ["GET /v1/collisions/summary", "GET /v1/collisions/trends", "GET /v1/vehicles/summary", "GET /v1/data-status", "GET /docs"],
                "consumer_contract": {"version": 1, "access": "public, read-only, bounded analytical requests", "freshness": "Check data-status and response metadata; daily acquisition is a goal, not real-time completeness.",
                                      "compatibility": "Version breaking API changes; include data_version and source_mode in responses.", "quality": manifest.get("quality", {})},
                "releases": [{"version": manifest.get("version"), "generated_at": manifest.get("generated_at"), "schema_version": manifest.get("schema_version")}],
                "limitations": ["Counts do not establish exposure-adjusted road risk.", "Source reports may be late or corrected; reconciliation dates matter.", "Missing geography is explicit, not silently discarded.", "Synthetic publications do not describe actual NYC events."]}
    _write_json(data_dir / "reports" / "consumer-contract.json", evidence["consumer_contract"])
    return _report(data_dir, "data-product", "Road-safety data product", evidence, "Use the provided metrics and queries without guessing joins, accounting for the published data origin and version.")
