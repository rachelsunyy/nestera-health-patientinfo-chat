"""The evaluation dataset and runner."""

from evals.run_eval import ACTIONS, RANK, load_cases, predict, summarize
from agents.llm_assist import AIAssist, AnswerTriage, ReviewResult, TriageResult
from tests.test_llm_assist import fake_client


def test_dataset_is_well_formed():
    cases = load_cases()
    assert len(cases) >= 30
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["expected_action"] in ACTIONS
        assert c["responses"] and all(r["question"] and r["answer"] for r in c["responses"])
    assert {c["expected_action"] for c in cases} == set(ACTIONS)   # all three labels are represented


def test_summary_counts_under_and_over_triage():
    cases = [{"id": "a", "expected_action": "Escalate"}, {"id": "b", "expected_action": "Routine review"},
             {"id": "c", "expected_action": "Schedule visit"}]
    s = summarize(cases, ["Routine review", "Schedule visit", "Schedule visit"])
    assert [u[0] for u in s["under"]] == ["a"] and [o[0] for o in s["over"]] == ["b"]
    assert s["accuracy"] == 1 / 3


def test_ai_can_fix_a_case_the_rules_miss():
    case = next(c for c in load_cases() if c["id"] == "cant_catch_breath")
    rules, final = predict(case, None)
    assert RANK[rules] < RANK[case["expected_action"]]
    client = fake_client(
        triage=TriageResult(items=[AnswerTriage(index=1, concern="urgent", reason="Severe dyspnea at rest")]),
        review=ReviewResult(recommended_action="Escalate", rationale="Agree", missed_concerns=[]),
    )
    _, final = predict(case, AIAssist(client))
    assert final == "Escalate"
    assert "overview" not in [t for t, _ in client.messages.calls]   # evals skip the text-only tier


def test_conversation_dataset_is_well_formed():
    import json
    from pathlib import Path
    path = Path(__file__).parent.parent / "evals" / "conversation_cases.jsonl"
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    intents = {"answer", "unclear", "patient_question", "emergency", "decline"}
    assert len(cases) >= 30 and {c["expected_intent"] for c in cases} == intents
    assert all(c["question"] and c["reply"] and c["conditions"] for c in cases)


# ── the larger evaluation set (evals/dataset_v2.jsonl) ───────────────────────────────────────────

V2 = "dataset_v2.jsonl"


def _v2():
    from pathlib import Path
    return load_cases(Path(__file__).parent.parent / "evals" / V2)


def test_large_dataset_is_well_formed():
    cases = _v2()
    assert len(cases) >= 300
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["expected_action"] in ACTIONS and c["category"] and c["source"] in ("original", "template", "authored")
        assert c["split"] in ("dev", "test")
        assert c["responses"] and all(r["question"] and r["answer"] for r in c["responses"])
    assert {c["expected_action"] for c in cases} == set(ACTIONS)
    assert {c["split"] for c in cases} == {"dev", "test"}


def test_large_dataset_keeps_the_original_cases_unchanged():
    original = {c["id"]: c for c in load_cases()}
    v2 = {c["id"]: c for c in _v2()}
    for cid, c in original.items():
        assert {k: v2[cid][k] for k in c} == c


def test_large_dataset_matches_its_generator():
    """The committed file must be exactly what build_dataset.py produces (no hand edits, no drift)."""
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))
    import build_dataset
    assert build_dataset.build_cases() == _v2()


def test_every_non_routine_authored_case_contains_its_target_answer():
    """Guards against cases whose target answer was silently dropped (the check-in would be all benign)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))
    import case_bank
    authored = {a for pool in (case_bank.INFORMAL_ESCALATE, case_bank.INFORMAL_SCHEDULE) for _, a, _, _ in pool}
    answers = {r["answer"] for c in _v2() for r in c["responses"]}
    assert authored <= answers


def test_numeric_and_routine_categories_agree_with_the_rules():
    """Labels for these categories come from a separate copy of the documented thresholds."""
    by_cat = {}
    for c in _v2():
        if c["category"].startswith("numeric_") and c["category"] != "numeric_glucose_mmol" or c["category"] == "routine":
            by_cat.setdefault(c["category"], []).append(c)
    assert by_cat
    for cat, cases in by_cat.items():
        for c in cases:
            assert predict(c, None)[0] == c["expected_action"], (c["id"], c["note"])


def test_report_by_category_counts_under_and_over():
    from evals.run_eval import render_by_category
    cases = [{"id": "a", "category": "x", "expected_action": "Escalate"},
             {"id": "b", "category": "x", "expected_action": "Routine review"}]
    table = render_by_category(cases, ["Routine review", "Schedule visit"])
    assert "| x | 2 | 0% | 1 | 1 |" in table
