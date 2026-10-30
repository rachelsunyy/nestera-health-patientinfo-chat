"""Import patients from Synthea (https://github.com/synthetichealth/synthea, Apache-2.0) CSV exports.

  python -m data.synthea_import --src external_data/synthea                 # report only
  python -m data.synthea_import --src external_data/synthea --register      # also add the patients to the app database
  python -m data.synthea_import --src external_data/synthea --vitals-out evals/synthea_vitals.jsonl

What it does
  1. Maps Synthea's SNOMED condition names onto the conditions our question builder understands
     (heart failure, COPD, pneumonia, stroke, kidney disease, type 2 diabetes, hypertension).
  2. Builds a PatientRecord for every patient who has at least one such condition, including
     active medications, allergies, and monitoring parameters implied by the conditions.
  3. Reports which conditions Synthea patients have that the app has NO questions for.
  4. Optionally turns each patient's latest recorded vital signs into labeled check-ins
     (expected action from the documented thresholds, not from the rules).

Synthea patients are fully synthetic, so no PHI is involved. The sample download is only ~100 patients;
to get many more with the conditions that matter for Hospital-at-Home, run Synthea itself (needs Java) with
module filters and point --src at its output/csv folder.
"""

from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.patient_agent import _build_questions  # noqa: E402
from data.models import Condition, Medication, PatientRecord  # noqa: E402

CARE_TEAM = "(000) 555-0100 — Synthetic Hospital-at-Home program"

# (regex on Synthea description, our condition label, monitoring parameters it implies, has a question template)
CONDITION_MAP = [
    (r"pneumonia", "Community-acquired pneumonia", ["oxygen saturation (SpO2)", "temperature", "respiratory rate"], True),
    (r"heart failure", "Heart failure", ["weight", "blood pressure", "oxygen saturation (SpO2)"], True),
    (r"emphysema|chronic obstructive", "COPD", ["oxygen saturation (SpO2)", "respiratory rate"], True),
    (r"stroke|cerebrovascular", "Stroke", ["blood pressure"], True),
    (r"kidney disease|renal failure|kidney due to", "Chronic kidney disease", ["blood pressure", "weight"], True),
    (r"^diabetes mellitus type 2", "Type 2 diabetes mellitus", ["blood glucose"], True),
    (r"essential hypertension|^hypertension", "Hypertension", ["blood pressure"], True),
    # Conditions Synthea produces that the app has no questions for (reported as a coverage gap):
    (r"^asthma", "Asthma", ["oxygen saturation (SpO2)", "respiratory rate"], False),
    (r"sepsis", "Sepsis", ["temperature", "blood pressure", "respiratory rate", "oxygen saturation (SpO2)"], False),
    (r"myocardial infarction", "Myocardial infarction", ["blood pressure", "weight"], False),
]
ACUTE = re.compile(r"pneumonia|sepsis|myocardial infarction|stroke|cerebrovascular", re.I)   # kept even if resolved
PRIORITY = ["Heart failure", "COPD", "Community-acquired pneumonia", "Stroke", "Chronic kidney disease",
            "Sepsis", "Myocardial infarction", "Asthma", "Type 2 diabetes mellitus", "Hypertension"]
_STRENGTH = re.compile(r"\d[\d.,]*\s*(?:MG|MCG|G|ML|UNT|MEQ)(?:/[\d.]*\s*(?:ML|HR|ACTUAT|G|MG))?", re.I)


def clean_name(synthea_name: str) -> str:
    """Synthea first/last names carry numeric suffixes (e.g. 'Maximina916')."""
    return re.sub(r"\d+", "", synthea_name)


def load_tables(src: Path) -> dict[str, list[dict]]:
    tables = {}
    for name in ("patients", "conditions", "medications", "allergies", "observations"):
        path = src / f"{name}.csv"
        tables[name] = list(csv.DictReader(path.open(encoding="utf8"))) if path.exists() else []
    if not tables["patients"] or not tables["conditions"]:
        raise SystemExit(f"{src} does not look like a Synthea CSV export (patients.csv / conditions.csv missing)")
    return tables


def map_conditions(rows: list[dict]) -> list[tuple[str, bool, str, list[str], bool]]:
    """-> [(label, acute, start_date, monitoring, has_questions)] for this patient's relevant conditions."""
    found: dict[str, tuple] = {}
    for r in rows:
        desc = r["DESCRIPTION"]
        if "history of" in desc.lower() or "awaiting" in desc.lower():
            continue
        if r["STOP"] and not ACUTE.search(desc):
            continue                                   # a resolved minor condition is not part of the current picture
        for pattern, label, monitoring, covered in CONDITION_MAP:
            if re.search(pattern, desc, re.I):
                prev = found.get(label)
                if prev is None or r["START"] > prev[2]:
                    found[label] = (label, bool(ACUTE.search(desc)), r["START"][:10], monitoring, covered)
                break
    return sorted(found.values(), key=lambda t: PRIORITY.index(t[0]))


def to_records(tables: dict[str, list[dict]]) -> tuple[list[PatientRecord], list[dict]]:
    by_patient = defaultdict(lambda: defaultdict(list))
    for table in ("conditions", "medications", "allergies"):
        for r in tables[table]:
            by_patient[r["PATIENT"]][table].append(r)
    records, meta = [], []
    for p in tables["patients"]:
        if p["DEATHDATE"]:
            continue
        mapped = map_conditions(by_patient[p["Id"]]["conditions"])
        if not mapped:
            continue
        meds = [m for m in by_patient[p["Id"]]["medications"] if not m["STOP"]]
        seen, medications = set(), []
        for m in meds:
            name = re.sub(r"\s*\(.*?\)\s*$", "", m["DESCRIPTION"]).strip()
            if name.lower() in seen or len(medications) >= 6:
                continue
            seen.add(name.lower())
            strength = _STRENGTH.search(name)
            medications.append(Medication(name=name, dose=strength.group(0) if strength else "per label",
                                          frequency="as prescribed"))
        monitoring = []
        for _, _, _, params, _ in mapped:
            monitoring += [x for x in params if x not in monitoring]
        allergies = sorted({a["DESCRIPTION"] for a in by_patient[p["Id"]]["allergies"] if not a["STOP"]})
        primary = mapped[0]
        records.append(PatientRecord(
            patient_id=f"synthea_{p['Id'][:8]}",
            name=f"{clean_name(p['FIRST'])} {clean_name(p['LAST'])}".strip(),
            date_of_birth=p["BIRTHDATE"], care_team_contact=CARE_TEAM, admission_date=primary[2],
            primary_diagnosis=primary[0], conditions=[Condition(name=c[0]) for c in mapped],
            medications=medications, monitoring_parameters=monitoring, known_allergies=allergies,
            notes="Imported from Synthea (synthetic). No real patient data.",
        ))
        meta.append({"patient_id": records[-1].patient_id, "synthea_id": p["Id"], "conditions": [c[0] for c in mapped],
                     "uncovered": [c[0] for c in mapped if not c[4]]})
    return records, meta


def question_coverage(record: PatientRecord) -> dict:
    """How many questions come from the patient's conditions (vs. the generic ones everyone gets)."""
    generic = PatientRecord(**{**record.model_dump(), "conditions": [], "primary_diagnosis": "none"})
    with_conditions = _build_questions(record, [])
    baseline = set(_build_questions(generic, []))
    return {"total": len(with_conditions), "condition_specific": sum(1 for q in with_conditions if q not in baseline)}


# ── Vital-sign check-ins from Synthea observations ───────────────────────────────────────────
VITAL_QUESTIONS = {
    "bp": "Did you check your blood pressure today? If yes, what was the reading?",
    "resp": "Did you count or measure your breathing rate today? If yes, what was it?",
    "temp": "Did you take your temperature today? If yes, what was it?",
}


def _bp_label(s, d): return "Escalate" if (s >= 180 or d >= 120 or s < 80) else "Schedule visit" if (s >= 160 or d >= 100 or s < 90) else "Routine review"
def _resp_label(r): return "Escalate" if r > 30 else "Schedule visit" if r > 24 else "Routine review"
def _temp_label(c):
    f = c * 9 / 5 + 32
    return "Escalate" if f >= 103 else "Schedule visit" if (f >= 100.4 or f < 95) else "Routine review"


def vitals_cases(tables: dict[str, list[dict]], records: list[PatientRecord], meta: list[dict]) -> list[dict]:
    """One labeled check-in per patient from their most recent encounter that has the readings."""
    wanted = {m["synthea_id"]: r for m, r in zip(meta, records)}
    latest: dict[str, dict[str, tuple[str, str]]] = defaultdict(dict)   # patient -> description -> (date, value)
    for o in tables["observations"]:
        if o["PATIENT"] in wanted and o["DESCRIPTION"] in ("Systolic Blood Pressure", "Diastolic Blood Pressure",
                                                           "Respiratory rate", "Body temperature"):
            prev = latest[o["PATIENT"]].get(o["DESCRIPTION"])
            if prev is None or o["DATE"] > prev[0]:
                latest[o["PATIENT"]][o["DESCRIPTION"]] = (o["DATE"], o["VALUE"])
    cases = []
    for pid, vals in latest.items():
        rec = wanted[pid]
        responses, labels = [], []
        if "Systolic Blood Pressure" in vals and "Diastolic Blood Pressure" in vals:
            s, d = round(float(vals["Systolic Blood Pressure"][1])), round(float(vals["Diastolic Blood Pressure"][1]))
            responses.append({"question": VITAL_QUESTIONS["bp"], "answer": f"{s}/{d}"}); labels.append(_bp_label(s, d))
        if "Respiratory rate" in vals:
            r = round(float(vals["Respiratory rate"][1]))
            responses.append({"question": VITAL_QUESTIONS["resp"], "answer": str(r)}); labels.append(_resp_label(r))
        if "Body temperature" in vals:
            t = float(vals["Body temperature"][1])
            responses.append({"question": VITAL_QUESTIONS["temp"], "answer": f"{t:.1f} C"}); labels.append(_temp_label(t))
        if not responses:
            continue
        order = {"Routine review": 0, "Schedule visit": 1, "Escalate": 2}
        cases.append({"id": f"synthea_vitals_{rec.patient_id}", "conditions": [c.name for c in rec.conditions],
                      "expected_action": max(labels, key=order.get), "note": "Latest recorded vitals from Synthea",
                      "responses": responses, "category": "synthea_vitals", "source": "synthea", "split": "test"})
    return cases


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, required=True, help="folder holding Synthea's CSV export")
    ap.add_argument("--register", action="store_true", help="save the patients into the app's database")
    ap.add_argument("--vitals-out", type=Path, help="write vital-sign check-ins as eval cases (jsonl)")
    args = ap.parse_args()

    tables = load_tables(args.src)
    records, meta = to_records(tables)
    print(f"{len(tables['patients'])} Synthea patients, {len(records)} with a condition the app can use")

    by_label = Counter(c for m in meta for c in m["conditions"])
    print("\nConditions among imported patients:")
    for label, n in by_label.most_common():
        gap = "  <- no question template in the app" if label in {m[1] for m in CONDITION_MAP if not m[3]} else ""
        print(f"  {n:3d}  {label}{gap}")
    cov = [question_coverage(r) for r in records]
    none = sum(1 for c in cov if c["condition_specific"] == 0)
    print(f"\nQuestion coverage: {len(records) - none}/{len(records)} patients get at least one condition-specific question; "
          f"{none} get only the generic ones.")

    if args.register:
        from database.patient_db import MockPatientDatabase
        db = MockPatientDatabase()
        for r in records:
            db.save_patient(r)
        print(f"\nRegistered {len(records)} patients in the app database.")
    if args.vitals_out:
        cases = vitals_cases(tables, records, meta)
        args.vitals_out.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
        print(f"\nWrote {len(cases)} vital-sign check-ins to {args.vitals_out}  "
              f"({Counter(c['expected_action'] for c in cases)})")


if __name__ == "__main__":
    main()
