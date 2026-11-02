"""Reading an uploaded patient record: a new patient, an existing one, or readable reasons it was rejected."""

import json
from collections.abc import Collection
from dataclasses import dataclass

from pydantic import ValidationError

from data.models import PatientRecord

EXPECTED = {
    "string_type": "expected text",
    "list_type": "expected a list",
    "model_type": "expected an object with named fields",
    "dict_type": "expected an object with named fields",
}


@dataclass(frozen=True)
class InvalidUpload:
    problems: list[str]


@dataclass(frozen=True)
class NewPatient:
    record: PatientRecord


@dataclass(frozen=True)
class ExistingPatient:
    record: PatientRecord


def field_path(loc: tuple) -> str:
    path = str(loc[0]) if loc else ""
    for part in loc[1:]:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path


def describe(error: dict) -> str:
    path = field_path(error["loc"])
    if error["type"] == "missing":
        return f"Missing required field: {path}"
    if not path:
        return "The file must contain one patient record as a JSON object."
    if error["type"] == "value_error":
        return f"{path}: {error['ctx']['error']}"
    return f"{path}: {EXPECTED.get(error['type'], error['msg'])}"


def read_upload(raw: bytes, existing_ids: Collection[str]) -> InvalidUpload | NewPatient | ExistingPatient:
    try:
        data = json.loads(raw)
    except UnicodeDecodeError:
        return InvalidUpload(["The file is not a text file. Upload a .json file saved as UTF-8 text."])
    except json.JSONDecodeError as e:
        return InvalidUpload([f"The file is not valid JSON: {e.msg} at line {e.lineno}, column {e.colno}."])
    try:
        record = PatientRecord.model_validate(data)
    except ValidationError as e:
        return InvalidUpload([describe(error) for error in e.errors()])
    return ExistingPatient(record) if record.patient_id in existing_ids else NewPatient(record)
