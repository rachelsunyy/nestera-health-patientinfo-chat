"""Conversational, adaptive version of the patient check-in.

Same interface as PatientAgent (start_session / respond / progress), so the app can swap
one for the other.

THE IDEA. Each patient has a coverage checklist: the topics a clinician needs answered
(built from their record by PatientAgent: conditions, readings, medications, safety, and
any questions the doctor added). The checklist is fixed. Everything about HOW the
conversation gets through it adapts to the patient, using one model call per reply:

  * ORDER     the model picks which remaining topic to raise next (e.g. the oxygen
              reading right after the patient mentions trouble breathing)
  * WORDING   it phrases the next question to flow from what the patient just said
  * FOLLOW-UPS it asks short, neutral follow-up questions when an answer reveals
              something worth a closer look (a symptom getting worse, something new,
              an incomplete answer). Capped, so a conversation can't run on
  * SKIPPING  a topic the patient has already answered is not asked again, but only if
              the model quotes their exact words and the code verifies the quote
  * CLARITY   one clarifying question when an answer is too vague to use; medical
              questions are redirected to the care team

WHAT THE MODEL CAN NEVER CHANGE (plain code):

  * a check-in only ends when every checklist topic is covered (or an emergency ends it)
  * recorded answers are always the patient's own words, never a model paraphrase;
    each Q/A is tagged with its topic so numeric checks (SpO2, BP...) still apply to
    reworded questions. Doctor-written questions are always asked verbatim
  * every emergency and medical-advice response is fixed text
  * hard caps on follow-ups, so the conversation always finishes

Everything the model writes for the patient (acknowledgments, questions) is checked
before it is shown: length, one question only, on the topic, no advice or reassurance
wording, no numbers the patient didn't say. If a check fails, or the model errors,
refuses or is unavailable, that turn uses the standard question and a scripted
acknowledgment, so a check-in never gets stuck.

Emergencies: if the reply matches the emergency rules (the same ones used for triage)
or the model flags one, the patient sees a fixed message telling them to contact their
care team and call 911 if in danger. The check-in then ends and is saved with an
emergency marker, which the summary always escalates.
"""

from __future__ import annotations
import logging
import random
import re
from dataclasses import dataclass
from datetime import date

from agents.llm_assist import AIAssist, TurnAnalysis
from agents.markers import EMERGENCY_MARKER, VOLUNTEERED_MARKER
from agents.patient_agent import PatientAgent, _ACK_PHRASES
from agents.summary_agent import _detect_flags
from data.models import CheckInResponse
from guardrails.safety import contains_medical_advice

log = logging.getLogger(__name__)

MAX_FOLLOWUPS_TOTAL = 6          # follow-up questions across the whole check-in
MAX_FOLLOWUPS_PER_TOPIC = 2      # and per checklist topic
_MAX_ACK_WORDS = 25
_MAX_QUESTION_WORDS = 30

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

DISCLOSURE = (
    "I'm an automated assistant, not a person and not a medical professional. "
    "I can't give medical advice, but I will pass everything you tell me to your care team."
)

CLARIFY_FALLBACK = "Could you tell me a little more about that?"


# ── Checklist topics ──────────────────────────────────────────────────────

@dataclass
class Topic:
    id: str                 # unique within one check-in (what the model refers to)
    kind: str               # base topic, e.g. "spo2"; stored with the answer
    canonical: str          # the standard question
    keywords: tuple[str, ...]
    numeric: bool           # a reading: skipping it needs a number as evidence
    verbatim: bool = False  # doctor-written: always asked exactly as written


# (kind, phrases found in the standard question, words a reworded question must keep, is a reading)
_KINDS: list[tuple[str, tuple[str, ...], tuple[str, ...], bool]] = [
    ("resp_rate", ("breathing rate", "respiratory rate"), ("breath",), True),
    ("spo2", ("oxygen", "spo2"), ("oxygen", "spo2", "saturation", "pulse ox"), True),
    ("temperature", ("your temperature",), ("temperature", "thermometer"), True),
    ("blood_pressure", ("blood pressure",), ("blood pressure", "bp"), True),
    ("low_sugar_symptoms", ("shakiness", "dizziness"), ("shak", "sweat", "dizz", "sugar"), False),
    ("blood_sugar_reading", ("check your blood sugar", "glucose"), ("blood sugar", "glucose", "sugar"), True),
    ("fever_chills", ("fever or chills",), ("fever", "chill"), False),
    ("cough", ("cough",), ("cough",), False),
    ("breathing", ("your breathing", "short of breath"), ("breath",), False),
    ("weight", ("weighed", "weigh yourself"), ("weigh",), True),
    ("swelling", ("swelling",), ("swell",), False),
    ("neuro", ("weakness, numbness",), ("weak", "numb", "speak", "speech"), False),
    ("fluids", ("fluid",), ("fluid", "drink"), False),
    ("rescue_inhaler", ("rescue inhaler",), ("inhaler",), False),
    ("medications", ("medications",), ("medic", "pill", "dose", "tablet"), False),
    ("wellbeing", ("well-being",), ("well", "feel", "scale", "1 to 10", "better", "worse"), False),
    ("safety", ("falls",), ("fall", "safe", "concern", "home"), False),
    ("anything_else", ("anything else",), ("anything", "else"), False),
]


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    for w in words:
        if (re.search(rf"\b{re.escape(w)}\b", text) if len(w) <= 3 else w in text):
            return True
    return False


def build_topics(questions: list[str], doctor_questions: list[str]) -> list[Topic]:
    """Turn the standard question list into the coverage checklist."""
    topics: list[Topic] = []
    used: set[str] = set()
    for i, q in enumerate(questions, 1):
        lower = q.lower()
        if q in doctor_questions:
            kind, keywords, numeric, verbatim = "doctor", (), False, True
        else:
            kind, keywords, numeric, verbatim = "other", (), False, True   # unknown wording: ask as written
            for k, phrases, kws, is_numeric in _KINDS:
                if any(p in lower for p in phrases):
                    kind, keywords, numeric, verbatim = k, kws, is_numeric, False
                    break
        tid = kind if kind not in used else f"{kind}_{i}"
        used.add(tid)
        topics.append(Topic(id=tid, kind=kind, canonical=q, keywords=keywords, numeric=numeric, verbatim=verbatim))
    return topics


# ── Fixed patient-facing messages ─────────────────────────────────────────

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


# ── Checks on model-written text ──────────────────────────────────────────

def _words(text: str) -> int:
    return len(text.split())


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", text))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _gives_advice(text: str) -> bool:
    return contains_medical_advice(text) or bool(_DIRECTIVE.search(text))


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
        and "?" not in ack                            # questions come only through the question path
    )
    return ack if ok else random.choice(_ACK_PHRASES)


def question_is_safe(question: str, allowed_numbers: set[str]) -> bool:
    q = (question or "").strip()
    return bool(
        q
        and q.endswith("?")
        and q.count("?") == 1
        and _words(q) <= _MAX_QUESTION_WORDS
        and not _gives_advice(q)
        and not any(p in q.lower() for p in _REASSURANCE)
        and _numbers(q) <= allowed_numbers
    )


def safe_clarifying_question(question: str, reply: str) -> str:
    return (question or "").strip() if question_is_safe(question, _numbers(reply)) else CLARIFY_FALLBACK


# ── The agent ─────────────────────────────────────────────────────────────

class ConversationalPatientAgent(PatientAgent):
    def __init__(self, patient_id, db, ai: AIAssist | None = None) -> None:
        super().__init__(patient_id, db)
        self.ai = ai if ai is not None else AIAssist()
        self.topics: list[Topic] = []
        self.remaining: list[Topic] = []
        self.covered_ids: set[str] = set()
        self._current: tuple[str, str] = ("", "")         # (question text shown, topic id or "followup")
        self._parent_id = ""                              # topic a follow-up belongs to
        self._followups_total = 0
        self._followups_by_topic: dict[str, int] = {}
        self._asked: set[str] = set()
        self._clarified = False
        self._deflected = False
        self._first_reply = ""
        self.ended_early = False

    # ── session ───────────────────────────────────────────────────────────
    @property
    def progress(self) -> tuple[int, int]:
        """(checklist topics covered, total topics)."""
        return len(self.covered_ids), len(self.topics)

    def start_session(self) -> str:
        opening = super().start_session()               # loads the record and the standard question list
        doctor_qs = self.db.get_doctor_questions(self.patient_id, date.today().isoformat())
        self.topics = build_topics(self.questions, doctor_qs)
        self.remaining = list(self.topics)
        first = self.remaining.pop(0)
        self._set_current(first.canonical, first.id)
        if not self.ai.enabled:
            return opening
        head, _, rest = opening.partition("\n\n")
        head = re.sub(r"I'll ask you \d+ questions", "I'll ask you some questions", head)
        return f"{head} {DISCLOSURE}\n\n{rest}"

    def respond(self, patient_input: str) -> tuple[str, bool]:
        question, topic_id = self._current
        contact = self.record.care_team_contact
        kind = self._kind_of(topic_id)

        # Emergency rules run first and never depend on the model.
        if self._rules_say_emergency(question, patient_input, kind):
            return self._end_for_emergency(patient_input, contact)

        plan: TurnAnalysis | None = None
        if self.ai.enabled:
            try:
                plan = self.ai.analyze_turn(
                    [c.name for c in self.record.conditions] or [self.record.primary_diagnosis],
                    question, patient_input,
                    patient_id=self.patient_id, known_names=(self.record.name,),
                    prior_reply=self._first_reply if self._clarified else "",
                    history=[(r.question, r.answer) for r in self.responses],
                    remaining=[(t.id, t.canonical) for t in self.remaining],
                )
            except Exception:
                log.warning("Conversation planning failed; using the standard question for this turn", exc_info=True)

        if plan is not None:
            if plan.intent == "emergency":
                return self._end_for_emergency(patient_input, contact)
            if plan.intent == "patient_question" and not self._deflected:
                self._deflected = True
                return f"{deflection_message(contact)}\n\n{question}", False
            if plan.intent == "unclear" and not self._clarified:
                self._clarified = True
                self._first_reply = patient_input
                return safe_clarifying_question(plan.clarifying_question, patient_input), False

        return self._record_and_advance(patient_input, plan)

    # ── state helpers ─────────────────────────────────────────────────────
    def _set_current(self, question: str, topic_id: str) -> None:
        self._current = (question, topic_id)
        self._asked.add(_norm(question))
        if topic_id != "followup":
            self._parent_id = topic_id

    def _kind_of(self, topic_id: str) -> str:
        return next((t.kind for t in self.topics if t.id == topic_id), "followup")

    def _patient_text(self, extra: str = "") -> str:
        return _norm(" ".join([r.answer for r in self.responses if r.question != EMERGENCY_MARKER] + [extra]))

    @staticmethod
    def _rules_say_emergency(question: str, reply: str, kind: str) -> bool:
        return _detect_flags([CheckInResponse(question=question, answer=reply, topic=kind)])[1] == "Escalate"

    def _end_for_emergency(self, reply: str, contact: str) -> tuple[str, bool]:
        self.responses.append(CheckInResponse(question=EMERGENCY_MARKER, answer=reply, topic="emergency"))
        self._save_checkin()
        self.ended_early = True
        return emergency_message(contact), True

    # ── the adaptive core ─────────────────────────────────────────────────
    def _record_and_advance(self, reply: str, plan: TurnAnalysis | None) -> tuple[str, bool]:
        question, topic_id = self._current
        kind = self._kind_of(topic_id)
        answer = f"{self._first_reply} | {reply}" if self._clarified and self._first_reply else reply
        self._clarified = self._deflected = False
        self._first_reply = ""
        self.responses.append(CheckInResponse(question=question, answer=answer, topic=kind))
        if topic_id != "followup":
            self.covered_ids.add(topic_id)

        ack = random.choice(_ACK_PHRASES)
        if plan is not None:
            ack = safe_acknowledgment(plan.acknowledgment, reply)
            self._record_volunteered(plan, reply)
            self._record_covered(plan, reply)
            follow_up = self._valid_follow_up(plan, reply, topic_id)
            if follow_up:
                self._followups_total += 1
                self._followups_by_topic[self._parent_id] = self._followups_by_topic.get(self._parent_id, 0) + 1
                self._set_current(follow_up, "followup")
                return f"{ack}\n\n{follow_up}", False

        if not self.remaining:
            self._save_checkin()
            return (
                "Thank you so much for completing today's check-in! "
                "Your responses have been saved and your care team will review them. "
                f"For urgent concerns please call {self.record.care_team_contact}. Take care!",
                True,
            )

        nxt = self._pick_next(plan)
        self.remaining.remove(nxt)
        text = self._question_text(nxt, plan, reply)
        self._set_current(text, nxt.id)
        return f"{ack}\n\n{text}", False

    def _record_volunteered(self, plan: TurnAnalysis, reply: str) -> None:
        excerpt = (plan.volunteered_concern or "").strip()
        if excerpt and _norm(excerpt) in _norm(reply):             # only the patient's exact words
            self.responses.append(CheckInResponse(question=VOLUNTEERED_MARKER, answer=excerpt, topic="volunteered"))

    def _record_covered(self, plan: TurnAnalysis, reply: str) -> None:
        """Skip topics the patient already answered, but only on verified evidence from their own words."""
        said = self._patient_text(reply)
        for c in plan.covered:
            topic = next((t for t in self.remaining if t.id == c.topic_id), None)
            ev = (c.evidence or "").strip()
            if not topic or not ev or _norm(ev) not in said:
                continue
            if topic.numeric and not re.search(r"\d", ev):
                continue
            self.remaining.remove(topic)
            self.covered_ids.add(topic.id)
            self.responses.append(CheckInResponse(question=topic.canonical, answer=ev, topic=topic.kind))

    def _valid_follow_up(self, plan: TurnAnalysis, reply: str, topic_id: str) -> str:
        q = (plan.follow_up_question or "").strip()
        if not q or plan.intent != "answer":
            return ""
        if self._followups_total >= MAX_FOLLOWUPS_TOTAL:
            return ""
        if self._followups_by_topic.get(self._parent_id, 0) >= MAX_FOLLOWUPS_PER_TOPIC:
            return ""
        if _norm(q) in self._asked or not question_is_safe(q, _numbers(self._patient_text(reply))):
            return ""
        return q

    def _pick_next(self, plan: TurnAnalysis | None) -> Topic:
        if plan is not None and plan.next_topic_id:
            chosen = next((t for t in self.remaining if t.id == plan.next_topic_id), None)
            if chosen:
                return chosen
        return self.remaining[0]

    def _question_text(self, topic: Topic, plan: TurnAnalysis | None, reply: str) -> str:
        """The model's wording if it is safe and on topic, otherwise the standard question."""
        if plan is None or topic.verbatim or not plan.next_question_text:
            return topic.canonical
        # Only chosen topic's wording is accepted, and only if it keeps the topic's own words
        if plan.next_topic_id and plan.next_topic_id != topic.id:
            return topic.canonical
        text = plan.next_question_text.strip()
        allowed = _numbers(self._patient_text(reply)) | _numbers(topic.canonical)
        if not question_is_safe(text, allowed) or not _contains_any(text.lower(), topic.keywords):
            return topic.canonical
        return text
