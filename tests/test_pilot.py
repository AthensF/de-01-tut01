"""Synthetic acquisition stubs for the bounded live-pilot orchestration."""
from datetime import date
import json

import pytest

from roadsafety import pilot
from roadsafety.fixtures import fixture_records


def acquisition():
    records = fixture_records()
    records["provenance"].update(run_id="synthetic-test", complete=True)
    return records


def test_pilot_profiles_and_preserves_evidence_without_publishing(tmp_path, monkeypatch):
    page_sizes = []
    def fetch(*args, **kwargs):
        page_sizes.append(kwargs["page_size"])
        return acquisition()
    monkeypatch.setattr(pilot, "acquire_live", fetch)
    result = pilot.run_pilot(tmp_path, date(2026, 10, 29), date(2026, 11, 1))
    assert result["raw_rows"] == {"crashes": 6, "vehicles": 6}
    assert result["required_rule_outcome"] == "passed"
    assert not result["production_publication_performed"]
    assert not (tmp_path / "published/manifest.json").exists()
    assert not (tmp_path / "warehouse.duckdb").exists()
    assert page_sizes == [500]
    assert (tmp_path / "reports/profile.html").exists()
    assert json.loads((tmp_path / "pilot-validation.json").read_text())["scope"] == "profiling_only"


def test_bad_records_are_profiled_but_fail_candidate_rules(tmp_path, monkeypatch):
    records = acquisition()
    records["crashes"][0].pop("number_of_persons_injured")
    monkeypatch.setattr(pilot, "acquire_live", lambda *args, **kwargs: records)
    result = pilot.run_pilot(tmp_path, date(2026, 10, 29), date(2026, 11, 1))
    assert result["quarantined_count"] == 1
    assert result["required_rule_outcome"] == "blocked"
    assert (tmp_path / "reports/profile.html").exists()


def test_bounds_and_incomplete_acquisition_are_not_successes(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "acquire_live", lambda *args, **kwargs: pytest.fail("must reject dates before network"))
    with pytest.raises(ValueError):
        pilot.run_pilot(tmp_path, date(2026, 1, 1), date(2026, 2, 1))
    records = acquisition()
    records["provenance"]["complete"] = False
    monkeypatch.setattr(pilot, "acquire_live", lambda *args, **kwargs: records)
    with pytest.raises(ValueError, match="Incomplete"):
        pilot.run_pilot(tmp_path, date(2026, 10, 29), date(2026, 11, 1))
    assert not (tmp_path / "raw").exists()
