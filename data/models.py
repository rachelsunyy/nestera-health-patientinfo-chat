"""Pydantic data models for patients, check-ins, and summaries."""

from __future__ import annotations
import re
from datetime import date, datetime
from typing import Annotated, Any
from pydantic import AfterValidator, BaseModel, Field, model_validator

# Ids become folder and object-name segments, so neither pattern admits a slash, a backslash, whitespace or "..".
PATIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
CHECKIN_ID = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(T[0-9]{2}-[0-9]{2}-[0-9]{2}(\.[0-9]{1,6})?)?")


def validate_patient_id(value: str) -> str:
    if not PATIENT_ID.fullmatch(value):
        raise ValueError("A patient id must be 1 to 64 letters, digits, underscores or hyphens.")
    return value


def validate_checkin_id(value: str) -> str:
    if not CHECKIN_ID.fullmatch(value):
        raise ValueError("A check-in id must be a date like 2026-10-29 or a date and time like 2026-11-01T17-30-05.123456.")
    return value


PatientId = Annotated[str, AfterValidator(validate_patient_id)]
CheckinId = Annotated[str, AfterValidator(validate_checkin_id)]


class Medication(BaseModel):
    name: str
    dose: str
    frequency: str


class Condition(BaseModel):
    name: str
    icd_code: str | None = None
    notes: str | None = None


class PatientRecord(BaseModel):
    patient_id: PatientId
    name: str
    date_of_birth: str          # ISO-8601 date string
    care_team_contact: str      # Phone / email shown to patient when they need help
    admission_date: str         # Date admitted to Hospital-at-Home program
    primary_diagnosis: str
    conditions: list[Condition] = []
    medications: list[Medication] = []
    monitoring_parameters: list[str] = []  # e.g. ["blood pressure", "oxygen saturation"]
    known_allergies: list[str] = []
    notes: str = ""


class CheckInResponse(BaseModel):
    question: str            # the question text actually shown to the patient
    answer: str              # the patient's own words
    topic: str = ""          # what the question was about (e.g. "spo2"); lets checks work on reworded questions


class DoctorQuestions(BaseModel):
    """Questions a doctor/nurse adds for a specific patient's next check-in."""
    patient_id: PatientId
    date: str = Field(default_factory=lambda: date.today().isoformat())
    questions: list[str] = []
    added_by: str = ""   # clinician name or ID


class DailyCheckIn(BaseModel):
    patient_id: PatientId
    id: str = ""                   # storage key; several check-ins can share a date
    date: str = Field(default_factory=lambda: date.today().isoformat())
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    responses: list[CheckInResponse] = []
    free_text_concerns: str = ""   # anything the patient mentioned outside structured Qs

    @model_validator(mode="after")
    def _default_id(self) -> DailyCheckIn:
        # Date plus wall-clock time, filesystem safe, so sorting ids sorts check-ins chronologically.
        # Legacy records stored as <date>.json get id == date from the database layer, which sorts first.
        if not self.id:
            self.id = f"{self.date}T{self.timestamp.partition('T')[2].replace(':', '-')}"
        return self


class ClinicalSummary(BaseModel):
    patient_id: PatientId
    date: str
    checkin_id: str = ""           # the check-in this note describes; legacy notes default to their date
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    summary_markdown: str          # Full Markdown summary for the care team
    flagged_items: list[str] = []  # Short list of items warranting clinician attention
    recommended_action: str = ""   # "routine review" | "schedule visit" | "escalate"
    ai_models: list[str] = []      # models that contributed (empty = rules only); kept for audit
    trend_status: str = ""         # "Worsening" | "Improving" | "Stable" | "Not enough data" (see agents/trends.py)

    @model_validator(mode="after")
    def _default_checkin_id(self) -> ClinicalSummary:
        if not self.checkin_id:
            self.checkin_id = self.date
        return self
