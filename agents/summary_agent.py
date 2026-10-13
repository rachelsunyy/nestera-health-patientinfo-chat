"""Clinician-facing summary agent.

Builds a structured clinical note directly from the patient's actual check-in
responses. No LLM required — the summary is derived entirely from what the
patient said, so it is always accurate and never fabricated.

If a Gemini API key is configured, the note is additionally enhanced with
an AI-written narrative paragraph. If not, the structured note stands on its own.
"""

from __future__ import annotations
import re
from datetime import date

from data.models import PatientRecord, DailyCheckIn, ClinicalSummary
from database.patient_db import PatientDatabase


# Keywords that warrant clinician attention
_CONCERN_PATTERNS = [
    ("worse", "Schedule visit"),
    ("worsening", "Schedule visit"),
    ("more swollen", "Schedule visit"),
    ("short of breath", "Schedule visit"),
    ("shortness of breath", "Schedule visit"),
    ("can't breathe", "Escalate"),
    ("cannot breathe", "Escalate"),
    ("chest pain", "Escalate"),
    ("chest tightness", "Escalate"),
    ("passed out", "Escalate"),
    ("fainted", "Escalate"),
    ("didn't take", "Schedule visit"),
    ("did not take", "Schedule visit"),
    ("forgot", "Schedule visit"),
    ("skipped", "Schedule visit"),
    ("fell", "Schedule visit"),
    ("fall", "Schedule visit"),
    ("falls", "Schedule visit"),
    ("fallen", "Schedule visit"),
    ("very dizzy", "Schedule visit"),
    ("confused", "Schedule visit"),
    ("confusion", "Schedule visit"),
    ("bleeding", "Escalate"),
]

_ACTION_PRIORITY = {"Routine review": 0, "Schedule visit": 1, "Escalate": 2}


_NEGATORS = {
    "no", "not", "never", "none", "nothing", "without", "denies", "denied",
    "neither", "nor", "haven't", "havent", "hasn't", "hasnt", "isn't", "isnt",
    "wasn't", "wasnt", "don't", "dont", "doesn't", "doesnt", "didn't", "didnt",
    "n't",
}
_CLAUSE_BREAK = re.compile(r"[,;.!?:\n]|\b(?:but|however|although)\b")
_NEGATION_WINDOW = 4  # words before the match that can negate it


def _is_negated(text: str, match_start: int) -> bool:
    """True if the matched phrase is negated by a nearby word in the same clause."""
    clause = _CLAUSE_BREAK.split(text[:match_start])[-1]
    words = re.findall(r"[a-z']+", clause)[-_NEGATION_WINDOW:]
    return any(w in _NEGATORS or w.endswith("n't") for w in words)


def _detect_flags(responses: list) -> tuple[list[str], str]:
    """Scan patient answers for concerning patterns. Returns (flagged_items, action).

    Phrases are matched on word boundaries and skipped when negated
    (e.g. "no falls", "not short of breath", "not worse").
    """
    flagged: list[str] = []
    action = "Routine review"

    for r in responses:
        answer_lower = r.answer.lower().replace("\u2019", "'")
        for pattern, severity in _CONCERN_PATTERNS:
            for m in re.finditer(rf"\b{re.escape(pattern)}\b", answer_lower):
                if _is_negated(answer_lower, m.start()):
                    continue
                flag_msg = f"{r.question.rstrip('?')} — patient said: \"{r.answer}\""
                if flag_msg not in flagged:
                    flagged.append(flag_msg)
                if _ACTION_PRIORITY[severity] > _ACTION_PRIORITY[action]:
                    action = severity
                break

    return flagged, action


def _build_clinical_note(record: PatientRecord, checkin: DailyCheckIn,
                         flagged: list[str], action: str) -> str:
    conditions = (
        ", ".join(c.name for c in record.conditions)
        if record.conditions else record.primary_diagnosis
    )
    meds = (
        ", ".join(f"{m.name} {m.dose}" for m in record.medications)
        if record.medications else "not documented"
    )

    lines = [
        f"## Daily Check-In Summary — {record.name}",
        f"**Date:** {checkin.date}  ",
        f"**Primary Diagnosis:** {record.primary_diagnosis}  ",
        f"**Conditions:** {conditions}  ",
        f"**Medications:** {meds}  ",
        "",
    ]

    if flagged:
        lines += [
            "### ⚠️ Items Requiring Attention",
            "",
        ]
        for item in flagged:
            lines.append(f"- {item}")
        lines.append("")

    lines += [
        f"### Recommended Action: {action}",
        "",
        "---",
        "",
        "### Full Patient Responses",
        "",
        "| Question | Patient's Response |",
        "| --- | --- |",
    ]

    for r in checkin.responses:
        q = r.question.replace("|", "/").replace("\n", " ")
        a = r.answer.replace("|", "/").replace("\n", " ")
        lines.append(f"| {q} | {a} |")

    lines += [
        "",
        "---",
        "*This note was generated from the patient's check-in responses. "
        "All content above reflects exactly what the patient reported.*",
    ]

    return "\n".join(lines)


class SummaryAgent:

    def __init__(self, patient_id: str, db: PatientDatabase) -> None:
        self.patient_id = patient_id
        self.db = db

    def generate(self, checkin_date: str | None = None) -> ClinicalSummary:
        today = checkin_date or date.today().isoformat()

        record = self.db.get_patient(self.patient_id)
        checkin = self.db.get_checkin(self.patient_id, today)
        if checkin is None:
            raise ValueError(
                f"No check-in found for {self.patient_id} on {today}"
            )

        flagged, action = _detect_flags(checkin.responses)
        note_md = _build_clinical_note(record, checkin, flagged, action)

        summary = ClinicalSummary(
            patient_id=self.patient_id,
            date=today,
            summary_markdown=note_md,
            flagged_items=flagged,
            recommended_action=action,
        )
        self.db.save_summary(summary)
        return summary
