import json
from pathlib import Path

import pytest

import config
import database.patient_db as patient_db
from data.models import PatientRecord
from database.patient_db import MockPatientDatabase

SAMPLE_DIR = Path(__file__).parent.parent / "sample_data"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep every test away from the real patient_data/ folder (including the AI audit log)."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A MockPatientDatabase that writes to a temporary folder, with the sample patients loaded."""
    monkeypatch.setattr(patient_db, "DATA_DIR", tmp_path)
    database = MockPatientDatabase()
    for f in sorted(SAMPLE_DIR.glob("patient_*.json")):
        database.save_patient(PatientRecord.model_validate(json.loads(f.read_text())))
    return database
