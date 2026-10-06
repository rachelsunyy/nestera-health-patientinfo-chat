"""Safety guardrails: prevent medical advice from reaching the patient."""

from config import MEDICAL_ADVICE_TRIGGERS, SAFE_REDIRECT_MESSAGE


def contains_medical_advice(text: str) -> bool:
    lower = text.lower()
    return any(trigger in lower for trigger in MEDICAL_ADVICE_TRIGGERS)


def apply_guardrail(response: str) -> str:
    """Return the response unchanged, or replace it with a safe redirect."""
    if contains_medical_advice(response):
        return SAFE_REDIRECT_MESSAGE
    return response
