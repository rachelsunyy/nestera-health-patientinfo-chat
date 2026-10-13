"""Question building, the check-in session, and summary generation end to end."""

from datetime import date

from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent
from data.models import DoctorQuestions


def run_checkin(agent: PatientAgent, answer="Doing fine") -> None:
    done = False
    while not done:
        _, done = agent.respond(answer)


def test_questions_are_personalised_and_capped(db):
    agent = PatientAgent("patient_001", db)  # pneumonia + diabetes + hypertension
    agent.start_session()
    qs = " ".join(agent.questions).lower()
    assert "cough" in qs and "blood sugar" in qs and "blood pressure" in qs
    assert 1 <= len(agent.questions) <= 10
    assert len(set(agent.questions)) == len(agent.questions)


def test_doctor_questions_come_first(db):
    db.save_doctor_questions(DoctorQuestions(
        patient_id="patient_001", questions=["Did you sleep well?"], added_by="Dr. Test"))
    agent = PatientAgent("patient_001", db)
    agent.start_session()
    assert agent.questions[0] == "Did you sleep well?"


def test_checkin_saves_and_reports_progress(db):
    agent = PatientAgent("patient_001", db)
    agent.start_session()
    total = len(agent.questions)
    assert agent.progress == (0, total)
    agent.respond("Better")
    assert agent.progress == (1, total)
    run_checkin(agent)
    saved = db.get_checkin("patient_001", date.today().isoformat())
    assert saved is not None and len(saved.responses) == total


def test_healthy_checkin_is_routine_review(db):
    agent = PatientAgent("patient_002", db)
    agent.start_session()
    run_checkin(agent, "No problems, feeling fine")
    summary = SummaryAgent("patient_002", db).generate()
    assert summary.recommended_action == "Routine review"
    assert summary.flagged_items == []


def test_concerning_checkin_is_flagged_and_saved(db):
    agent = PatientAgent("patient_001", db)
    agent.start_session()
    agent.respond("I fell yesterday")
    run_checkin(agent, "Fine")
    summary = SummaryAgent("patient_001", db).generate()
    assert summary.recommended_action == "Schedule visit"
    assert db.get_summary("patient_001", date.today().isoformat()) is not None
    assert "Items Requiring Attention" in summary.summary_markdown


def test_summary_without_checkin_raises(db):
    import pytest
    with pytest.raises(ValueError):
        SummaryAgent("patient_003", db).generate()
