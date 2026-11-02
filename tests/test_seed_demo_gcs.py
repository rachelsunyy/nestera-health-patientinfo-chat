"""Seeding a Cloud Storage bucket: same scenarios as local, idempotent, and never touching non-demo patients."""

import json
from datetime import datetime

import pytest

import database.patient_db as patient_db
from agents.patient_agent import PatientAgent
from data.models import CheckInResponse, DailyCheckIn
from scripts import seed_demo

NOW = datetime.now().replace(hour=15, minute=0)


def snapshot(bucket) -> dict[str, object]:
    """Every object in the bucket; summaries without their generation time, which is always 'now'."""
    files = {}
    for name, text in sorted(bucket.blobs.items()):
        data = json.loads(text)
        if "/summaries/" in name:
            data.pop("generated_at")
        files[name] = data
    return files


def complete_checkin(db, pid: str) -> None:
    agent = PatientAgent(pid, db)
    agent.start_session()
    done = False
    while not done:
        _, done = agent.respond("Fine")


def test_bucket_gets_the_same_scenarios_as_a_local_folder(db, tmp_path, gcs_db):
    assert seed_demo.seed_bucket(gcs_db, now=NOW) == seed_demo.seed(tmp_path / "local", now=NOW)


def test_bucket_gets_the_sample_patients_without_overwriting_existing_ones(db, gcs_db):
    edited = db.get_patient("patient_001").model_copy(update={"name": "Edited By Clinician"})
    gcs_db.save_patient(edited)

    seed_demo.seed_bucket(gcs_db, now=NOW)

    assert {"patient_001", "patient_002", "patient_003"} <= set(gcs_db.list_patient_ids())
    assert gcs_db.get_patient("patient_001").name == "Edited By Clinician"


def test_rerun_converges_and_reset_removes_stray_demo_patients(gcs_db, fake_bucket):
    seed_demo.seed_bucket(gcs_db, now=NOW)
    first = snapshot(fake_bucket)

    complete_checkin(gcs_db, "demo_live")
    fake_bucket.blobs["patients/demo_retired/record.json"] = "{}"

    seed_demo.seed_bucket(gcs_db, now=NOW)
    stray = snapshot(fake_bucket)
    assert stray.pop("patients/demo_retired/record.json") == {}
    assert stray == first

    seed_demo.seed_bucket(gcs_db, reset=True, now=NOW)
    assert snapshot(fake_bucket) == first


def test_reset_leaves_every_non_demo_object_untouched(db, gcs_db, fake_bucket):
    gcs_db.save_patient(db.get_patient("patient_001"))
    gcs_db.save_checkin(DailyCheckIn(patient_id="patient_001", date="2026-10-30", timestamp="2026-10-30T09:00:00",
                                     responses=[CheckInResponse(question="How are you?", answer="Fine")]))
    fake_bucket.blobs["patients/demonstration/record.json"] = '{"keep": true}'
    fake_bucket.blobs["patients/demo_x.json"] = '{"keep": true}'
    fake_bucket.blobs["exports/demo_live/record.json"] = '{"keep": true}'
    before = dict(fake_bucket.blobs)

    seed_demo.seed_bucket(gcs_db, reset=True, now=NOW)

    assert {k: fake_bucket.blobs.get(k) for k in before} == before


def test_cli_seeds_the_named_bucket(gcs_db, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(patient_db, "GCSPatientDatabase", lambda name: opened.append(name) or gcs_db)

    seed_demo.main(["--gcs-bucket", "demo-bucket", "--reset"])

    assert opened == ["demo-bucket"]
    out = capsys.readouterr().out
    assert "Seeded 6 demo patients in gs://demo-bucket" in out
    assert "demo_pneumonia     Walter Briggs   5          1      Escalate        Worsening" in out


def test_cli_refuses_a_folder_and_a_bucket_together(tmp_path, capsys):
    with pytest.raises(SystemExit):
        seed_demo.main(["--data-dir", str(tmp_path), "--gcs-bucket", "demo-bucket"])
    assert "not allowed with argument" in capsys.readouterr().err
