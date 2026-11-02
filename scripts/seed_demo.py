"""Seed synthetic demo patients for a sponsor walkthrough (see DEMO.md).

Each scenario is a patient record plus an ordered list of check-ins. The check-ins answer the
real questions PatientAgent builds for that patient, are saved with backdated dates, and are
summarised by the real SummaryAgent with AI forced off, so every flag, recommended action and
trend shown in the app comes from the production rules.

Only patients whose id starts with `demo_` are written or removed.

    python scripts/seed_demo.py              # create or refresh the demo patients
    python scripts/seed_demo.py --reset      # also remove every other demo_ patient first
    python scripts/seed_demo.py --data-dir /tmp/demo_data
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import database.patient_db as patient_db  # noqa: E402
from agents.patient_agent import PatientAgent  # noqa: E402
from agents.summary_agent import SummaryAgent  # noqa: E402
from agents.trends import assess_trend  # noqa: E402
from data.models import CheckInResponse, DailyCheckIn, PatientRecord  # noqa: E402

PREFIX = "demo_"

# (substring of a PatientAgent question, topic). The first match wins, so "breathing rate" sits before "breathing".
_TOPICS = [
    ("weigh", "weight"),
    ("swelling", "swelling"),
    ("cough", "cough"),
    ("fever or chills", "fever"),
    ("check your blood sugar", "glucose"),
    ("shakiness", "low_sugar"),
    ("blood pressure", "bp"),
    ("rescue inhaler", "inhaler"),
    ("weakness, numbness", "neuro"),
    ("fluid", "fluid"),
    ("spo2", "spo2"),
    ("temperature", "temperature"),
    ("breathing rate", "resp_rate"),
    ("breathing", "breathing"),
    ("medications", "meds"),
    ("well-being", "wellbeing"),
    ("falls", "safety"),
    ("anything else", "anything_else"),
]

# Unremarkable answers used for any topic a scenario check-in does not mention.
_ROUTINE = {
    "weight": "Yes, 181 pounds, same as yesterday.",
    "swelling": "No new swelling.",
    "cough": "About the same, a little clear mucus.",
    "fever": "No fever or chills.",
    "glucose": "Yes, 128 this morning.",
    "low_sugar": "No, none of that.",
    "bp": "Yes, 126 over 80.",
    "inhaler": "No, I did not need it today.",
    "neuro": "No, nothing new.",
    "fluid": "About the same as usual.",
    "spo2": "Yes, 96.",
    "temperature": "Yes, 98.4.",
    "resp_rate": "About 16.",
    "breathing": "Comfortable at rest.",
    "meds": "Yes, I took all of them on time.",
    "wellbeing": "About a 7, similar to yesterday.",
    "safety": "No falls, I feel safe at home.",
    "anything_else": "No, nothing else right now.",
}


@dataclass(frozen=True)
class CheckIn:
    days_ago: int
    hours_ago: float          # before the current clock time, on that day; kept after midnight
    answers: dict[str, str] = field(default_factory=dict)   # topic -> answer; other topics get _ROUTINE


@dataclass(frozen=True)
class Scenario:
    record: PatientRecord
    checkins: tuple[CheckIn, ...]


def _record(pid: str, name: str, dob: str, diagnosis: str, conditions: list[tuple[str, str]],
            medications: list[tuple[str, str, str]], monitoring: list[str], notes: str) -> PatientRecord:
    assert pid.startswith(PREFIX), pid
    return PatientRecord.model_validate({
        "patient_id": pid,
        "name": name,
        "date_of_birth": dob,
        "care_team_contact": "(312) 555-0100, Demo Hospital-At-Home Program",
        "admission_date": (date.today() - timedelta(days=6)).isoformat(),
        "primary_diagnosis": diagnosis,
        "conditions": [{"name": n, "icd_code": c} for n, c in conditions],
        "medications": [{"name": n, "dose": d, "frequency": f} for n, d, f in medications],
        "monitoring_parameters": monitoring,
        "notes": notes + " Synthetic demo patient.",
    })


SCENARIOS = (
    # Pneumonia, slowly worsening: no single reading crosses a threshold until today.
    Scenario(
        _record("demo_pneumonia", "Walter Briggs", "1951-06-02", "Community-acquired pneumonia",
                [("Community-acquired pneumonia", "J18.9")],
                [("Amoxicillin-clavulanate", "875/125 mg", "twice daily"),
                 ("Acetaminophen", "650 mg", "every 6 hours as needed")],
                ["oxygen saturation (SpO2)", "temperature", "respiratory rate"],
                "Lives with spouse."),
        (
            CheckIn(4, 2, {"spo2": "Yes, 97.", "temperature": "98.9", "resp_rate": "About 17."}),
            CheckIn(3, 2, {"spo2": "96 this morning.", "temperature": "99.1", "resp_rate": "18."}),
            CheckIn(2, 2, {"spo2": "95.", "temperature": "99.4", "resp_rate": "19.",
                           "breathing": "Okay at rest, a bit winded on the stairs."}),
            CheckIn(1, 2, {"spo2": "93.", "temperature": "99.9", "resp_rate": "21.",
                           "cough": "Coughing more, thicker yellow mucus.",
                           "breathing": "Winded walking to the kitchen."}),
            CheckIn(0, 1, {"spo2": "It said 89.", "temperature": "100.6", "resp_rate": "24.",
                           "cough": "Worse, coughing most of the night.",
                           "breathing": "I get short of breath just sitting up.",
                           "wellbeing": "A 4, worse than yesterday."}),
        ),
    ),
    # Heart failure, stable and routine.
    Scenario(
        _record("demo_heartfailure", "Harold Okafor", "1946-11-19", "Heart failure",
                [("Heart failure", "I50.9"), ("Hypertension", "I10")],
                [("Furosemide", "40 mg", "once daily"), ("Carvedilol", "12.5 mg", "twice daily")],
                ["weight", "blood pressure", "oxygen saturation (SpO2)"],
                "Daughter checks in each evening."),
        (
            CheckIn(3, 3, {"weight": "182 pounds, same as yesterday.", "bp": "124 over 78.", "spo2": "96."}),
            CheckIn(2, 3, {"weight": "182, no change.", "bp": "126/80.", "spo2": "97."}),
            CheckIn(1, 3, {"weight": "181 pounds.", "bp": "122 over 76.", "spo2": "96."}),
            CheckIn(0, 3, {"weight": "181, same.", "bp": "125/79.", "spo2": "96."}),
        ),
    ),
    # Diabetes, improving: blood sugar coming back into range.
    Scenario(
        _record("demo_diabetes", "Rosa Delgado", "1958-02-27", "Type 2 diabetes mellitus, hyperglycemia",
                [("Type 2 diabetes mellitus", "E11.65")],
                [("Insulin glargine", "18 units", "at bedtime"), ("Metformin", "1000 mg", "twice daily")],
                ["blood glucose"],
                "Insulin started on admission."),
        (
            CheckIn(4, 2, {"glucose": "Yes, 310 before breakfast.", "wellbeing": "A 5, very thirsty."}),
            CheckIn(3, 2, {"glucose": "265 this morning."}),
            CheckIn(2, 2, {"glucose": "220."}),
            CheckIn(1, 2, {"glucose": "175 before breakfast."}),
            CheckIn(0, 2, {"glucose": "142 this morning.", "wellbeing": "An 8, more energy."}),
        ),
    ),
    # COPD, has not checked in today.
    Scenario(
        _record("demo_copd", "Frank Ellison", "1949-08-08", "COPD exacerbation",
                [("COPD", "J44.1")],
                [("Tiotropium inhaler", "18 mcg", "once daily"), ("Albuterol inhaler", "90 mcg", "as needed")],
                ["oxygen saturation (SpO2)"],
                "Usual SpO2 92 to 94 percent."),
        (
            CheckIn(3, 4, {"spo2": "93.", "inhaler": "Twice."}),
            CheckIn(2, 4, {"spo2": "93.", "inhaler": "Once."}),
            CheckIn(1, 4, {"spo2": "94.", "inhaler": "Once in the evening."}),
        ),
    ),
    # Two check-ins today: a fine morning, then a concerning afternoon or evening.
    Scenario(
        _record("demo_twice", "Samuel Park", "1955-04-14", "Hypertensive urgency",
                [("Hypertension", "I10"), ("Type 2 diabetes mellitus", "E11.9")],
                [("Amlodipine", "10 mg", "once daily"), ("Metformin", "500 mg", "twice daily")],
                ["blood pressure", "blood glucose"],
                "Admitted for blood pressure control."),
        (
            CheckIn(1, 6, {"bp": "134 over 86.", "glucose": "140."}),
            CheckIn(0, 6, {"bp": "132 over 84.", "glucose": "135 before breakfast."}),
            CheckIn(0, 0.25, {"bp": "Just took it again, 172 over 104.", "glucose": "150.",
                              "wellbeing": "A 4. I have a pounding headache and feel very dizzy."}),
        ),
    ),
    # For the live demo: history, but no check-in today.
    Scenario(
        _record("demo_live", "Grace Thompson", "1950-09-30", "Heart failure",
                [("Heart failure", "I50.9")],
                [("Furosemide", "20 mg", "once daily"), ("Lisinopril", "5 mg", "once daily")],
                ["oxygen saturation (SpO2)"],
                "Used for the live check-in during the demo."),
        (
            CheckIn(2, 3, {"weight": "150 pounds.", "spo2": "96."}),
            CheckIn(1, 3, {"weight": "150, same as yesterday.", "spo2": "96."}),
        ),
    ),
)


def _topic(question: str) -> str:
    q = question.lower()
    for needle, topic in _TOPICS:
        if needle in q:
            return topic
    raise ValueError(f"No demo topic for question: {question!r}")


def _timestamp(checkin: CheckIn, now: datetime, order: int) -> datetime:
    day = now.date() - timedelta(days=checkin.days_ago)
    at = datetime.combine(day, now.time()) - timedelta(hours=checkin.hours_ago)
    return max(at, datetime.combine(day, time(0, order + 1)))


def _responses(questions: list[str], answers: dict[str, str], pid: str) -> list[CheckInResponse]:
    topics = [_topic(q) for q in questions]
    unasked = set(answers) - set(topics)
    if unasked:
        raise ValueError(f"{pid}: answers for topics PatientAgent does not ask: {sorted(unasked)}")
    return [CheckInResponse(question=q, answer=answers.get(t, _ROUTINE[t])) for q, t in zip(questions, topics)]


def seed_scenario(db: patient_db.PatientDatabase, scenario: Scenario, now: datetime) -> None:
    pid = scenario.record.patient_id
    db.save_patient(scenario.record)
    agent = PatientAgent(pid, db)
    agent.start_session()
    for order, checkin in enumerate(scenario.checkins):
        ts = _timestamp(checkin, now, order)
        saved = DailyCheckIn(patient_id=pid, date=ts.date().isoformat(), timestamp=ts.isoformat(),
                             responses=_responses(agent.questions, checkin.answers, pid))
        db.save_checkin(saved)
        SummaryAgent(pid, db).generate(saved.id)


def demo_dirs(data_dir: Path) -> list[Path]:
    return sorted(p for p in data_dir.iterdir() if p.is_dir() and p.name.startswith(PREFIX))


def seed(data_dir: Path, reset: bool = False, now: datetime | None = None) -> list[dict]:
    """Converge every scenario patient to its seeded state and return one summary row per patient."""
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    data_dir.mkdir(parents=True, exist_ok=True)
    patient_db.DATA_DIR = data_dir
    config.AI_ASSIST_ENABLED = False      # no network, no key, no audit entries: rules only

    targets = demo_dirs(data_dir) if reset else [data_dir / s.record.patient_id for s in SCENARIOS]
    for path in targets:
        if path.is_dir():
            shutil.rmtree(path)

    db = patient_db.MockPatientDatabase()
    for scenario in SCENARIOS:
        seed_scenario(db, scenario, now)
    return [summary_row(db, s.record.patient_id, now.date().isoformat()) for s in SCENARIOS]


def summary_row(db: patient_db.PatientDatabase, pid: str, today: str) -> dict:
    checkins = db.get_recent_checkins(pid, n=1000)
    return {
        "patient": pid,
        "name": db.get_patient(pid).name,
        "check-ins": len(checkins),
        "today": len(db.get_checkins_for_date(pid, today)),
        "latest action": db.get_summary(pid, checkins[0].id).recommended_action,
        "trend": assess_trend(checkins).status,
    }


def format_table(rows: list[dict]) -> str:
    headers = list(rows[0])
    widths = [max(len(h), *(len(str(r[h])) for r in rows)) for h in headers]

    def line(cells) -> str:
        return "  ".join(str(c).ljust(w) for c, w in zip(cells, widths)).rstrip()

    return "\n".join([line(headers), line("-" * w for w in widths), *(line(r.values()) for r in rows)])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=config.DATA_DIR,
                        help=f"where patient folders live (default: {config.DATA_DIR})")
    parser.add_argument("--reset", action="store_true",
                        help="remove every demo_ patient folder before seeding, including ones no scenario uses")
    args = parser.parse_args(argv)
    rows = seed(args.data_dir.resolve(), reset=args.reset)
    print(f"Seeded {len(rows)} demo patients in {args.data_dir.resolve()}\n")
    print(format_table(rows))


if __name__ == "__main__":
    main()
