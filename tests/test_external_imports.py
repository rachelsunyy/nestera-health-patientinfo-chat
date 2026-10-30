"""Synthea and NoteChat importers, tested on tiny inline fixtures (never the downloaded data)."""

import csv
import json

from data.notechat_import import ACTIONS, labels_to_cases, parse_turns, replies, write_sheet
from data.synthea_import import load_tables, question_coverage, to_records, vitals_cases


def write_csv(path, header, rows):
    with path.open("w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


PAT = ["Id", "BIRTHDATE", "DEATHDATE", "FIRST", "LAST"]
COND = ["START", "STOP", "PATIENT", "ENCOUNTER", "SYSTEM", "CODE", "DESCRIPTION"]
MED = ["START", "STOP", "PATIENT", "PAYER", "ENCOUNTER", "CODE", "DESCRIPTION"]
OBS = ["DATE", "PATIENT", "ENCOUNTER", "CATEGORY", "CODE", "DESCRIPTION", "VALUE", "UNITS", "TYPE"]


def synthea_dir(tmp_path):
    write_csv(tmp_path / "patients.csv", PAT, [
        ["p1aaaaaa-1", "1950-02-03", "", "Maximina916", "Schiller186"],     # emphysema + diabetes, active
        ["p2bbbbbb-2", "1940-01-01", "2012-08-05", "Old1", "Gone2"],       # heart failure but deceased
        ["p3cccccc-3", "1980-05-05", "", "Well3", "Person4"],              # only a resolved cold: not relevant
        ["p4dddddd-4", "1960-06-06", "", "Wheeze5", "Only6"],              # asthma only: no question template
    ])
    write_csv(tmp_path / "conditions.csv", COND, [
        ["2010-01-01", "", "p1aaaaaa-1", "e", "SNOMED-CT", "1", "Pulmonary emphysema (disorder)"],
        ["2011-01-01", "", "p1aaaaaa-1", "e", "SNOMED-CT", "2", "Diabetes mellitus type 2 (disorder)"],
        ["2012-01-01", "2013-01-01", "p1aaaaaa-1", "e", "SNOMED-CT", "3", "Acute bronchitis (disorder)"],   # resolved minor
        ["2020-03-03", "2020-03-20", "p1aaaaaa-1", "e", "SNOMED-CT", "4", "Pneumonia (disorder)"],         # resolved acute: kept
        ["2000-01-01", "", "p2bbbbbb-2", "e", "SNOMED-CT", "5", "Chronic congestive heart failure (disorder)"],
        ["2015-01-01", "2015-01-10", "p3cccccc-3", "e", "SNOMED-CT", "6", "Acute bronchitis (disorder)"],
        ["2018-01-01", "", "p4dddddd-4", "e", "SNOMED-CT", "7", "Asthma (disorder)"],
        ["2016-01-01", "", "p1aaaaaa-1", "e", "SNOMED-CT", "8", "History of myocardial infarction (situation)"],  # history: ignored
    ])
    write_csv(tmp_path / "medications.csv", MED, [
        ["2015-01-01", "", "p1aaaaaa-1", "x", "e", "1", "Metformin 500 MG Oral Tablet"],
        ["2015-01-01", "2016-01-01", "p1aaaaaa-1", "x", "e", "2", "Stopped drug 10 MG"],
    ])
    write_csv(tmp_path / "observations.csv", OBS, [
        ["2021-01-01T00:00:00Z", "p1aaaaaa-1", "e", "vital-signs", "1", "Systolic Blood Pressure", "150", "mmHg", "numeric"],
        ["2021-01-01T00:00:00Z", "p1aaaaaa-1", "e", "vital-signs", "2", "Diastolic Blood Pressure", "92", "mmHg", "numeric"],
        ["2021-01-01T00:00:00Z", "p1aaaaaa-1", "e", "vital-signs", "3", "Respiratory rate", "31", "/min", "numeric"],
        ["2019-01-01T00:00:00Z", "p1aaaaaa-1", "e", "vital-signs", "1", "Systolic Blood Pressure", "190", "mmHg", "numeric"],  # older: ignored
        ["2021-01-01T00:00:00Z", "p4dddddd-4", "e", "vital-signs", "4", "Body temperature", "37.0", "Cel", "numeric"],
    ])
    return tmp_path


def test_synthea_maps_conditions_and_skips_deceased_and_irrelevant_patients(tmp_path):
    records, meta = to_records(load_tables(synthea_dir(tmp_path)))
    by_id = {r.patient_id: r for r in records}
    assert set(by_id) == {"synthea_p1aaaaaa", "synthea_p4dddddd"}          # deceased and cold-only patients dropped
    p1 = by_id["synthea_p1aaaaaa"]
    assert p1.name == "Maximina Schiller"                                  # numeric suffixes removed
    assert [c.name for c in p1.conditions] == ["COPD", "Community-acquired pneumonia", "Type 2 diabetes mellitus"]
    assert p1.primary_diagnosis == "COPD" and p1.admission_date == "2010-01-01"
    assert [m.name for m in p1.medications] == ["Metformin 500 MG Oral Tablet"]       # stopped drug excluded
    assert p1.medications[0].dose == "500 MG"
    assert "blood glucose" in p1.monitoring_parameters and "respiratory rate" in p1.monitoring_parameters
    assert {m["patient_id"]: m["uncovered"] for m in meta}["synthea_p4dddddd"] == ["Asthma"]


def test_synthea_question_coverage_flags_conditions_without_templates(tmp_path):
    records, _ = to_records(load_tables(synthea_dir(tmp_path)))
    cov = {r.patient_id: question_coverage(r) for r in records}
    assert cov["synthea_p1aaaaaa"]["condition_specific"] >= 3
    assert cov["synthea_p4dddddd"]["condition_specific"] == 0              # asthma: only generic questions


def test_synthea_vitals_use_the_latest_readings_and_documented_thresholds(tmp_path):
    tables = load_tables(synthea_dir(tmp_path))
    records, meta = to_records(tables)
    cases = {c["id"]: c for c in vitals_cases(tables, records, meta)}
    c1 = cases["synthea_vitals_synthea_p1aaaaaa"]
    answers = {r["answer"] for r in c1["responses"]}
    assert "150/92" in answers and "190/110" not in answers and "31" in answers
    assert c1["expected_action"] == "Escalate"                             # breathing rate 31 is above 30
    assert cases["synthea_vitals_synthea_p4dddddd"]["expected_action"] == "Routine review"   # 37.0 C


def test_synthea_import_refuses_a_folder_that_is_not_a_synthea_export(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        load_tables(tmp_path)


# ── NoteChat ────────────────────────────────────────────────────────────────────────────────────

CONVERSATION = """Doctor: Good morning, how are you?
Patient: Fine thanks.
Doctor: What brings you in today?
Patient: I've had chest pain for two days
and it gets worse when I breathe in.
Doctor: Any falls?
Patient: No falls at all, I have been steady on my feet."""


def notechat_csv(tmp_path):
    path = tmp_path / "nc.csv"
    write_csv(path, ["data", "conversation"], [["note text", CONVERSATION]])
    return path


def test_notechat_turns_join_continuation_lines():
    turns = parse_turns(CONVERSATION)
    assert [s for s, _ in turns] == ["Doctor", "Patient", "Doctor", "Patient", "Doctor", "Patient"]
    assert turns[3][1].endswith("when I breathe in.") and "chest pain" in turns[3][1]


def test_notechat_replies_pair_each_with_the_doctor_question_and_skip_short_ones(tmp_path):
    items = list(replies(notechat_csv(tmp_path)))
    assert [i["reply"][:12] for i in items] == ["I've had che", "No falls at "]    # "Fine thanks." is under 6 words
    assert items[0]["question"] == "What brings you in today?"


def test_notechat_label_sheet_is_blind_and_round_trips_into_eval_cases(tmp_path):
    sheet, out = tmp_path / "sheet.csv", tmp_path / "cases.jsonl"
    write_sheet(notechat_csv(tmp_path), sheet, n=10, seed=1)
    rows = list(csv.DictReader(sheet.open(encoding="utf8")))
    assert set(rows[0]) == {"id", "doctor_question", "patient_reply", "expected_action", "notes"}   # rules output not shown
    assert all(r["expected_action"] == "" for r in rows)
    rows[0]["expected_action"] = "Escalate"                                  # only one row gets labeled
    with sheet.open("w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    labels_to_cases(sheet, out)
    cases = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(cases) == 1 and cases[0]["expected_action"] in ACTIONS and cases[0]["source"] == "notechat"
    assert cases[0]["responses"][0]["answer"] == rows[0]["patient_reply"]
