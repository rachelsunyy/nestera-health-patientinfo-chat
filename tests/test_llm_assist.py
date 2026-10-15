"""AI assist tiers, using a fake Anthropic client (no network, no API key needed)."""

from types import SimpleNamespace

import pytest

import config
from agents.llm_assist import AIAssist, AnswerTriage, ReviewResult, TriageResult
from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent


class FakeMessages:
    def __init__(self, triage=None, review=None, overview="Stable overview.", fail=(), refuse=()):
        self.calls = []
        self.triage, self.review, self.overview = triage, review, overview
        self.fail, self.refuse = set(fail), set(refuse)

    def _tier(self, model):
        return {config.AI_MODEL_TRIAGE: "triage", config.AI_MODEL_REVIEW: "review",
                config.AI_MODEL_SUMMARY: "overview"}[model]

    def parse(self, **kw):
        tier = self._tier(kw["model"])
        self.calls.append((tier, kw))
        if tier in self.fail:
            raise RuntimeError("boom")
        if tier in self.refuse:
            return SimpleNamespace(stop_reason="refusal", parsed_output=None)
        out = self.triage if tier == "triage" else self.review
        return SimpleNamespace(stop_reason="end_turn", parsed_output=out)

    def create(self, **kw):
        tier = self._tier(kw["model"])
        self.calls.append((tier, kw))
        if tier in self.fail:
            raise RuntimeError("boom")
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text=self.overview)])


def fake_client(**kw):
    return SimpleNamespace(messages=FakeMessages(**kw))


def tiers(client):
    return [t for t, _ in client.messages.calls]


def finished_checkin(db, pid="patient_001", first_answer="Fine"):
    agent = PatientAgent(pid, db)
    agent.start_session()
    agent.respond(first_answer)
    done = False
    while not done:
        _, done = agent.respond("Fine")
    return agent


def test_disabled_by_default_makes_no_calls(db, monkeypatch):
    monkeypatch.setattr(config, "AI_ASSIST_ENABLED", False)
    assert AIAssist().enabled is False
    finished_checkin(db)
    summary = SummaryAgent("patient_001", db).generate()
    assert summary.ai_models == []
    assert "AI-assisted" not in summary.summary_markdown


def test_routine_checkin_uses_only_cheap_and_mid_tiers(db):
    client = fake_client(triage=TriageResult(items=[]))
    finished_checkin(db)
    summary = SummaryAgent("patient_001", db, AIAssist(client)).generate()
    assert tiers(client) == ["triage", "overview"]          # no expensive review for a quiet check-in
    assert summary.ai_models == [config.AI_MODEL_TRIAGE, config.AI_MODEL_SUMMARY]
    assert "### AI-assisted overview" in summary.summary_markdown
    assert summary.recommended_action == "Routine review"


def test_models_and_effort_are_stratified(db):
    client = fake_client(
        triage=TriageResult(items=[AnswerTriage(index=1, concern="urgent", reason="Severe symptom")]),
        review=ReviewResult(recommended_action="Escalate", rationale="Agree.", missed_concerns=[]),
    )
    finished_checkin(db)
    SummaryAgent("patient_001", db, AIAssist(client)).generate()
    by_tier = {t: kw for t, kw in client.messages.calls}
    assert by_tier["triage"]["model"] == "claude-haiku-5-5" and by_tier["triage"]["output_config"] == {"effort": "low"}
    assert by_tier["overview"]["model"] == "claude-sonnet-5-5" and by_tier["overview"]["output_config"] == {"effort": "medium"}
    assert by_tier["review"]["model"] == "claude-opus-5-5" and by_tier["review"]["output_config"] == {"effort": "high"}


def test_ai_can_raise_the_action(db):
    client = fake_client(
        triage=TriageResult(items=[AnswerTriage(index=1, concern="urgent", reason="Possible stroke symptoms")]),
        review=ReviewResult(recommended_action="Escalate", rationale="Reasonable to escalate.", missed_concerns=["Speech change"]),
    )
    finished_checkin(db, first_answer="my words feel slurred and my face droops")
    summary = SummaryAgent("patient_001", db, AIAssist(client)).generate()
    assert summary.recommended_action == "Escalate"
    assert "review" in tiers(client)
    assert any(f.startswith("AI triage (urgent)") for f in summary.flagged_items)
    assert "### AI second review" in summary.summary_markdown
    assert "Possible missed concern: Speech change" in summary.summary_markdown


def test_ai_can_never_lower_the_action(db):
    client = fake_client(
        triage=TriageResult(items=[AnswerTriage(index=1, concern="none", reason="Reassuring")]),
        review=ReviewResult(recommended_action="Routine review", rationale="Looks fine.", missed_concerns=[]),
    )
    finished_checkin(db, first_answer="I have chest pain")          # rules say Escalate
    summary = SummaryAgent("patient_001", db, AIAssist(client)).generate()
    assert summary.recommended_action == "Escalate"


@pytest.mark.parametrize("failing", [("triage",), ("overview",), ("triage", "overview", "review")])
def test_ai_failures_never_break_the_summary(db, failing):
    client = fake_client(triage=TriageResult(items=[]), fail=failing)
    finished_checkin(db, first_answer="I fell yesterday")
    summary = SummaryAgent("patient_001", db, AIAssist(client)).generate()
    assert summary.recommended_action == "Schedule visit"           # rules result survives
    for tier in failing:
        model = {"triage": config.AI_MODEL_TRIAGE, "overview": config.AI_MODEL_SUMMARY,
                 "review": config.AI_MODEL_REVIEW}[tier]
        assert model not in summary.ai_models


def test_refusal_is_handled_like_a_failure(db):
    client = fake_client(refuse=("triage",))
    finished_checkin(db)
    summary = SummaryAgent("patient_001", db, AIAssist(client)).generate()
    assert config.AI_MODEL_TRIAGE not in summary.ai_models
    assert summary.recommended_action == "Routine review"


def test_no_direct_identifiers_are_sent(db):
    client = fake_client(triage=TriageResult(items=[]))
    finished_checkin(db)
    SummaryAgent("patient_001", db, AIAssist(client)).generate()
    record = db.get_patient("patient_001")
    sent = " ".join(str(kw) for _, kw in client.messages.calls)
    for identifier in (record.name, record.date_of_birth, record.patient_id, record.care_team_contact):
        assert identifier not in sent
    assert record.conditions[0].name in sent                       # clinical context is sent


def test_out_of_range_triage_index_is_ignored(db):
    client = fake_client(triage=TriageResult(items=[AnswerTriage(index=99, concern="urgent", reason="bogus")]))
    finished_checkin(db)
    summary = SummaryAgent("patient_001", db, AIAssist(client)).generate()
    assert summary.recommended_action == "Routine review"
