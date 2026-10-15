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
    sent. Name, date of birth, contact details and patient ID are not.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

import config
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


def _qa_block(responses: list) -> str:
    return "\n".join(f"{i}. Q: {r.question}\n   A: {r.answer}" for i, r in enumerate(responses, 1))


def _text(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text").strip()


class AIAssist:
    def __init__(self, client=None) -> None:
        self.client = client if client is not None else build_client()

    @property
    def enabled(self) -> bool:
        return self.client is not None

    # ── Tier 1: triage ────────────────────────────────────────────────────
    def triage(self, conditions: list[str], responses: list) -> list[AnswerTriage]:
        response = self.client.messages.parse(
            model=config.AI_MODEL_TRIAGE,
            max_tokens=4096,
            output_config={"effort": "low"},
            system=_TRIAGE_SYSTEM,
            messages=[{"role": "user", "content": (
                f"Conditions: {', '.join(conditions) or 'not documented'}\n\n"
                f"Check-in answers:\n{_qa_block(responses)}"
            )}],
            output_format=TriageResult,
        )
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"triage returned no result (stop_reason={response.stop_reason})")
        return [t for t in response.parsed_output.items if 1 <= t.index <= len(responses)]

    # ── Tier 2: overview ──────────────────────────────────────────────────
    def overview(self, conditions: list[str], responses: list, flags: list[str]) -> str:
        flag_text = "\n".join(f"- {f}" for f in flags) or "None"
        response = self.client.messages.create(
            model=config.AI_MODEL_SUMMARY,
            max_tokens=4096,
            output_config={"effort": "medium"},
            system=_SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": (
                f"Conditions: {', '.join(conditions) or 'not documented'}\n\n"
                f"Check-in answers:\n{_qa_block(responses)}\n\nFlags already raised:\n{flag_text}"
            )}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("overview was refused")
        return _text(response)

    # ── Tier 3: second review ─────────────────────────────────────────────
    def review(self, conditions: list[str], responses: list, flags: list[str], action: str) -> ReviewResult:
        flag_text = "\n".join(f"- {f}" for f in flags) or "None"
        response = self.client.messages.parse(
            model=config.AI_MODEL_REVIEW,
            max_tokens=8000,
            output_config={"effort": "high"},
            system=_REVIEW_SYSTEM,
            messages=[{"role": "user", "content": (
                f"Conditions: {', '.join(conditions) or 'not documented'}\n\n"
                f"Check-in answers:\n{_qa_block(responses)}\n\n"
                f"Flags raised so far:\n{flag_text}\n\nCurrent recommended action: {action}"
            )}],
            output_format=ReviewResult,
        )
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"review returned no result (stop_reason={response.stop_reason})")
        return response.parsed_output

    # ── Orchestration ─────────────────────────────────────────────────────
    def assist(self, conditions: list[str], responses: list, rule_flags: list[str], rule_action: str) -> AIOutcome:
        """Run the tiers on top of the rules result. Each tier fails independently and safely."""
        out = AIOutcome(action=rule_action)
        if not self.enabled:
            return out

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

        try:
            out.overview = self.overview(conditions, responses, all_flags)
            out.models.append(config.AI_MODEL_SUMMARY)
        except Exception:
            log.warning("AI overview failed; continuing without it", exc_info=True)

        return out
