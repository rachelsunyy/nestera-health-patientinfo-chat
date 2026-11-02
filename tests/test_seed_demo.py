"""The demo seed script: scenario outcomes, idempotence, and isolation from non-demo data."""

import json
from datetime import datetime
from pathlib import Path

from agents.patient_agent import PatientAgent
from scripts import seed_demo

NOW = datetime.now().replace(hour=15, minute=0)

# patient: (check-ins, today, latest action, trend)
EXPECTED = {
    "demo_pneumonia": (5, 1, "Escalate", "Worsening"),
    "demo_heartfailure": (4, 1, "Routine review", "Stable"),
    "demo_diabetes": (5, 1, "Routine review", "Improving"),
    "demo_copd": (3, 0, "Routine review", "Stable"),
    "demo_twice": (3, 2, "Schedule visit", "Worsening"),
    "demo_live": (2, 0, "Routine review", "Stable"),
}


def snapshot(data_dir: Path) -> dict[str, object]:
    """Every file under data_dir; summaries without their generation time, which is always 'now'."""
    files = {}
    for f in sorted(data_dir.rglob("*.json")):
        data = json.loads(f.read_text())
        if f.parent.name == "summaries":
            data.pop("generated_at")
        files[str(f.relative_to(data_dir))] = data
    return files


def test_each_scenario_gets_its_expected_action_and_trend(db, tmp_path):
    rows = seed_demo.seed(tmp_path, now=NOW)
    got = {r["patient"]: (r["check-ins"], r["today"], r["latest action"], r["trend"]) for r in rows}
    assert got == EXPECTED


def test_pneumonia_trend_raises_yesterday_before_any_threshold_is_crossed(db, tmp_path):
    seed_demo.seed(tmp_path, now=NOW)
    yesterday = db.get_recent_checkins("demo_pneumonia", n=2)[1]
    summary = db.get_summary("demo_pneumonia", yesterday.id)
    assert summary.recommended_action == "Schedule visit"
    assert [f.split(":")[0] for f in summary.flagged_items] == ["Worsening trend"]


def test_rerun_converges_and_reset_removes_stray_demo_patients(db, tmp_path):
    seed_demo.seed(tmp_path, now=NOW)
    first = snapshot(tmp_path)

    live = PatientAgent("demo_live", db)
    live.start_session()
    done = False
    while not done:
        _, done = live.respond("Fine")
    (tmp_path / "demo_retired").mkdir()

    seed_demo.seed(tmp_path, now=NOW)
    assert (tmp_path / "demo_retired").is_dir()
    assert snapshot(tmp_path) == first

    seed_demo.seed(tmp_path, reset=True, now=NOW)
    assert not (tmp_path / "demo_retired").exists()
    assert snapshot(tmp_path) == first


def test_non_demo_patients_are_untouched(db, tmp_path):
    agent = PatientAgent("patient_001", db)
    agent.start_session()
    done = False
    while not done:
        _, done = agent.respond("Fine")
    (tmp_path / "demonstration").mkdir()
    before = snapshot(tmp_path)

    seed_demo.seed(tmp_path, reset=True, now=NOW)

    after = {k: v for k, v in snapshot(tmp_path).items() if not k.startswith("demo_")}
    assert after == before
    assert (tmp_path / "demonstration").is_dir()


def test_cli_prints_the_summary_table(db, tmp_path, capsys):
    seed_demo.main(["--data-dir", str(tmp_path), "--reset"])
    out = capsys.readouterr().out
    assert "demo_pneumonia     Walter Briggs   5          1      Escalate        Worsening" in out
