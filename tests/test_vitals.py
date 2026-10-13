"""Numeric vital-sign thresholds."""

import pytest

from agents.summary_agent import _detect_flags
from data.models import CheckInResponse

SPO2 = "Did you measure your oxygen level (SpO2) today? If yes, what was the reading?"
TEMP = "Did you take your temperature today? If yes, what was the reading?"
BP = "Did you check your blood pressure today? If yes, what was the reading?"
GLUCOSE = "Did you check your blood sugar today? If yes, what were the readings?"
RESP = "Did you count or measure your breathing rate today? If yes, what was it?"
HYPO = "Have you felt any shakiness, sweating, or dizziness that might mean your blood sugar is low?"


def action_for(question: str, answer: str) -> str:
    return _detect_flags([CheckInResponse(question=question, answer=answer)])[1]


@pytest.mark.parametrize("question, answer, expected", [
    (SPO2, "88%", "Escalate"),
    (SPO2, "91", "Schedule visit"),
    (SPO2, "97 on room air", "Routine review"),
    (SPO2, "I didn't check", "Routine review"),
    (TEMP, "103.2 F", "Escalate"),
    (TEMP, "101.5", "Schedule visit"),
    (TEMP, "38.5 C", "Schedule visit"),
    (TEMP, "98.6", "Routine review"),
    (TEMP, "37", "Routine review"),
    (BP, "190/110", "Escalate"),
    (BP, "165 over 95", "Schedule visit"),
    (BP, "85/50", "Schedule visit"),
    (BP, "120/80", "Routine review"),
    (GLUCOSE, "45", "Escalate"),
    (GLUCOSE, "320", "Escalate"),
    (GLUCOSE, "260", "Schedule visit"),
    (GLUCOSE, "110 and 95", "Routine review"),
    (RESP, "28", "Schedule visit"),
    (RESP, "16", "Routine review"),
])
def test_vital_thresholds(question, answer, expected):
    assert action_for(question, answer) == expected


def test_worst_of_several_readings_is_used():
    assert action_for(GLUCOSE, "110 in the morning, 45 this afternoon") == "Escalate"


def test_numbers_in_symptom_questions_are_ignored():
    assert action_for(HYPO, "Yes, around 3 times, 100% sure") == "Routine review"


def test_flag_message_names_the_reading():
    flagged, _ = _detect_flags([CheckInResponse(question=SPO2, answer="88%")])
    assert flagged[0].startswith("Low oxygen saturation: 88%")
