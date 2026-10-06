"""Central configuration for the Hospital-At-Home agent."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Model ──────────────────────────────────────────────────────────────────
MODEL_ID = "google/medgemma-1.5-4b-it"
MODEL_MAX_NEW_TOKENS = 512
MODEL_TEMPERATURE = 0.3       # Low temperature → more deterministic, safer outputs
HF_TOKEN = os.getenv("HF_TOKEN")  # Required: accept HaDF terms on HuggingFace first

# ── Storage ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "patient_data"
DATA_DIR.mkdir(exist_ok=True)

# ── Safety ─────────────────────────────────────────────────────────────────
# Phrases that signal the model may be giving medical advice.
# The guardrail replaces any response containing these with a safe redirect.
MEDICAL_ADVICE_TRIGGERS = [
    "you should take",
    "i recommend",
    "i suggest you",
    "my recommendation",
    "increase your dose",
    "decrease your dose",
    "stop taking your",
    "start taking",
    "this could mean you",
    "this indicates you",
    "this suggests you",
    "you likely have",
    "you may have",
    "you might have",
    "i can diagnose",
    "my diagnosis",
    "i would prescribe",
    "call 911",
    "go to the er",
    "go to the emergency room",
    "seek immediate",
]

SAFE_REDIRECT_MESSAGE = (
    "I'm only here to collect information for your care team — "
    "I'm not able to give medical advice or interpret your symptoms. "
    "Please contact your care team directly if you have concerns. "
    "Let's continue with our check-in questions."
)

# ── Care-team notification (stub — replace with real email/webhook) ─────────
CARE_TEAM_EMAIL = os.getenv("CARE_TEAM_EMAIL", "careteam@example.com")
