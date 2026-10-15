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
