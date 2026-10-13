"""Keyword flagging (with negation) and the overall recommended action."""

import pytest

from agents.summary_agent import _detect_flags
from data.models import CheckInResponse

Q = "How are you feeling today?"


def action_for(answer: str, question: str = Q) -> str:
    return _detect_flags([CheckInResponse(question=question, answer=answer)])[1]


@pytest.mark.parametrize("answer", [
    "No falls, no problems",
    "I have no shortness of breath",
    "Not worse, feeling great",
    "no chest pain",
    "I have never been short of breath",
    "waterfall trip with the kids",
    "Fine",
])
def test_negated_or_benign_answers_are_routine(answer):
    assert action_for(answer) == "Routine review"


@pytest.mark.parametrize("answer, expected", [
    ("I fell yesterday", "Schedule visit"),
    ("I did not take my metformin", "Schedule visit"),
    ("I didn’t take the evening dose", "Schedule visit"),
    ("I've been short of breath", "Schedule visit"),
    ("Chest pain since this morning", "Escalate"),
    ("Chest pain since morning, no fever", "Escalate"),
    ("never short of breath but I forgot my pills", "Schedule visit"),
    ("I passed out in the bathroom", "Escalate"),
])
def test_concerning_answers_are_flagged(answer, expected):
    assert action_for(answer) == expected


def test_highest_severity_wins_across_answers():
    flagged, action = _detect_flags([
        CheckInResponse(question="Q1?", answer="I forgot my pills"),
        CheckInResponse(question="Q2?", answer="chest pain"),
    ])
    assert action == "Escalate"
    assert len(flagged) == 2


def test_flag_message_includes_question_and_answer():
    flagged, _ = _detect_flags([CheckInResponse(question="Any falls?", answer="I fell")])
    assert flagged == ['Patient said "I fell" when asked: Any falls?']
