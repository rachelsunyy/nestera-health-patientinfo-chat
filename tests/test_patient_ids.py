"""Patient and check-in ids become folder and object names, so crafted ids are refused before any path is built."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import cli
from data.models import ClinicalSummary, DailyCheckIn, DoctorQuestions, PatientRecord
from database.patient_db import GCSPatientDatabase
from tests.conftest import FakeBucket
from views.registration import InvalidUpload, NewPatient, read_upload

SAMPLE = json.loads((Path(__file__).parent.parent / "sample_data" / "patient_001.json").read_text())

CRAFTED = ["../x", "..", ".", "a/b", "a\\b", "", "x" * 200, "/etc/passwd", "a\x00b", "a\nb", "patient_001\n", "p 1"]


class RecordingBucket(FakeBucket):
    def __init__(self):
        super().__init__()
        self.touched: list[str] = []

    def blob(self, name):
        self.touched.append(name)
        return super().blob(name)

    def list_blobs(self, bucket, prefix):
        self.touched.append(prefix)
        return super().list_blobs(bucket, prefix)


def tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


@pytest.fixture(params=["mock", "gcs"])
def store(request, db, tmp_path):
    """(database, snapshot) where snapshot() lists everything on disk around the data dir, or in the bucket."""
    if request.param == "mock":
        return db, lambda: tree(tmp_path.parent)
    bucket = RecordingBucket()
    gcs = GCSPatientDatabase.__new__(GCSPatientDatabase)
    gcs._client, gcs._bucket = bucket, bucket
    gcs.save_patient(db.get_patient("patient_001"))
    return gcs, lambda: (sorted(bucket.blobs), list(bucket.touched))


def storage_calls(database, pid):
    record = PatientRecord.model_validate(SAMPLE).model_copy(update={"patient_id": pid})
    return {
        "get_patient": lambda: database.get_patient(pid),
        "save_patient": lambda: database.save_patient(record),
        "get_doctor_questions": lambda: database.get_doctor_questions(pid, "2026-11-01"),
        "save_doctor_questions": lambda: database.save_doctor_questions(
            DoctorQuestions.model_construct(patient_id=pid, date="2026-11-01", questions=["q"], added_by="")),
        "save_checkin": lambda: database.save_checkin(
            DailyCheckIn.model_construct(patient_id=pid, id="2026-11-01", date="2026-11-01", timestamp="", responses=[],
                                         free_text_concerns="")),
        "get_checkin": lambda: database.get_checkin(pid, "2026-11-01"),
        "get_checkins_for_date": lambda: database.get_checkins_for_date(pid, "2026-11-01"),
        "get_recent_checkins": lambda: database.get_recent_checkins(pid),
        "save_summary": lambda: database.save_summary(
            ClinicalSummary.model_construct(patient_id=pid, date="2026-11-01", checkin_id="2026-11-01",
                                            summary_markdown="")),
        "get_summary": lambda: database.get_summary(pid, "2026-11-01"),
    }


@pytest.mark.parametrize("pid", CRAFTED + ["ABSOLUTE"])
def test_storage_refuses_crafted_patient_ids_without_touching_disk_or_bucket(store, pid, tmp_path):
    database, snapshot = store
    pid = str(tmp_path.parent / "escaped") if pid == "ABSOLUTE" else pid
    before = snapshot()
    for name, call in storage_calls(database, pid).items():
        with pytest.raises(ValueError, match="patient id must be"):
            call()
    assert snapshot() == before


def test_a_valid_id_still_round_trips_on_both_backends(store):
    database, _ = store
    for pid in ["a-B_9", "x" * 64]:
        database.save_patient(PatientRecord.model_validate({**SAMPLE, "patient_id": pid}))
        assert database.get_patient(pid).patient_id == pid
        assert pid in database.list_patient_ids()


def test_the_roster_ignores_stray_folders_and_objects_that_are_not_patient_ids(db, tmp_path):
    (tmp_path / ".cache").mkdir()
    assert ".cache" not in db.list_patient_ids()
    bucket = FakeBucket()
    bucket.blobs = {"patients/patient_001/record.json": "{}", "patients/bad.id/record.json": "{}"}
    gcs = GCSPatientDatabase.__new__(GCSPatientDatabase)
    gcs._client, gcs._bucket = bucket, bucket
    assert gcs.list_patient_ids() == ["patient_001"]


@pytest.mark.parametrize("model", [PatientRecord, DailyCheckIn, DoctorQuestions, ClinicalSummary])
def test_every_model_keyed_by_patient_rejects_a_crafted_id(model):
    fields = {**SAMPLE, "date": "2026-11-01", "summary_markdown": ""}
    with pytest.raises(ValidationError):
        model.model_validate({**fields, "patient_id": "../x"})


def test_an_upload_with_a_traversal_id_is_refused_with_a_readable_line():
    result = read_upload(json.dumps({**SAMPLE, "patient_id": "../../etc/x"}).encode(), [])
    assert result == InvalidUpload(["patient_id: A patient id must be 1 to 64 letters, digits, underscores or hyphens."])
    assert isinstance(read_upload(json.dumps({**SAMPLE, "patient_id": "new-patient_7"}).encode(), []), NewPatient)


@pytest.mark.parametrize("pid", ["../x", "..", "a\\b", "x" * 200])
def test_patient_deep_link_with_a_crafted_id_shows_the_picker_and_creates_nothing(db, open_page, tmp_path, pid):
    before = tree(tmp_path.parent)
    at = open_page("patient", patient=pid)
    assert "couldn't find that check-in link" in at.info[0].value
    assert at.selectbox[0].label == "Your name"
    assert tree(tmp_path.parent) == before


@pytest.mark.parametrize("pid", ["../x", "[click](https://example.com)", "nobody"])
def test_clinician_deep_link_with_a_bad_id_shows_the_roster_without_echoing_it(db, open_page, tmp_path, pid):
    before = tree(tmp_path.parent)
    at = open_page("clinician", patient=pid)
    assert at.info[0].value == "We couldn't find that patient link. Showing today's roster."
    assert [b for b in at.button if b.label == "Open"]
    assert tree(tmp_path.parent) == before


def asgi_get(path: str, query: str = "") -> int:
    import app
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": query.encode(), "headers": [],
             "server": ("test", 80), "client": ("test", 1), "root_path": ""}
    asyncio.run(app.app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_api_rejects_crafted_patient_and_checkin_ids(db, tmp_path):
    before = tree(tmp_path.parent)
    assert asgi_get("/patients/patient_001") == 200
    for path in ["/patients/..", "/patients/a\\b", "/patients/" + "x" * 200, "/trend/..", "/doctor/questions/.."]:
        assert asgi_get(path) == 422, path
    assert asgi_get("/summary/patient_001", "checkin_id=..%2F..%2Fx") == 422
    assert asgi_get("/summary/patient_001", "checkin_id=2026-10-29") == 404
    assert asgi_get("/summary/patient_001", "checkin_id=2026-11-01T17-30-05.123456") == 404
    assert tree(tmp_path.parent) == before


@pytest.mark.parametrize("argv", [
    ["summary", "--patient", "../x"],
    ["checkin", "--patient", "a/b"],
    ["add-questions", "--patient", "..", "--questions", "q"],
    ["summary", "--patient", "patient_001", "--checkin", "../x"],
])
def test_cli_rejects_crafted_ids_before_touching_storage(db, tmp_path, monkeypatch, capsys, argv):
    before = tree(tmp_path.parent)
    monkeypatch.setattr("sys.argv", ["cli.py", *argv])
    with pytest.raises(SystemExit) as exit_:
        cli.main()
    assert exit_.value.code == 2
    assert "id must be" in capsys.readouterr().err
    assert tree(tmp_path.parent) == before
