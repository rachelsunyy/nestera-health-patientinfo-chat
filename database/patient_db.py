"""Database abstraction for the Hospital-At-Home agent.

PatientDatabase defines the interface every backend must satisfy.
MockPatientDatabase  — local JSON files (development/testing)
GCSPatientDatabase   — Google Cloud Storage JSON files (production, no Firestore needed)
FirestorePatientDatabase — Firestore (if available)

To switch backends, change one line in app.py:
    db = MockPatientDatabase()
    db = GCSPatientDatabase("your-bucket-name")
    db = FirestorePatientDatabase("your-project-id")
"""

from __future__ import annotations
import json
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from data.models import (
    PatientRecord, DoctorQuestions, DailyCheckIn, ClinicalSummary
)
from config import DATA_DIR


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
        """Persist a completed daily check-in."""

    @abstractmethod
    def get_checkin(self, patient_id: str, checkin_date: str) -> DailyCheckIn | None:
        """Load a specific check-in, or None if it doesn't exist."""

    @abstractmethod
    def get_recent_checkins(self, patient_id: str, n: int = 3) -> list[DailyCheckIn]:
        """Return the n most recent check-ins, newest first."""

    @abstractmethod
    def save_summary(self, summary: ClinicalSummary) -> None:
        """Persist a clinical summary."""

    @abstractmethod
    def get_summary(self, patient_id: str, summary_date: str) -> ClinicalSummary | None:
        """Load a specific summary, or None."""


# ── Mock (local JSON) implementation ──────────────────────────────────────

class MockPatientDatabase(PatientDatabase):
    """JSON-file backed database for local development and testing.

    Directory structure under DATA_DIR:
      <patient_id>/
        record.json
        doctor_questions/YYYY-MM-DD.json
        checkins/YYYY-MM-DD.json
        summaries/YYYY-MM-DD.json
    """

    def _patient_dir(self, patient_id: str) -> Path:
        p = DATA_DIR / patient_id
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
        return [p.name for p in DATA_DIR.iterdir() if p.is_dir()]

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
        path = self._patient_dir(checkin.patient_id) / "checkins" / f"{checkin.date}.json"
        path.write_text(checkin.model_dump_json(indent=2))

    def get_checkin(self, patient_id: str, checkin_date: str) -> DailyCheckIn | None:
        path = self._patient_dir(patient_id) / "checkins" / f"{checkin_date}.json"
        if not path.exists():
            return None
        return DailyCheckIn.model_validate_json(path.read_text())

    def get_recent_checkins(self, patient_id: str, n: int = 3) -> list[DailyCheckIn]:
        d = self._patient_dir(patient_id) / "checkins"
        files = sorted(d.glob("*.json"), reverse=True)[:n]
        return [DailyCheckIn.model_validate_json(f.read_text()) for f in files]

    # Summaries
    def save_summary(self, summary: ClinicalSummary) -> None:
        path = self._patient_dir(summary.patient_id) / "summaries" / f"{summary.date}.json"
        path.write_text(summary.model_dump_json(indent=2))

    def get_summary(self, patient_id: str, summary_date: str) -> ClinicalSummary | None:
        path = self._patient_dir(patient_id) / "summaries" / f"{summary_date}.json"
        if not path.exists():
            return None
        return ClinicalSummary.model_validate_json(path.read_text())


# ── Firestore implementation (Google Cloud) ────────────────────────────────

class FirestorePatientDatabase(PatientDatabase):
    """Cloud Firestore backend for production on Google Cloud.

    Collections:
      patients/{patient_id}                         → PatientRecord
      patients/{patient_id}/doctor_questions/{date} → DoctorQuestions
      patients/{patient_id}/checkins/{date}         → DailyCheckIn
      patients/{patient_id}/summaries/{date}        → ClinicalSummary

    Install:  pip install google-cloud-firestore
    Auth:     Application Default Credentials (automatic on Cloud Run)
              or set GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json locally
    """

    def __init__(self, project_id: str) -> None:
        from google.cloud import firestore
        self._db = firestore.Client(project=project_id)

    def _patients(self):
        return self._db.collection("patients")

    def get_patient(self, patient_id: str) -> PatientRecord:
        doc = self._patients().document(patient_id).get()
        if not doc.exists:
            raise FileNotFoundError(f"No patient record found for ID '{patient_id}'")
        return PatientRecord.model_validate(doc.to_dict())

    def save_patient(self, record: PatientRecord) -> None:
        self._patients().document(record.patient_id).set(record.model_dump())

    def list_patient_ids(self) -> list[str]:
        return [d.id for d in self._patients().stream()]

    def get_doctor_questions(self, patient_id: str, for_date: str) -> list[str]:
        doc = self._patients().document(patient_id)\
                  .collection("doctor_questions").document(for_date).get()
        if not doc.exists:
            return []
        return DoctorQuestions.model_validate(doc.to_dict()).questions

    def save_doctor_questions(self, dq: DoctorQuestions) -> None:
        self._patients().document(dq.patient_id)\
            .collection("doctor_questions").document(dq.date).set(dq.model_dump())

    def save_checkin(self, checkin: DailyCheckIn) -> None:
        self._patients().document(checkin.patient_id)\
            .collection("checkins").document(checkin.date).set(checkin.model_dump())

    def get_checkin(self, patient_id: str, checkin_date: str) -> DailyCheckIn | None:
        doc = self._patients().document(patient_id)\
                  .collection("checkins").document(checkin_date).get()
        return DailyCheckIn.model_validate(doc.to_dict()) if doc.exists else None

    def get_recent_checkins(self, patient_id: str, n: int = 3) -> list[DailyCheckIn]:
        docs = self._patients().document(patient_id)\
                   .collection("checkins")\
                   .order_by("date", direction="DESCENDING").limit(n).stream()
        return [DailyCheckIn.model_validate(d.to_dict()) for d in docs]

    def save_summary(self, summary: ClinicalSummary) -> None:
        self._patients().document(summary.patient_id)\
            .collection("summaries").document(summary.date).set(summary.model_dump())

    def get_summary(self, patient_id: str, summary_date: str) -> ClinicalSummary | None:
        doc = self._patients().document(patient_id)\
                  .collection("summaries").document(summary_date).get()
        return ClinicalSummary.model_validate(doc.to_dict()) if doc.exists else None


# ── Google Cloud Storage implementation ────────────────────────────────────

class GCSPatientDatabase(PatientDatabase):
    """Cloud Storage backend — stores JSON blobs in a GCS bucket.

    No Firestore needed. Same file layout as MockPatientDatabase but in GCS:
      gs://<bucket>/patients/<patient_id>/record.json
      gs://<bucket>/patients/<patient_id>/doctor_questions/YYYY-MM-DD.json
      gs://<bucket>/patients/<patient_id>/checkins/YYYY-MM-DD.json
      gs://<bucket>/patients/<patient_id>/summaries/YYYY-MM-DD.json

    Install:  pip install google-cloud-storage
    Auth:     Application Default Credentials (automatic on Cloud Run)
    """

    def __init__(self, bucket_name: str) -> None:
        from google.cloud import storage
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)

    def _blob(self, path: str):
        return self._bucket.blob(f"patients/{path}")

    def _read(self, path: str) -> dict | None:
        blob = self._blob(path)
        if not blob.exists():
            return None
        return json.loads(blob.download_as_text())

    def _write(self, path: str, data: dict) -> None:
        self._blob(path).upload_from_string(
            json.dumps(data, indent=2), content_type="application/json"
        )

    def _list_blobs(self, prefix: str) -> list[str]:
        return [
            b.name for b in self._client.list_blobs(
                self._bucket, prefix=f"patients/{prefix}"
            )
        ]

    # Patient records
    def get_patient(self, patient_id: str) -> PatientRecord:
        data = self._read(f"{patient_id}/record.json")
        if data is None:
            raise FileNotFoundError(f"No patient record found for ID '{patient_id}'")
        return PatientRecord.model_validate(data)

    def save_patient(self, record: PatientRecord) -> None:
        self._write(f"{record.patient_id}/record.json", record.model_dump())

    def list_patient_ids(self) -> list[str]:
        seen, ids = set(), []
        for name in self._list_blobs(""):
            parts = name.split("/")
            if len(parts) >= 3:
                pid = parts[1]
                if pid not in seen:
                    seen.add(pid); ids.append(pid)
        return ids

    # Doctor questions
    def get_doctor_questions(self, patient_id: str, for_date: str) -> list[str]:
        data = self._read(f"{patient_id}/doctor_questions/{for_date}.json")
        if data is None:
            return []
        return DoctorQuestions.model_validate(data).questions

    def save_doctor_questions(self, dq: DoctorQuestions) -> None:
        self._write(f"{dq.patient_id}/doctor_questions/{dq.date}.json", dq.model_dump())

    # Check-ins
    def save_checkin(self, checkin: DailyCheckIn) -> None:
        self._write(f"{checkin.patient_id}/checkins/{checkin.date}.json", checkin.model_dump())

    def get_checkin(self, patient_id: str, checkin_date: str) -> DailyCheckIn | None:
        data = self._read(f"{patient_id}/checkins/{checkin_date}.json")
        return DailyCheckIn.model_validate(data) if data else None

    def get_recent_checkins(self, patient_id: str, n: int = 3) -> list[DailyCheckIn]:
        blobs = sorted(
            self._list_blobs(f"{patient_id}/checkins/"), reverse=True
        )[:n]
        result = []
        for name in blobs:
            blob = self._bucket.blob(name)
            result.append(DailyCheckIn.model_validate(json.loads(blob.download_as_text())))
        return result

    # Summaries
    def save_summary(self, summary: ClinicalSummary) -> None:
        self._write(f"{summary.patient_id}/summaries/{summary.date}.json", summary.model_dump())

    def get_summary(self, patient_id: str, summary_date: str) -> ClinicalSummary | None:
        data = self._read(f"{patient_id}/summaries/{summary_date}.json")
        return ClinicalSummary.model_validate(data) if data else None
