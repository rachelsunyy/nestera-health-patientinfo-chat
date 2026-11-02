"""State shared by every page: the patient database and how patients are named on screen."""

import os
from pathlib import Path

import streamlit as st

from data.models import PatientRecord
from database.patient_db import GCSPatientDatabase, MockPatientDatabase, PatientDatabase

SAMPLE_DIR = Path(__file__).parent.parent / "sample_data"


@st.cache_resource
def get_db() -> PatientDatabase:
    bucket = os.getenv("GCS_BUCKET")
    if bucket:
        return GCSPatientDatabase(bucket)
    db = MockPatientDatabase()
    for sample_file in sorted(SAMPLE_DIR.glob("patient_*.json")):
        try:
            record = PatientRecord.model_validate_json(sample_file.read_text())
            if record.patient_id not in db.list_patient_ids():
                db.save_patient(record)
        except Exception:
            pass
    return db


def patient_names(db: PatientDatabase) -> dict[str, str]:
    """Patient id to display name, sorted by name."""
    names = {}
    for pid in db.list_patient_ids():
        try:
            names[pid] = db.get_patient(pid).name
        except Exception:
            names[pid] = pid
    return dict(sorted(names.items(), key=lambda item: item[1]))
