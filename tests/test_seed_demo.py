"""The demo seed script: scenario outcomes, idempotence, and isolation from non-demo data."""

import json
import re
from datetime import date, datetime
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


ROOT = Path(__file__).parent.parent
LIVE_ANSWERS = ["151 pounds, up one pound from yesterday.", "No new swelling.", "Comfortable when I sit still.",
                "It was 89.", "Yes, I took both this morning.", "About a 6.", "No falls, I feel safe at home.",
                "No, that's all."]
DOCTOR_QUESTION = "Did you feel lightheaded when you stood up today?"
SECOND_ANSWERS = ["No, not today.", "151 pounds.", "No new swelling.", "Comfortable when I sit still.", "93 now.",
                  "Yes.", "About a 6.", "No falls, I feel safe at home.", "No, that's all."]


def html(at, marker: str) -> str:
    return next(m.value for m in at.markdown if marker in m.value)


def roster(at) -> list[list[str]]:
    """Visible text of each roster row, top to bottom."""
    rows = [m.value for m in at.markdown if m.value.startswith('<div class="nh-roster-row">')]
    return [[t.strip() for t in re.split(r"<[^>]+>", row) if t.strip()] for row in rows]


def roster_cells(at, pid: str) -> list[str]:
    return next(r for r in roster(at) if r[1] == pid)


def kpis(at) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html(at, '<div class="nh-kpis">')).split())


def bullets(at) -> list[str]:
    return [m.value[2:] for m in at.markdown if m.value.startswith("- ")]


def button(at, label: str):
    return next(b for b in at.button if b.label == label)


def open_patient(clinician, pid: str) -> None:
    if any(b.label == "Back to roster" for b in clinician.button):
        button(clinician, "Back to roster").click().run()
    clinician.button(key=f"open_{pid}").click().run()
    assert not clinician.exception


def check_in(patient, answers: list[str]) -> str:
    if patient.selectbox:
        patient.selectbox[0].set_value("demo_live").run()
        patient.button(key="start").click().run()
    else:
        button(patient, "Start a new check-in").click().run()
    opening = patient.chat_message[0].markdown[0].value
    for answer in answers:
        patient.chat_input[0].set_value(answer).run()
        assert not patient.exception
    assert any("Check-in complete!" in s.value for s in patient.success)
    return opening


def chip(at, text: str) -> bool:
    return any(f'">{text}</span>' in m.value for m in at.markdown)


def test_demo_walkthrough_matches_the_screen(db, tmp_path, open_page):
    demo_md = (ROOT / "DEMO.md").read_text()
    for text in [*LIVE_ANSWERS, DOCTOR_QUESTION, *SECOND_ANSWERS]:
        assert f"`{text}`" in demo_md, f"DEMO.md no longer tells presenters to type {text!r}"
    seed_demo.seed(tmp_path)

    clinician = open_page("clinician")
    assert kpis(clinician) == "Patients 9 Check-ins complete 4 / 9 Need attention 2"
    assert roster_cells(clinician, "demo_live")[-2:] == ["Not started", "—"]

    patient = open_page("patient")
    assert any("<h1>Who is checking in today?</h1>" in m.value for m in patient.markdown)
    assert patient.selectbox[0].label == "Your name"
    patient.selectbox[0].set_value("demo_live").run()
    patient.button(key="start").click().run()
    opening = patient.chat_message[0].markdown[0].value
    assert opening.startswith("Hello Grace!") and "I'll ask you 8 questions" in opening
    assert patient.get("progress")[0].proto.text == "0 of 8 questions answered"
    assert any("call <b>911</b>" in m.value for m in patient.markdown)
    for answer in LIVE_ANSWERS:
        patient.chat_input[0].set_value(answer).run()
    assert any("Check-in complete!" in s.value for s in patient.success)

    # AppTest has no timers, so the Refresh button stands in for the roster's auto refresh
    clinician.button(key="refresh_roster").click().run()
    assert kpis(clinician) == "Patients 9 Check-ins complete 5 / 9 Need attention 3"
    assert [r[0] for r in roster(clinician)] == [
        "Grace Thompson", "Walter Briggs", "Samuel Park", "Dorothy Williams", "Frank Ellison",
        "Margaret Chen", "Robert Johnson", "Harold Okafor", "Rosa Delgado",
    ]
    assert roster_cells(clinician, "demo_live")[-2:] == ["Completed", "Escalate"]
    assert roster_cells(clinician, "demo_pneumonia")[-2:] == ["Completed", "Escalate"]
    assert roster_cells(clinician, "demo_twice")[-3:] == ["Completed", "2 check-ins today", "Schedule visit"]
    for pid in ("demo_diabetes", "demo_heartfailure"):
        assert roster_cells(clinician, pid)[-2:] == ["Completed", "Routine review"]
    for pid in ("demo_copd", "patient_001", "patient_002", "patient_003"):
        assert roster_cells(clinician, pid)[-2:] == ["Not started", "—"]

    open_patient(clinician, "demo_live")
    assert chip(clinician, "Escalate")
    latest = db.get_recent_checkins("demo_live", n=1)[0]
    assert db.get_summary("demo_live", latest.id).flagged_items == bullets(clinician)[:2] == [
        'Low oxygen saturation: 89% (below 90%) — patient said "It was 89."',
        "Worsening trend: Oxygen saturation moving outside the normal range: 96% → 96% → 89%; "
        "Recommended action rose to Escalate (previously at most Routine review)",
    ]
    assert any("| It was 89." in m.value or "It was 89. |" in m.value for m in clinician.markdown)

    open_patient(clinician, "demo_pneumonia")
    assert chip(clinician, "Worsening")
    assert any(m.value.startswith("**Trajectory over the last 5 check-ins**") for m in clinician.markdown)
    reasons = [
        "Oxygen saturation moving outside the normal range: 97% → 96% → 95% → 93% → 89%",
        "Temperature moving outside the normal range: 98.9 °F → 99.1 °F → 99.4 °F → 99.9 °F → 100.6 °F",
        "Breathing rate moving outside the normal range: 17/min → 18/min → 19/min → 21/min → 24/min",
        "Recommended action rose to Escalate (previously at most Routine review)",
        "Patient reports more symptoms getting worse than at the last check-in",
    ]
    assert bullets(clinician)[-len(reasons):] == reasons
    charts = [c.value for c in clinician.caption]
    assert [c.split(" (")[0] for c in charts if " (" in c] == ["Oxygen saturation", "Temperature", "Breathing rate"]
    assert len(clinician.get("vega_lite_chart")) == 3
    open_patient(clinician, "demo_diabetes")
    assert chip(clinician, "Improving")
    assert "Blood sugar returning toward normal: 310 mg/dL → 265 mg/dL → 220 mg/dL → 175 mg/dL → 142 mg/dL" in bullets(clinician)
    open_patient(clinician, "demo_heartfailure")
    assert chip(clinician, "Stable")

    open_patient(clinician, "demo_twice")
    assert clinician.caption[0].value.startswith("2 check-ins today. Showing the latest, from ")
    assert chip(clinician, "Schedule visit")
    flags = bullets(clinician)[:2]
    assert flags[0].startswith("High blood pressure: 172/104 mmHg")
    assert "I have a pounding headache and feel very dizzy" in flags[1]
    answers = [" ".join(t.value["Answer"]) for t in clinician.table]
    assert "172 over 104" in answers[0] and "132 over 84" in answers[1]

    open_patient(clinician, "demo_live")
    clinician.text_input[0].set_value("Dr. Rivera")
    clinician.text_area[0].set_value(DOCTOR_QUESTION)
    button(clinician, "Save questions").click().run()
    assert any(s.value.endswith("1 question(s) saved for Grace Thompson.") for s in clinician.success)

    button(patient, "Start a new check-in").click().run()
    opening = patient.chat_message[0].markdown[0].value
    assert "I'll ask you 9 questions" in opening and opening.endswith(DOCTOR_QUESTION)
    for answer in SECOND_ANSWERS:
        patient.chat_input[0].set_value(answer).run()
    assert any("Check-in complete!" in s.value for s in patient.success)

    button(clinician, "Back to roster").click().run()
    assert roster_cells(clinician, "demo_live")[-3:] == ["Completed", "2 check-ins today", "Schedule visit"]
    open_patient(clinician, "demo_live")
    assert clinician.caption[0].value.startswith("2 check-ins today. Showing the latest, from ")
    latest = db.get_recent_checkins("demo_live", n=1)[0]
    assert db.get_summary("demo_live", latest.id).flagged_items == [
        "Worsening trend: Oxygen saturation drifting the wrong way: 96% → 96% → 89% → 93%"
    ]
    today = date.today().isoformat()
    assert sum(m.value.startswith(f"**{today} at ") for m in clinician.markdown) == 2
    newest = clinician.table[0].value
    assert (newest["Question"].iloc[0], newest["Answer"].iloc[0]) == (DOCTOR_QUESTION, "No, not today.")
