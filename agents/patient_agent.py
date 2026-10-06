"""Patient-facing conversational agent.

Questions are built directly from the patient's own record:
  - doctor-specified questions first
  - then condition-specific questions (using the patient's actual conditions)
  - then medication adherence questions (using the patient's actual drug names)
  - then monitoring parameter questions (using the patient's actual parameters)
  - then base wellness questions

No LLM is used here. Responses are saved to the database on completion.
"""

from __future__ import annotations
import random
from datetime import date

from data.models import PatientRecord, DailyCheckIn, CheckInResponse
from database.patient_db import PatientDatabase


_ACK_PHRASES = [
    "Thank you, I've noted that.",
    "Got it, thank you.",
    "I've recorded that, thank you.",
    "Understood, thank you for sharing.",
    "Noted — thank you.",
]

_BASE_QUESTIONS = [
    "On a scale of 1 to 10, how would you rate your overall well-being today compared to yesterday?",
    "Have you had any falls, felt unsafe, or had any new concerns at home today?",
    "Is there anything else you would like your care team to know?",
]


def _build_system_prompt(record: PatientRecord) -> str:
    return (
        f"You are a Hospital-At-Home check-in assistant for {record.name}. "
        "You collect health information only. You NEVER give medical advice or interpret symptoms. "
        f"Care team contact: {record.care_team_contact}."
    )


def _build_questions(record: PatientRecord, doctor_questions: list[str]) -> list[str]:
    """Build a personalized question list from the patient's actual medical record."""
    questions: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        if q not in seen:
            seen.add(q)
            questions.append(q)

    # 1. Doctor-specified questions go first
    for q in doctor_questions:
        add(q)

    # 2. Condition-specific questions — keyed to this patient's actual conditions
    conditions_text = " ".join(
        c.name.lower() for c in record.conditions
    ) if record.conditions else record.primary_diagnosis.lower()

    if "heart failure" in conditions_text:
        add("Have you weighed yourself today? If yes, what was your weight, and has it gone up or down since yesterday?")
        add("Have you noticed any new or worsening swelling in your legs, ankles, or feet?")
        add("How is your breathing — comfortable at rest, or are you feeling any shortness of breath?")

    if "pneumonia" in conditions_text:
        add("How is your cough today — better, worse, or the same as yesterday? Is it bringing up any mucus?")
        add("How is your breathing — comfortable, or are you feeling short of breath?")
        add("Have you had any fever or chills today?")

    if "diabetes" in conditions_text:
        add("Did you check your blood sugar today? If yes, what were the readings?")
        add("Have you felt any shakiness, sweating, or dizziness that might mean your blood sugar is low?")

    if any(w in conditions_text for w in ("hypertension", "high blood pressure")):
        add("Did you check your blood pressure today? If yes, what was the reading?")

    if "copd" in conditions_text or "emphysema" in conditions_text or "chronic obstructive" in conditions_text:
        add("How is your breathing today compared to your usual baseline?")
        add("Have you needed to use your rescue inhaler today? If yes, how many times?")

    if "stroke" in conditions_text or "tia" in conditions_text:
        add("Have you noticed any new weakness, numbness, or difficulty speaking today?")

    if "kidney" in conditions_text or "renal" in conditions_text:
        add("How much fluid have you been drinking today — more or less than usual?")

    # 3. Monitoring parameter questions — using this patient's actual parameters
    for param in record.monitoring_parameters:
        p = param.lower()
        if any(w in p for w in ("oxygen", "spo2", "saturation", "o2")):
            add("Did you measure your oxygen level (SpO2) today? If yes, what was the reading?")
        elif "temperature" in p or "fever" in p:
            add("Did you take your temperature today? If yes, what was the reading?")
        elif "weight" in p and "have you weighed" not in " ".join(questions).lower():
            add("Did you weigh yourself today? If yes, what was the reading?")
        elif "respiratory rate" in p or "breathing rate" in p:
            add("Did you count or measure your breathing rate today? If yes, what was it?")
        elif "glucose" in p or "blood sugar" in p:
            if "did you check your blood sugar" not in " ".join(questions).lower():
                add("Did you check your blood sugar today? If yes, what were the readings?")

    # 4. Medication adherence — using this patient's actual drug names
    if record.medications:
        med_list = ", ".join(
            f"{m.name} {m.dose}" for m in record.medications
        )
        add(f"Have you taken all your medications today as scheduled? "
            f"(Your medications include: {med_list}.)")

    # 5. Base questions for everyone
    for q in _BASE_QUESTIONS:
        add(q)

    return questions[:10]


class PatientAgent:
    """Manages one daily check-in session for a patient.

    Usage:
        agent = PatientAgent(patient_id, db)
        opening = agent.start_session()   # instant — no LLM
        while True:
            reply, done = agent.respond(patient_input)
            if done: break
        # check-in is auto-saved on completion
    """

    def __init__(self, patient_id: str, db: PatientDatabase) -> None:
        self.patient_id = patient_id
        self.db = db
        self.record: PatientRecord | None = None
        self.questions: list[str] = []
        self.responses: list[CheckInResponse] = []
        self._current_q_index = 0

    def start_session(self) -> str:
        """Load patient record from DB, build question list, return opening message.
        Completely instant — no LLM calls.
        """
        self.record = self.db.get_patient(self.patient_id)
        today = date.today().isoformat()
        doctor_questions = self.db.get_doctor_questions(self.patient_id, today)
        self.questions = _build_questions(self.record, doctor_questions)
        self._current_q_index = 0

        first_name = self.record.name.split()[0]
        n = len(self.questions)
        return (
            f"Hello {first_name}! I'm your Hospital-At-Home check-in assistant. "
            f"I'll ask you {n} questions about how you're feeling today — "
            "your care team will review everything. "
            f"For urgent concerns please call {self.record.care_team_contact}.\n\n"
            f"{self.questions[self._current_q_index]}"
        )

    def respond(self, patient_input: str) -> tuple[str, bool]:
        """Record patient answer; return (next reply, session_complete)."""
        asked_q = self.questions[self._current_q_index]
        self.responses.append(CheckInResponse(question=asked_q, answer=patient_input))
        self._current_q_index += 1

        if self._current_q_index >= len(self.questions):
            self._save_checkin()
            return (
                "Thank you so much for completing today's check-in! "
                "Your care team has been notified and will review your responses. "
                f"For urgent concerns please call {self.record.care_team_contact}. "
                "Take care!",
                True,
            )

        ack = random.choice(_ACK_PHRASES)
        next_q = self.questions[self._current_q_index]
        return f"{ack}\n\n{next_q}", False

    def _save_checkin(self) -> None:
        self.db.save_checkin(DailyCheckIn(
            patient_id=self.patient_id,
            date=date.today().isoformat(),
            responses=self.responses,
        ))
