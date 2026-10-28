"""Pydantic data models for patients, check-ins, and summaries."""

from __future__ import annotations
from datetime import date, datetime
from typing import Any
from pydantic import BaseModel, Field


class Medication(BaseModel):
    name: str
    dose: str
    frequency: str


class Condition(BaseModel):
    name: str
    icd_code: str | None = None
    notes: str | None = None


class PatientRecord(BaseModel):
    patient_id: str
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
    patient_id: str
    date: str = Field(default_factory=lambda: date.today().isoformat())
    questions: list[str] = []
    added_by: str = ""   # clinician name or ID


class DailyCheckIn(BaseModel):
    patient_id: str
    date: str = Field(default_factory=lambda: date.today().isoformat())
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    responses: list[CheckInResponse] = []
    free_text_concerns: str = ""   # anything the patient mentioned outside structured Qs


class ClinicalSummary(BaseModel):
    patient_id: str
    date: str
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    summary_markdown: str          # Full Markdown summary for the care team
    flagged_items: list[str] = []  # Short list of items warranting clinician attention
    recommended_action: str = ""   # "routine review" | "schedule visit" | "escalate"
    ai_models: list[str] = []      # models that contributed (empty = rules only); kept for audit
    trend_status: str = ""         # "Worsening" | "Improving" | "Stable" | "Not enough data" (see agents/trends.py)
