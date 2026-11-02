"""Safety guardrails: prevent medical advice from reaching the patient."""

from config import MEDICAL_ADVICE_TRIGGERS


def contains_medical_advice(text: str) -> bool:
    lower = text.lower()
    return any(trigger in lower for trigger in MEDICAL_ADVICE_TRIGGERS)
