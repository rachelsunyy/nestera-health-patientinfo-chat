"""Database abstraction for the Hospital-At-Home agent.

PatientDatabase defines the interface every backend must satisfy.
MockPatientDatabase  — local JSON files (development/testing)
GCSPatientDatabase   — Google Cloud Storage JSON files (production)

To switch backends, change one line in app.py:
    db = MockPatientDatabase()
    db = GCSPatientDatabase("your-bucket-name")
"""

from __future__ import annotations
import json
from abc import ABC, abstractmethod
from pathlib import Path

from data.models import (
    PATIENT_ID, PatientRecord, DoctorQuestions, DailyCheckIn, ClinicalSummary, validate_patient_id
)
from config import DATA_DIR


def _load_checkin(key: str, data: dict) -> DailyCheckIn:
    """Parse a stored check-in; records saved before ids existed take their id from the file name."""
    return DailyCheckIn.model_validate({"id": key, **data})


# ── Abstract interface ─────────────────────────────────────────────────────

class PatientDatabase(ABC):

    @abstractmethod
    def get_patient(self, patient_id: str) -> PatientRecord:
        """Load a patient's full medical record."""

    @abstractmethod
    def save_patient(self, record: PatientRecord) -> None:
        """Create or update a patient record."""

    @abstractmethod
    def list_patient_ids(self) -> list[str]:
        """Return all registered patient IDs."""

    @abstractmethod
    def get_doctor_questions(self, patient_id: str, for_date: str) -> list[str]:
        """Return questions the doctor added for this patient for today."""

    @abstractmethod
    def save_doctor_questions(self, dq: DoctorQuestions) -> None:
        """Save or replace doctor questions for a patient/date."""

    @abstractmethod
    def save_checkin(self, checkin: DailyCheckIn) -> None:
        """Persist a completed check-in under its id."""

    @abstractmethod
    def get_checkin(self, patient_id: str, checkin_id: str) -> DailyCheckIn | None:
        """Load a specific check-in by id, or None if it doesn't exist."""

    @abstractmethod
    def get_checkins_for_date(self, patient_id: str, for_date: str) -> list[DailyCheckIn]:
        """Return every check-in on a date, oldest first."""

    @abstractmethod
    def get_recent_checkins(self, patient_id: str, n: int = 3) -> list[DailyCheckIn]:
        """Return the n most recent check-ins, newest first."""

    @abstractmethod
    def save_summary(self, summary: ClinicalSummary) -> None:
        """Persist a clinical summary."""

    @abstractmethod
    def get_summary(self, patient_id: str, checkin_id: str) -> ClinicalSummary | None:
        """Load the summary of a check-in, or None."""


# ── Mock (local JSON) implementation ──────────────────────────────────────

class MockPatientDatabase(PatientDatabase):
    """JSON-file backed database for local development and testing.

    Directory structure under DATA_DIR:
      <patient_id>/
        record.json
        doctor_questions/YYYY-MM-DD.json
        checkins/<checkin id>.json     e.g. 2026-11-01T17-30-05.123456.json
        summaries/<checkin id>.json
    Records written before multiple daily check-ins are named YYYY-MM-DD.json.
    """

    def _patient_dir(self, patient_id: str) -> Path:
        p = DATA_DIR / validate_patient_id(patient_id)
        for sub in ("doctor_questions", "checkins", "summaries"):
            (p / sub).mkdir(parents=True, exist_ok=True)
        return p

    # Patient records
    def get_patient(self, patient_id: str) -> PatientRecord:
        path = self._patient_dir(patient_id) / "record.json"
        if not path.exists():
            raise FileNotFoundError(f"No patient record found for ID '{patient_id}'")
        return PatientRecord.model_validate_json(path.read_text())

    def save_patient(self, record: PatientRecord) -> None:
        path = self._patient_dir(record.patient_id) / "record.json"
        path.write_text(record.model_dump_json(indent=2))

    def list_patient_ids(self) -> list[str]:
        return [p.name for p in DATA_DIR.iterdir() if p.is_dir() and PATIENT_ID.fullmatch(p.name)]

    # Doctor questions
    def get_doctor_questions(self, patient_id: str, for_date: str) -> list[str]:
        path = self._patient_dir(patient_id) / "doctor_questions" / f"{for_date}.json"
        if not path.exists():
            return []
        dq = DoctorQuestions.model_validate_json(path.read_text())
        return dq.questions

    def save_doctor_questions(self, dq: DoctorQuestions) -> None:
        path = self._patient_dir(dq.patient_id) / "doctor_questions" / f"{dq.date}.json"
        path.write_text(dq.model_dump_json(indent=2))

    # Check-ins
    def save_checkin(self, checkin: DailyCheckIn) -> None:
        path = self._patient_dir(checkin.patient_id) / "checkins" / f"{checkin.id}.json"
        path.write_text(checkin.model_dump_json(indent=2))

    def get_checkin(self, patient_id: str, checkin_id: str) -> DailyCheckIn | None:
        path = self._patient_dir(patient_id) / "checkins" / f"{checkin_id}.json"
        return self._read_checkin(path) if path.exists() else None

    def get_checkins_for_date(self, patient_id: str, for_date: str) -> list[DailyCheckIn]:
        files = sorted((self._patient_dir(patient_id) / "checkins").glob(f"{for_date}*.json"))
        return [self._read_checkin(f) for f in files]

    def get_recent_checkins(self, patient_id: str, n: int = 3) -> list[DailyCheckIn]:
        d = self._patient_dir(patient_id) / "checkins"
        files = sorted(d.glob("*.json"), reverse=True)[:n]
        return [self._read_checkin(f) for f in files]

    @staticmethod
    def _read_checkin(path: Path) -> DailyCheckIn:
        return _load_checkin(path.stem, json.loads(path.read_text()))

    # Summaries
    def save_summary(self, summary: ClinicalSummary) -> None:
        path = self._patient_dir(summary.patient_id) / "summaries" / f"{summary.checkin_id}.json"
        path.write_text(summary.model_dump_json(indent=2))

    def get_summary(self, patient_id: str, checkin_id: str) -> ClinicalSummary | None:
        path = self._patient_dir(patient_id) / "summaries" / f"{checkin_id}.json"
        if not path.exists():
            return None
        return ClinicalSummary.model_validate_json(path.read_text())


# ── Google Cloud Storage implementation ────────────────────────────────────

class GCSPatientDatabase(PatientDatabase):
    """Cloud Storage backend — stores JSON blobs in a GCS bucket.

    Same file layout as MockPatientDatabase but in GCS:
      gs://<bucket>/patients/<patient_id>/record.json
      gs://<bucket>/patients/<patient_id>/doctor_questions/YYYY-MM-DD.json
      gs://<bucket>/patients/<patient_id>/checkins/<checkin id>.json
      gs://<bucket>/patients/<patient_id>/summaries/<checkin id>.json

    Install:  pip install google-cloud-storage
    Auth:     Application Default Credentials (automatic on Cloud Run)
    """

    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    @staticmethod
    def _key(patient_id: str, name: str) -> str:
        return f"patients/{validate_patient_id(patient_id)}/{name}"

    def _read(self, patient_id: str, name: str) -> dict | None:
        blob = self._bucket.blob(self._key(patient_id, name))
        if not blob.exists():
            return None
        return json.loads(blob.download_as_text())

    def _write(self, patient_id: str, name: str, data: dict) -> None:
        self._bucket.blob(self._key(patient_id, name)).upload_from_string(
            json.dumps(data, indent=2), content_type="application/json"
        )

    def _list_blobs(self, patient_id: str, prefix: str) -> list[str]:
        return [b.name for b in self._client.list_blobs(self._bucket, prefix=self._key(patient_id, prefix))]

    # Patient records
    def get_patient(self, patient_id: str) -> PatientRecord:
        data = self._read(patient_id, "record.json")
        if data is None:
            raise FileNotFoundError(f"No patient record found for ID '{patient_id}'")
        return PatientRecord.model_validate(data)

    def save_patient(self, record: PatientRecord) -> None:
        self._write(record.patient_id, "record.json", record.model_dump())

    def delete_patient(self, patient_id: str) -> None:
        """Remove every object stored under one patient: record, questions, check-ins, summaries."""
        for blob in self._client.list_blobs(self._bucket, prefix=self._key(patient_id, "")):
            blob.delete()

    def list_patient_ids(self) -> list[str]:
        seen, ids = set(), []
        for blob in self._client.list_blobs(self._bucket, prefix="patients/"):
            parts = blob.name.split("/")
            if len(parts) >= 3:
                pid = parts[1]
                if pid not in seen and PATIENT_ID.fullmatch(pid):
                    seen.add(pid); ids.append(pid)
        return ids

    # Doctor questions
    def get_doctor_questions(self, patient_id: str, for_date: str) -> list[str]:
        data = self._read(patient_id, f"doctor_questions/{for_date}.json")
        if data is None:
            return []
        return DoctorQuestions.model_validate(data).questions

    def save_doctor_questions(self, dq: DoctorQuestions) -> None:
        self._write(dq.patient_id, f"doctor_questions/{dq.date}.json", dq.model_dump())

    # Check-ins
    def save_checkin(self, checkin: DailyCheckIn) -> None:
        self._write(checkin.patient_id, f"checkins/{checkin.id}.json", checkin.model_dump())

    def get_checkin(self, patient_id: str, checkin_id: str) -> DailyCheckIn | None:
        data = self._read(patient_id, f"checkins/{checkin_id}.json")
        return _load_checkin(checkin_id, data) if data else None

    def _load_checkin_blobs(self, names: list[str]) -> list[DailyCheckIn]:
        return [
            _load_checkin(Path(name).stem, json.loads(self._bucket.blob(name).download_as_text()))
            for name in names
        ]

    def get_checkins_for_date(self, patient_id: str, for_date: str) -> list[DailyCheckIn]:
        return self._load_checkin_blobs(sorted(self._list_blobs(patient_id, f"checkins/{for_date}")))

    def get_recent_checkins(self, patient_id: str, n: int = 3) -> list[DailyCheckIn]:
        return self._load_checkin_blobs(sorted(self._list_blobs(patient_id, "checkins/"), reverse=True)[:n])

    # Summaries
    def save_summary(self, summary: ClinicalSummary) -> None:
        self._write(summary.patient_id, f"summaries/{summary.checkin_id}.json", summary.model_dump())

    def get_summary(self, patient_id: str, checkin_id: str) -> ClinicalSummary | None:
        data = self._read(patient_id, f"summaries/{checkin_id}.json")
        return ClinicalSummary.model_validate(data) if data else None
