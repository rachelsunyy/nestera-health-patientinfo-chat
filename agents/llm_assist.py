"""Optional AI assist for clinical summaries, using Anthropic Claude models.

Three tiers, matched to how much reasoning each job needs:

  1. TRIAGE  (small/fast model)  - every check-in. Rates each free-text answer
                                   none / minor / moderate / urgent.
  2. SUMMARY (mid model)         - every check-in. Writes a short, grounded
                                   overview for the clinician.
  3. REVIEW  (deepest model)     - only when the stakes are high: the action is
                                   already Escalate, or AI triage raised the
                                   rule-based action. Second look + rationale.

Safety rules baked in:
  * The deterministic rules in summary_agent.py always run first and set a floor.
    AI results can only RAISE the recommended action or add notes - never lower it.
  * AI output goes to clinicians only. Nothing here is shown to the patient.
  * If AI is disabled, unconfigured, errors out, or refuses, the check-in still
    gets its normal rules-based summary.
  * Minimum necessary data: condition names and the question/answer text are
    sent, scrubbed of identifiers (agents/deid.py). Name, date of birth, contact
    details and patient ID are never included.
  * Enabling requires an explicit AI_DATA_MODE (and, for real patient data, a
    confirmed BAA). Every model call is written to an audit log (agents/ai_audit.py)
    without its content.
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

import config
from agents import ai_audit
from agents.deid import make_scrubber
from agents.vitals import ESCALATE, SCHEDULE

log = logging.getLogger(__name__)

ROUTINE = "Routine review"
_RANK = {ROUTINE: 0, SCHEDULE: 1, ESCALATE: 2}

_TRIAGE_SYSTEM = (
    "You assist a hospital-at-home care team by triaging a patient's daily check-in answers. "
    "For each numbered answer, rate how concerning it is for a patient with the listed conditions: "
    "'none' (reassuring or uninformative), 'minor', 'moderate' (a clinician should arrange a visit or call), "
    "or 'urgent' (needs same-day escalation). Judge only from the text. Respect negation "
    "('no chest pain' is reassuring). Do not give medical advice, diagnose, or address the patient; "
    "write each reason as one short clinical sentence for the care team."
)

_SUMMARY_SYSTEM = (
    "You write a short overview of a hospital-at-home patient's daily check-in for the care team. "
    "Use only facts stated in the answers; never invent readings or symptoms. Mention anything flagged. "
    "Maximum 120 words, plain prose, no headings. Do not give medical advice or diagnose."
)

_REVIEW_SYSTEM = (
    "You are a second reviewer for a hospital-at-home program. A rules engine and a first-pass triage have "
    "produced a recommended action for today's patient check-in. Review the answers and the flags, decide the "
    "action you recommend (Routine review, Schedule visit, or Escalate), and explain your reasoning briefly "
    "for the clinician. List any concern you think the earlier steps missed. Do not give medical advice to the "
    "patient; your audience is the care team, who make the final decision."
)


class AnswerTriage(BaseModel):
    index: int
    concern: Literal["none", "minor", "moderate", "urgent"]
    reason: str


class TriageResult(BaseModel):
    items: list[AnswerTriage]


class ReviewResult(BaseModel):
    recommended_action: Literal["Routine review", "Schedule visit", "Escalate"]
    rationale: str
    missed_concerns: list[str]


@dataclass
class AIOutcome:
    """What the AI tiers contributed to one summary."""
    action: str = ROUTINE
    flags: list[str] = field(default_factory=list)
    overview: str = ""
    review: str = ""
    models: list[str] = field(default_factory=list)


def build_client():
    """Return an Anthropic client for the configured provider, or None if AI assist is off/unconfigured."""
    if not config.AI_ASSIST_ENABLED:
        return None
    if config.AI_DATA_MODE not in ("synthetic", "phi"):
        log.warning("AI assist disabled: set AI_DATA_MODE=synthetic or AI_DATA_MODE=phi")
        return None
    if config.AI_DATA_MODE == "phi" and not config.AI_BAA_CONFIRMED:
        log.warning("AI assist disabled: AI_DATA_MODE=phi requires AI_BAA_CONFIRMED=true (signed BAA on file)")
        return None
    import anthropic

    if config.AI_PROVIDER == "vertex":
        if not config.GCP_PROJECT:
            log.warning("AI_PROVIDER=vertex but GCP_PROJECT is not set; AI assist disabled")
            return None
        return anthropic.AnthropicVertex(project_id=config.GCP_PROJECT, region=config.GCP_REGION)
    try:
        return anthropic.Anthropic(timeout=60.0, max_retries=2)  # reads ANTHROPIC_API_KEY
    except Exception:
        log.warning("Anthropic client could not be created; AI assist disabled", exc_info=True)
        return None


def _identity(text: str) -> str:
    return text


def _qa_block(responses: list, scrub=_identity) -> str:
    return "\n".join(
        f"{i}. Q: {scrub(r.question)}\n   A: {scrub(r.answer)}" for i, r in enumerate(responses, 1)
    )


def _flag_block(flags: list[str], scrub=_identity) -> str:
    return "\n".join(f"- {scrub(f)}" for f in flags) or "None"


def _text(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text").strip()


class AIAssist:
    def __init__(self, client=None) -> None:
        self.client = client if client is not None else build_client()
        self._scrub = _identity     # set per check-in by assist()
        self._patient = ""

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def _call(self, tier: str, model: str, request):
        """Run one model call, recording an audit entry (never the content)."""
        start = time.monotonic()
        try:
            response = request()
        except Exception as e:
            ai_audit.record(tier=tier, model=model, outcome="error", patient=self._patient,
                            latency_ms=int((time.monotonic() - start) * 1000), error=type(e).__name__)
            raise
        refused = getattr(response, "stop_reason", None) == "refusal"
        ai_audit.record(tier=tier, model=model, outcome="refused" if refused else "ok", patient=self._patient,
                        latency_ms=int((time.monotonic() - start) * 1000),
                        usage=getattr(response, "usage", None), stop_reason=getattr(response, "stop_reason", None))
        return response

    # ── Tier 1: triage ────────────────────────────────────────────────────
    def triage(self, conditions: list[str], responses: list) -> list[AnswerTriage]:
        response = self._call("triage", config.AI_MODEL_TRIAGE, lambda: self.client.messages.parse(
            model=config.AI_MODEL_TRIAGE,
            max_tokens=4096,
            output_config={"effort": "low"},
            system=_TRIAGE_SYSTEM,
            messages=[{"role": "user", "content": (
                f"Conditions: {', '.join(conditions) or 'not documented'}\n\n"
                f"Check-in answers:\n{_qa_block(responses, self._scrub)}"
            )}],
            output_format=TriageResult,
        ))
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"triage returned no result (stop_reason={response.stop_reason})")
        return [t for t in response.parsed_output.items if 1 <= t.index <= len(responses)]

    # ── Tier 2: overview ──────────────────────────────────────────────────
    def overview(self, conditions: list[str], responses: list, flags: list[str]) -> str:
        response = self._call("overview", config.AI_MODEL_SUMMARY, lambda: self.client.messages.create(
            model=config.AI_MODEL_SUMMARY,
            max_tokens=4096,
            output_config={"effort": "medium"},
            system=_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": (
                f"Conditions: {', '.join(conditions) or 'not documented'}\n\n"
                f"Check-in answers:\n{_qa_block(responses, self._scrub)}\n\n"
                f"Flags already raised:\n{_flag_block(flags, self._scrub)}"
            )}],
        ))
        if response.stop_reason == "refusal":
            raise RuntimeError("overview was refused")
        return _text(response)

    # ── Tier 3: second review ─────────────────────────────────────────────
    def review(self, conditions: list[str], responses: list, flags: list[str], action: str) -> ReviewResult:
        response = self._call("review", config.AI_MODEL_REVIEW, lambda: self.client.messages.parse(
            model=config.AI_MODEL_REVIEW,
            max_tokens=8000,
            output_config={"effort": "high"},
            system=_REVIEW_SYSTEM,
            messages=[{"role": "user", "content": (
                f"Conditions: {', '.join(conditions) or 'not documented'}\n\n"
                f"Check-in answers:\n{_qa_block(responses, self._scrub)}\n\n"
                f"Flags raised so far:\n{_flag_block(flags, self._scrub)}\n\n"
                f"Current recommended action: {action}"
            )}],
            output_format=ReviewResult,
        ))
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"review returned no result (stop_reason={response.stop_reason})")
        return response.parsed_output

    # ── Orchestration ─────────────────────────────────────────────────────
    def assist(self, conditions: list[str], responses: list, rule_flags: list[str], rule_action: str,
               patient_id: str = "", known_names: tuple[str, ...] = (),
               with_overview: bool = True) -> AIOutcome:
        """Run the tiers on top of the rules result. Each tier fails independently and safely.

        `known_names` (e.g. the patient's name) are removed from everything sent to the model.
        """
        out = AIOutcome(action=rule_action)
        if not self.enabled:
            return out

        self._scrub = make_scrubber(known_names)
        self._patient = ai_audit.patient_ref(patient_id) if patient_id else ""
        all_flags = list(rule_flags)

        try:
            for t in self.triage(conditions, responses):
                if t.concern not in ("moderate", "urgent"):
                    continue
                severity = ESCALATE if t.concern == "urgent" else SCHEDULE
                r = responses[t.index - 1]
                if not any(r.answer in f for f in rule_flags):  # skip answers the rules already flagged
                    msg = f'AI triage ({t.concern}): {t.reason} — patient said "{r.answer}"'
                    out.flags.append(msg)
                    all_flags.append(msg)
                if _RANK[severity] > _RANK[out.action]:
                    out.action = severity
            out.models.append(config.AI_MODEL_TRIAGE)
        except Exception:
            log.warning("AI triage failed; continuing with rules only", exc_info=True)

        raised = _RANK[out.action] > _RANK[rule_action]
        if out.action == ESCALATE or raised:
            try:
                rv = self.review(conditions, responses, all_flags, out.action)
                if _RANK[rv.recommended_action] > _RANK[out.action]:
                    out.action = rv.recommended_action
                parts = [rv.rationale] + [f"Possible missed concern: {c}" for c in rv.missed_concerns]
                out.review = "\n\n".join(parts)
                out.models.append(config.AI_MODEL_REVIEW)
            except Exception:
                log.warning("AI review failed; continuing without it", exc_info=True)

        if with_overview:
            try:
                out.overview = self.overview(conditions, responses, all_flags)
                out.models.append(config.AI_MODEL_SUMMARY)
            except Exception:
                log.warning("AI overview failed; continuing without it", exc_info=True)

        self._scrub, self._patient = _identity, ""
        return out
