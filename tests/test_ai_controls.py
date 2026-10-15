"""Data-handling controls around the AI tiers: enable guard, scrubbing in requests, audit log."""

import json
from types import SimpleNamespace

import pytest

import config
from agents import ai_audit
from agents.llm_assist import AIAssist, TriageResult, build_client
from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent
from tests.test_llm_assist import fake_client, finished_checkin


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(config, "AI_ASSIST_ENABLED", True)
    monkeypatch.setattr(config, "AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_enabling_requires_an_explicit_data_mode(enabled, monkeypatch):
    monkeypatch.setattr(config, "AI_DATA_MODE", "")
    assert build_client() is None


def test_synthetic_mode_creates_a_client(enabled, monkeypatch):
    monkeypatch.setattr(config, "AI_DATA_MODE", "synthetic")
    assert build_client() is not None


def test_phi_mode_requires_a_confirmed_baa(enabled, monkeypatch):
    monkeypatch.setattr(config, "AI_DATA_MODE", "phi")
    monkeypatch.setattr(config, "AI_BAA_CONFIRMED", False)
    assert build_client() is None
    monkeypatch.setattr(config, "AI_BAA_CONFIRMED", True)
    assert build_client() is not None


def test_requests_are_scrubbed_of_identifiers(db):
    client = fake_client(triage=TriageResult(items=[]))
    agent = PatientAgent("patient_001", db)
    agent.start_session()
    agent.respond("Margaret here. Call me on (312) 555-0123, I live at 55 Oak Street")
    done = False
    while not done:
        _, done = agent.respond("Fine")
    SummaryAgent("patient_001", db, AIAssist(client)).generate()
    sent = " ".join(str(kw) for _, kw in client.messages.calls)
    for leaked in ("Margaret", "555-0123", "Oak Street"):
        assert leaked not in sent
    assert "[PHONE]" in sent and "[ADDRESS]" in sent


def test_scrubbed_text_is_sent_but_original_stays_in_the_stored_note(db):
    client = fake_client(triage=TriageResult(items=[]))
    finished_checkin(db, first_answer="I fell, call (312) 555-0123")
    summary = SummaryAgent("patient_001", db, AIAssist(client)).generate()
    assert "(312) 555-0123" in summary.summary_markdown            # clinicians still see the real answer


def read_audit():
    path = ai_audit.audit_path()
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_every_call_is_audited_without_content(db):
    client = fake_client(triage=TriageResult(items=[]))
    client.messages.parse  # noqa: B018 - make sure the fake is wired
    finished_checkin(db, first_answer="distinctive-secret-answer")
    SummaryAgent("patient_001", db, AIAssist(client)).generate()
    entries = read_audit()
    assert [e["tier"] for e in entries] == ["triage", "overview"]
    for e in entries:
        assert e["outcome"] == "ok" and e["model"] and e["latency_ms"] >= 0
        assert e["patient_ref"] and "patient_001" not in json.dumps(e)
    raw = ai_audit.audit_path().read_text()
    assert "distinctive-secret-answer" not in raw


def test_failures_and_refusals_are_audited(db):
    client = fake_client(triage=TriageResult(items=[]), fail=("overview",), refuse=("triage",))
    finished_checkin(db)
    SummaryAgent("patient_001", db, AIAssist(client)).generate()
    outcomes = {e["tier"]: e["outcome"] for e in read_audit()}
    assert outcomes == {"triage": "refused", "overview": "error"}


def test_audit_never_breaks_a_checkin(db, monkeypatch):
    monkeypatch.setattr(ai_audit, "audit_path", lambda: db_unwritable())
    client = fake_client(triage=TriageResult(items=[]))
    finished_checkin(db)
    summary = SummaryAgent("patient_001", db, AIAssist(client)).generate()
    assert summary.recommended_action == "Routine review"


def db_unwritable():
    from pathlib import Path
    return Path("/nonexistent-dir/ai_audit.jsonl")
