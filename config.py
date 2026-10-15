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

# ── Optional AI assist (Anthropic Claude) ──────────────────────────────────
# OFF by default. When on, the deterministic rules still run first and set a
# floor: AI can raise a recommended action or add notes, never lower it.
#
# PHI WARNING: only enable this with real patient data after your organization
# has a signed BAA covering the exact service you use, and has confirmed that
# the models below are available under it. See README -> "AI assist and patient data".
AI_ASSIST_ENABLED = os.getenv("AI_ASSIST_ENABLED", "false").lower() == "true"
# Enabling AI requires an explicit data-handling decision (there is no default):
#   AI_DATA_MODE=synthetic   -> only fake/demo patients are in this deployment
#   AI_DATA_MODE=phi         -> real patient data; ALSO requires AI_BAA_CONFIRMED=true,
#                               meaning a BAA covering the chosen route is signed and on file.
AI_DATA_MODE = os.getenv("AI_DATA_MODE", "").lower()
AI_BAA_CONFIRMED = os.getenv("AI_BAA_CONFIRMED", "false").lower() == "true"
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic")        # "anthropic" or "vertex"
GCP_PROJECT = os.getenv("GCP_PROJECT")                     # vertex only
GCP_REGION = os.getenv("GCP_REGION", "global")             # vertex only

# Models stratified by reasoning requirement (override with env vars)
AI_MODEL_TRIAGE = os.getenv("AI_MODEL_TRIAGE", "claude-haiku-5-5")    # every check-in: cheap, fast, low reasoning
AI_MODEL_SUMMARY = os.getenv("AI_MODEL_SUMMARY", "claude-sonnet-5-5") # every check-in: clinician-facing overview
AI_MODEL_REVIEW = os.getenv("AI_MODEL_REVIEW", "claude-opus-5-5")     # only escalations / disagreements: deepest reasoning
