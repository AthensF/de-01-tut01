import json
import subprocess
import sys
from pathlib import Path

from roadsafety.cli import main
from roadsafety.lessons import run_lesson, capstone


def test_installed_console_script_returns_success(tmp_path):
    command = Path(sys.executable).with_name("roadsafety")
    result = subprocess.run([str(command), "lesson", "2", "--data-dir", str(tmp_path)],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["dependencies"]["duckdb"] == "1.4.1"


def test_offline_verification_never_authorizes_live(tmp_path):
    report = run_lesson(1, tmp_path)
    assert report["status"] == "unverified"
    assert not (tmp_path / "source_verification.json").exists()


def test_cli_pipeline_and_human_incident_record(tmp_path, capsys):
    main(["pipeline", "--data-dir", str(tmp_path), "--mode", "fixture"])
    output = json.loads(capsys.readouterr().out)
    assert output["quality"]["collisions"] == 6
    main(["record-incident", "--data-dir", str(tmp_path), "--summary", "Reviewed synthetic repair", "--approve"])
    history = json.loads((tmp_path / "incidents/reviewed.json").read_text())
    assert history[0]["reviewer"] == "human"


def test_reviewed_incident_is_reused_by_incident_report(tmp_path):
    from roadsafety import reports
    from roadsafety.config import atomic_json
    from roadsafety.pipeline import run_pipeline
    run_pipeline(tmp_path)
    atomic_json(tmp_path / "runs" / "zz-failure.json", {
        "run_id": "zz-failure", "status": "failed", "started_at": "2099-01-01T00:00:00+00:00",
        "error": "missing required fields", "source_mode": "fixture"})
    main(["record-incident", "--data-dir", str(tmp_path), "--summary", "Reviewed missing required fields mapping", "--approve"])
    reports.incident(tmp_path)
    evidence = json.loads((tmp_path / "reports/incident.json").read_text())
    assert any("Reviewed missing" in str(item) for item in evidence["previous_incidents"])


def test_capstone_has_failure_preservation_and_verified_recovery(tmp_path):
    outcome = capstone(tmp_path)
    assert outcome["publication_preserved"]
    assert outcome["recovered"] and outcome["analytical_content_restored"]
    assert outcome["api_status"] == 200
    assert outcome["data_origin"] == "synthetic"


def test_acquisition_chapter_runs_once_and_live_never_falls_back(tmp_path, monkeypatch):
    from roadsafety import lessons
    calls = []
    def fake_run(path, mode="fixture", **kwargs):
        calls.append(mode)
        return {"version": "test", "quality": {}, "content_sha256": "hash"}
    monkeypatch.setattr(lessons, "run_pipeline", fake_run)
    run_lesson(5, tmp_path, live=True)
    assert calls == ["live"]
    calls.clear()
    # A live analytical chapter must invoke the live gate, not fixture bootstrap.
    try:
        run_lesson(3, tmp_path / "new", live=True)
    except FileNotFoundError:
        pass  # fake acquisition deliberately does not create raw inputs
    assert calls == ["live"]
