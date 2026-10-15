"""Conversational version of the patient check-in.

Same interface as PatientAgent (start_session / respond / progress), so the app can
swap one for the other. What stays fixed, in plain code the model cannot influence:

  * the list of questions, their order, and when the check-in is complete
  * the recorded answers: always the patient's own words, never a model paraphrase
  * every emergency and medical-advice response: fixed text, never written by the model

What the model adds (agents/llm_assist.py, one low-reasoning call per reply):

  * understands the reply: answered / unclear / a question for the care team /
    possible emergency / declined
  * writes a short, warm acknowledgment
  * asks at most ONE clarifying question when an answer is too vague to use
  * notices a concerning symptom mentioned out of order and records it

Anything the model writes for the patient is checked before it is shown (length, no
advice or reassurance wording, no invented numbers). If a check fails, or the model
errors, refuses or is unavailable, the turn falls back to the scripted behaviour of
PatientAgent, so a check-in never gets stuck.

Emergencies: if the reply matches the emergency rules (the same ones used for triage)
or the model flags one, the patient is shown a fixed message telling them to contact
their care team and call 911 if in danger. The check-in then ends and is saved with an
emergency marker, which the summary always escalates.
"""

from __future__ import annotations
import logging
import random
import re

from agents.llm_assist import AIAssist, TurnAnalysis
from agents.markers import EMERGENCY_MARKER, VOLUNTEERED_MARKER
from agents.patient_agent import PatientAgent, _ACK_PHRASES
from agents.summary_agent import _detect_flags
from data.models import CheckInResponse
from guardrails.safety import contains_medical_advice

log = logging.getLogger(__name__)

_MAX_ACK_WORDS = 25
_MAX_CLARIFY_WORDS = 30
_REASSURANCE = (
    "normal", "nothing to worry", "don't worry", "do not worry", "not a concern", "sounds fine",
    "good news", "you're fine", "you are fine", "nothing serious", "no need to", "perfectly",
)

# Directive or advice-like wording the model must not use with a patient (broader than guardrails/safety.py)
_DIRECTIVE = re.compile(
    r"\b(?:you|u)\s+(?:should|must|need to|ought to|have to|had better|could try|might want to)\b"
    r"|\b(?:make sure|be sure|try to|try taking|avoid|remember to|don't forget|stop|start|increase|decrease|"
    r"rest|drink|eat|take your|call (?:911|your doctor)|go to)\b",
    re.I,
)


def _gives_advice(text: str) -> bool:
    return contains_medical_advice(text) or bool(_DIRECTIVE.search(text))


DISCLOSURE = (
    "I'm an automated assistant, not a person and not a medical professional. "
    "I can't give medical advice, but I will pass everything you tell me to your care team."
)

CLARIFY_FALLBACK = "Could you tell me a little more about that?"


def emergency_message(contact: str) -> str:
    return (
        "Thank you for telling me. Based on what you've shared, please contact your care team right away "
        f"at {contact}. If you feel in danger or this is an emergency, call 911 now. "
        "I've noted this for your care team and will end the check-in here so you can get help."
    )


def deflection_message(contact: str) -> str:
    return (
        "That's a good question for your care team. I can't give medical advice, "
        f"but you can reach them at {contact}. Let's keep going with the check-in."
    )


def _words(text: str) -> int:
    return len(text.split())


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def safe_acknowledgment(ack: str, reply: str) -> str:
    """Return the model's acknowledgment if it passes the checks, else a scripted one."""
    ack = (ack or "").strip()
    lower = ack.lower()
    ok = (
        ack
        and _words(ack) <= _MAX_ACK_WORDS
        and not _gives_advice(ack)
        and not any(p in lower for p in _REASSURANCE)
        and _numbers(ack) <= _numbers(reply)          # no numbers the patient did not say
        and "?" not in ack                            # questions come only from the fixed list
    )
    return ack if ok else random.choice(_ACK_PHRASES)


def safe_clarifying_question(question: str, reply: str) -> str:
    q = (question or "").strip()
    ok = (
        q.endswith("?")
        and _words(q) <= _MAX_CLARIFY_WORDS
        and q.count("?") == 1
        and not _gives_advice(q)
        and not any(p in q.lower() for p in _REASSURANCE)
        and _numbers(q) <= _numbers(reply)
    )
    return q if ok else CLARIFY_FALLBACK


class ConversationalPatientAgent(PatientAgent):
    def __init__(self, patient_id, db, ai: AIAssist | None = None) -> None:
        super().__init__(patient_id, db)
        self.ai = ai if ai is not None else AIAssist()
        self._clarified = False          # already asked a clarifying question for the current question
        self._deflected = False          # already redirected a medical question for the current question
        self._first_reply = ""           # the patient's reply before the clarifying question
        self.ended_early = False

    # ── session ───────────────────────────────────────────────────────────
    def start_session(self) -> str:
        opening = super().start_session()
        if self.ai.enabled:
            head, _, rest = opening.partition("\n\n")
            return f"{head} {DISCLOSURE}\n\n{rest}"
        return opening

    def respond(self, patient_input: str) -> tuple[str, bool]:
        if not self.ai.enabled:
            return super().respond(patient_input)

        question = self.questions[self._current_q_index]
        contact = self.record.care_team_contact

        # Emergency rules run first and never depend on the model.
        if self._rules_say_emergency(question, patient_input):
            return self._end_for_emergency(question, patient_input, contact)

        try:
            turn = self.ai.analyze_turn(
                [c.name for c in self.record.conditions] or [self.record.primary_diagnosis],
                question, patient_input,
                patient_id=self.patient_id, known_names=(self.record.name,),
                prior_reply=self._first_reply if self._clarified else "",
            )
        except Exception:
            log.warning("Conversation analysis failed; using the scripted flow for this turn", exc_info=True)
            return self._record_and_advance(patient_input, ack=None)

        if turn.intent == "emergency":
            return self._end_for_emergency(question, patient_input, contact)

        if turn.intent == "patient_question" and not self._deflected:
            self._deflected = True
            return f"{deflection_message(contact)}\n\n{question}", False

        if turn.intent == "unclear" and not self._clarified:
            self._clarified = True
            self._first_reply = patient_input
            return safe_clarifying_question(turn.clarifying_question, patient_input), False

        self._record_volunteered(turn, patient_input)
        return self._record_and_advance(patient_input, ack=safe_acknowledgment(turn.acknowledgment, patient_input))

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _rules_say_emergency(question: str, reply: str) -> bool:
        return _detect_flags([CheckInResponse(question=question, answer=reply)])[1] == "Escalate"

    def _end_for_emergency(self, question: str, reply: str, contact: str) -> tuple[str, bool]:
        self.responses.append(CheckInResponse(question=EMERGENCY_MARKER, answer=reply))
        self._save_checkin()
        self.ended_early = True
        return emergency_message(contact), True

    def _record_volunteered(self, turn: TurnAnalysis, reply: str) -> None:
        excerpt = (turn.volunteered_concern or "").strip()
        # Only keep text that really is in the patient's message (no model rewording).
        if excerpt and excerpt.lower() in reply.lower():
            self.responses.append(CheckInResponse(question=VOLUNTEERED_MARKER, answer=excerpt))

    def _record_and_advance(self, reply: str, ack: str | None) -> tuple[str, bool]:
        question = self.questions[self._current_q_index]
        answer = f"{self._first_reply} | {reply}" if self._clarified and self._first_reply else reply
        self._clarified = self._deflected = False
        self._first_reply = ""
        self.responses.append(CheckInResponse(question=question, answer=answer))
        self._current_q_index += 1

        if self._current_q_index >= len(self.questions):
            self._save_checkin()
            return (
                "Thank you so much for completing today's check-in! "
                "Your responses have been saved and your care team will review them. "
                f"For urgent concerns please call {self.record.care_team_contact}. Take care!",
                True,
            )
        return f"{ack or random.choice(_ACK_PHRASES)}\n\n{self.questions[self._current_q_index]}", False
