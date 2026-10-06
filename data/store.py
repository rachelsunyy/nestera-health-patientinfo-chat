"""JSON-file persistence layer.

One directory per patient:  patient_data/<patient_id>/
  record.json          — PatientRecord (static)
  checkins/YYYY-MM-DD.json  — DailyCheckIn
  summaries/YYYY-MM-DD.json — ClinicalSummary
"""

from __future__ import annotations
import json
from pathlib import Path
from datetime import date

from config import DATA_DIR
from data.models import PatientRecord, DailyCheckIn, ClinicalSummary


def _patient_dir(patient_id: str) -> Path:
    p = DATA_DIR / patient_id
    (p / "checkins").mkdir(parents=True, exist_ok=True)
    (p / "summaries").mkdir(parents=True, exist_ok=True)
    return p


# ── Patient records ────────────────────────────────────────────────────────

def save_patient_record(record: PatientRecord) -> None:
    path = _patient_dir(record.patient_id) / "record.json"
    path.write_text(record.model_dump_json(indent=2))


def load_patient_record(patient_id: str) -> PatientRecord:
    path = _patient_dir(patient_id) / "record.json"
    if not path.exists():
        raise FileNotFoundError(f"No record found for patient '{patient_id}'")
    return PatientRecord.model_validate_json(path.read_text())


def list_patients() -> list[str]:
    return [p.name for p in DATA_DIR.iterdir() if p.is_dir()]


# ── Daily check-ins ────────────────────────────────────────────────────────

def save_checkin(checkin: DailyCheckIn) -> None:
    path = _patient_dir(checkin.patient_id) / "checkins" / f"{checkin.date}.json"
    path.write_text(checkin.model_dump_json(indent=2))


def load_checkin(patient_id: str, checkin_date: str | None = None) -> DailyCheckIn | None:
    d = checkin_date or date.today().isoformat()
    path = _patient_dir(patient_id) / "checkins" / f"{d}.json"
    if not path.exists():
        return None
    return DailyCheckIn.model_validate_json(path.read_text())


def load_recent_checkins(patient_id: str, n: int = 3) -> list[DailyCheckIn]:
    checkin_dir = _patient_dir(patient_id) / "checkins"
    files = sorted(checkin_dir.glob("*.json"), reverse=True)[:n]
    return [DailyCheckIn.model_validate_json(f.read_text()) for f in files]


# ── Clinical summaries ─────────────────────────────────────────────────────

def save_summary(summary: ClinicalSummary) -> None:
    path = _patient_dir(summary.patient_id) / "summaries" / f"{summary.date}.json"
    path.write_text(summary.model_dump_json(indent=2))


def load_summary(patient_id: str, summary_date: str | None = None) -> ClinicalSummary | None:
    d = summary_date or date.today().isoformat()
    path = _patient_dir(patient_id) / "summaries" / f"{d}.json"
    if not path.exists():
        return None
    return ClinicalSummary.model_validate_json(path.read_text())
