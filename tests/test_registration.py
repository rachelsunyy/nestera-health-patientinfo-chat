"""Reading an uploaded patient record into a new patient, an existing patient, or readable problems."""

import json
from pathlib import Path

from views.registration import ExistingPatient, InvalidUpload, NewPatient, read_upload

SAMPLE = json.loads((Path(__file__).parent.parent / "sample_data" / "patient_001.json").read_text())


def upload(**changes) -> bytes:
    data = {**SAMPLE, **changes}
    return json.dumps({k: v for k, v in data.items() if v is not ...}).encode()


def test_unknown_id_is_a_new_patient():
    result = read_upload(upload(patient_id="p_new", name="Ann Lee"), {"patient_001"})
    assert isinstance(result, NewPatient)
    assert (result.record.patient_id, result.record.name) == ("p_new", "Ann Lee")


def test_id_already_registered_is_an_existing_patient():
    result = read_upload(upload(name="Someone Else"), {"patient_001", "patient_002"})
    assert isinstance(result, ExistingPatient)
    assert result.record.name == "Someone Else"


def test_validation_problems_read_as_one_line_per_field():
    result = read_upload(upload(date_of_birth=..., admission_date=20260101, medications="aspirin",
                                conditions=[{"name": 7}]), set())
    assert result == InvalidUpload([
        "Missing required field: date_of_birth",
        "admission_date: expected text",
        "conditions[0].name: expected text",
        "medications: expected a list",
    ])


def test_a_file_that_is_not_one_json_object_is_rejected_plainly():
    assert read_upload(b"[1, 2]", set()) == InvalidUpload(["The file must contain one patient record as a JSON object."])
    broken = read_upload(b'{"patient_id": "x",', set())
    assert isinstance(broken, InvalidUpload)
    assert broken.problems[0].startswith("The file is not valid JSON:")
    assert read_upload("é".encode("latin-1"), set()) == InvalidUpload(
        ["The file is not a text file. Upload a .json file saved as UTF-8 text."])
