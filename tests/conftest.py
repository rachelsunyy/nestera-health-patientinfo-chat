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


@pytest.fixture(autouse=True)
def ai_off_by_default(monkeypatch):
    """A developer's .env may enable AI; tests must never build a real client or spend API credit."""
    monkeypatch.setattr(config, "AI_ASSIST_ENABLED", False)
    monkeypatch.setattr(config, "AI_CONVERSATION_ENABLED", False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A MockPatientDatabase that writes to a temporary folder, with the sample patients loaded."""
    monkeypatch.setattr(patient_db, "DATA_DIR", tmp_path)
    database = MockPatientDatabase()
    for f in sorted(SAMPLE_DIR.glob("patient_*.json")):
        database.save_patient(PatientRecord.model_validate(json.loads(f.read_text())))
    return database


@pytest.fixture
def open_page():
    """Open a page through the real router, as a browser visiting its URL would."""
    from streamlit.testing.v1 import AppTest

    def open_(page: str | None = None, **query: str):
        at = AppTest.from_file(str(Path(__file__).parent.parent / "streamlit_app.py"), default_timeout=60)
        at.query_params.update(query)
        at.run()
        if page:
            at.switch_page(f"views/{page}.py").run()
        assert not at.exception
        return at

    return open_
