"""Several check-ins per day: storage keys, legacy date-keyed records, per-check-in summaries."""

import json
from datetime import date

import pytest

from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent
from data.models import CheckInResponse, DailyCheckIn
from database.patient_db import GCSPatientDatabase

SPO2 = "Did you measure your oxygen level (SpO2) today? If yes, what was the reading?"


class FakeBucket:
    """The slice of google.cloud.storage that GCSPatientDatabase uses, backed by a dict."""

    def __init__(self):
        self.blobs: dict[str, str] = {}

    def blob(self, name):
        bucket = self

        class Blob:
            def __init__(self):
                self.name = name

            def exists(self):
                return name in bucket.blobs

            def download_as_text(self):
                return bucket.blobs[name]

            def upload_from_string(self, text, content_type=None):
                bucket.blobs[name] = text

        return Blob()

    def list_blobs(self, _bucket, prefix):
        return [self.blob(n) for n in self.blobs if n.startswith(prefix)]


@pytest.fixture(params=["mock", "gcs"])
def backend(request, db, tmp_path):
    """(database, write_raw) where write_raw(path, dict) stores a file exactly as an older version left it."""
    if request.param == "mock":
        return db, lambda path, data: (tmp_path / path).write_text(json.dumps(data))
    fake = FakeBucket()
    gcs = GCSPatientDatabase.__new__(GCSPatientDatabase)
    gcs._client, gcs._bucket = fake, fake
    gcs.save_patient(db.get_patient("patient_001"))
    return gcs, lambda path, data: fake.blobs.__setitem__(f"patients/{path}", json.dumps(data))


def checkin(timestamp, spo2="97"):
    return DailyCheckIn(patient_id="patient_001", date=timestamp[:10], timestamp=timestamp,
                        responses=[CheckInResponse(question=SPO2, answer=spo2)])


def test_two_same_day_checkins_both_persist(backend):
    database, _ = backend
    morning, evening = checkin("2026-10-30T09:05:00.000001", "97"), checkin("2026-10-30T18:40:12.5", "93")
    database.save_checkin(morning)
    database.save_checkin(evening)
    database.save_checkin(checkin("2026-10-29T12:00:00"))

    assert [c.responses[0].answer for c in database.get_checkins_for_date("patient_001", "2026-10-30")] == ["97", "93"]
    assert [c.timestamp for c in database.get_recent_checkins("patient_001", n=3)] == [
        "2026-10-30T18:40:12.5", "2026-10-30T09:05:00.000001", "2026-10-29T12:00:00"]
    assert database.get_checkin("patient_001", morning.id).responses[0].answer == "97"


def test_legacy_date_keyed_checkin_and_summary_still_load_and_sort_first(backend):
    database, write_raw = backend
    write_raw("patient_001/checkins/2026-10-30.json", {
        "patient_id": "patient_001", "date": "2026-10-30", "timestamp": "2026-10-30T20:00:00",
        "responses": [{"question": SPO2, "answer": "96"}], "free_text_concerns": ""})
    write_raw("patient_001/summaries/2026-10-30.json", {
        "patient_id": "patient_001", "date": "2026-10-30", "generated_at": "2026-10-30T20:01:00",
        "summary_markdown": "old note", "recommended_action": "Routine review"})
    later = checkin("2026-10-30T21:15:00")
    database.save_checkin(later)

    legacy, new = database.get_checkins_for_date("patient_001", "2026-10-30")
    assert legacy.id == "2026-10-30" and legacy.responses[0].answer == "96"
    assert new.id == later.id
    assert [c.id for c in database.get_recent_checkins("patient_001")] == [later.id, "2026-10-30"]
    assert database.get_checkin("patient_001", "2026-10-30").responses[0].answer == "96"
    assert database.get_summary("patient_001", "2026-10-30").summary_markdown == "old note"


def test_summaries_are_kept_per_checkin(backend):
    database, _ = backend
    first, second = checkin("2026-10-30T09:00:00", "97"), checkin("2026-10-30T17:00:00", "88")
    database.save_checkin(first)
    database.save_checkin(second)
    agent = SummaryAgent("patient_001", database)
    agent.generate(first.id)
    agent.generate(second.id)

    assert database.get_summary("patient_001", first.id).recommended_action == "Routine review"
    assert database.get_summary("patient_001", second.id).recommended_action == "Escalate"


def test_second_checkin_today_does_not_replace_the_first(db):
    for answer in ("Doing fine", "I fell this morning"):
        agent = PatientAgent("patient_002", db)
        agent.start_session()
        done = False
        while not done:
            _, done = agent.respond(answer)

    first, second = db.get_checkins_for_date("patient_002", date.today().isoformat())
    assert first.responses[0].answer == "Doing fine" and second.responses[0].answer == "I fell this morning"
    summary = SummaryAgent("patient_002", db).generate()
    assert summary.checkin_id == second.id and summary.recommended_action == "Schedule visit"
    assert db.get_summary("patient_002", first.id) is None
