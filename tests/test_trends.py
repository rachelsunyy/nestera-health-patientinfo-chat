"""Longitudinal trend tracking across days."""

import pytest

from agents.summary_agent import SummaryAgent
from agents.trends import IMPROVING, INSUFFICIENT, STABLE, WORSENING, assess_trend
from agents.vitals import vital_key, vital_reading
from data.models import CheckInResponse, DailyCheckIn

SPO2 = "Did you measure your oxygen level (SpO2) today? If yes, what was the reading?"
TEMP = "Did you take your temperature today? If yes, what was the reading?"
BP = "Did you check your blood pressure today? If yes, what was the reading?"
COUGH = "How is your cough today — better, worse, or the same as yesterday?"


def day(d, *pairs, pid="patient_001"):
    return DailyCheckIn(patient_id=pid, date=d,
                        responses=[CheckInResponse(question=q, answer=a) for q, a in pairs])


# ── reading extraction ────────────────────────────────────────────────────

@pytest.mark.parametrize("key, answer, expected", [
    ("spo2", "96% on room air", 96),
    ("spo2", "97 then 93", 93),
    ("spo2", "BP was 120/80, sat 95", 95),
    ("temperature", "101.2 F", 101.2),
    ("temperature", "38 C", pytest.approx(100.4)),
    ("blood_pressure", "165 over 95", 165),
    ("resp_rate", "22", 22),
    ("spo2", "I didn't check", None),
])
def test_vital_reading(key, answer, expected):
    assert vital_reading(key, answer) == expected


def test_vital_key_uses_topic_or_question():
    assert vital_key(SPO2) == "spo2"
    assert vital_key("anything", topic="temperature") == "temperature"
    assert vital_key(COUGH) is None


# ── trend rules ───────────────────────────────────────────────────────────

def test_one_checkin_is_not_enough():
    assert assess_trend([day("2026-10-01", (SPO2, "96"))]).status == INSUFFICIENT


def test_falling_oxygen_is_worsening_even_inside_the_normal_range():
    report = assess_trend([day("2026-10-01", (SPO2, "98")), day("2026-10-02", (SPO2, "97")),
                           day("2026-10-03", (SPO2, "95"))])
    assert report.status == WORSENING
    assert any("Oxygen saturation" in r and "98% → 97% → 95%" in r for r in report.reasons)


def test_rising_temperature_is_worsening():
    report = assess_trend([day("2026-10-01", (TEMP, "98.2")), day("2026-10-02", (TEMP, "99.4"))])
    assert report.status == WORSENING


def test_oxygen_recovering_is_improving():
    report = assess_trend([day("2026-10-01", (SPO2, "90")), day("2026-10-02", (SPO2, "93")),
                           day("2026-10-03", (SPO2, "96"))])
    assert report.status == IMPROVING


def test_flat_readings_are_stable():
    report = assess_trend([day("2026-10-01", (SPO2, "97"), (COUGH, "same")),
                           day("2026-10-02", (SPO2, "97"), (COUGH, "same"))])
    assert report.status == STABLE


def test_persistent_worse_reports_are_worsening_but_negated_ones_are_not():
    worse = assess_trend([day("2026-10-01", (COUGH, "worse")), day("2026-10-02", (COUGH, "a bit worse")),
                          day("2026-10-03", (COUGH, "worse"))])
    assert worse.status == WORSENING
    not_worse = assess_trend([day("2026-10-01", (COUGH, "not worse")), day("2026-10-02", (COUGH, "no worse"))])
    assert not_worse.status == STABLE


def test_not_better_counts_as_worse_not_better():
    report = assess_trend([day("2026-10-01", (COUGH, "same")), day("2026-10-02", (COUGH, "not better"))])
    assert report.status == WORSENING


def test_recommended_action_rising_is_worsening():
    report = assess_trend([day("2026-10-01", (COUGH, "same")), day("2026-10-02", (SPO2, "88"))])
    assert report.status == WORSENING


def test_symptoms_improving_after_a_bad_day():
    report = assess_trend([day("2026-10-01", (COUGH, "worse")), day("2026-10-02", (COUGH, "much better"))])
    assert report.status == IMPROVING


def test_checkins_are_ordered_by_date_not_by_input_order():
    report = assess_trend([day("2026-10-03", (SPO2, "95")), day("2026-10-01", (SPO2, "98")),
                           day("2026-10-02", (SPO2, "97"))])
    assert report.points[-1].date == "2026-10-03" and report.status == WORSENING


def test_a_missing_reading_today_does_not_invent_a_trend():
    report = assess_trend([day("2026-10-01", (SPO2, "98")), day("2026-10-02", (SPO2, "I didn't check"))])
    assert report.status == STABLE


# ── integration with the clinical note ────────────────────────────────────

def test_worsening_trend_raises_a_routine_day_and_lands_in_the_note(db):
    for d, v in (("2026-10-01", "98"), ("2026-10-02", "97"), ("2026-10-03", "95")):
        db.save_checkin(day(d, (SPO2, v)))
    summary = SummaryAgent("patient_001", db).generate("2026-10-03")
    assert summary.trend_status == WORSENING
    assert summary.recommended_action == "Schedule visit"
    assert any(f.startswith("Worsening trend:") for f in summary.flagged_items)
    assert "### Trend over recent check-ins: Worsening" in summary.summary_markdown


def test_regenerating_an_old_summary_ignores_later_checkins(db):
    for d, v in (("2026-10-01", "98"), ("2026-10-02", "97"), ("2026-10-03", "88")):
        db.save_checkin(day(d, (SPO2, v)))
    assert SummaryAgent("patient_001", db).generate("2026-10-02").trend_status == STABLE


def test_a_first_checkin_has_no_trend_section(db):
    db.save_checkin(day("2026-10-01", (SPO2, "96")))
    summary = SummaryAgent("patient_001", db).generate("2026-10-01")
    assert summary.trend_status == INSUFFICIENT and "Trend over" not in summary.summary_markdown
    assert summary.recommended_action == "Routine review"
