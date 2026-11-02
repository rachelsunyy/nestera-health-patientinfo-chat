"""Central configuration for the Hospital-At-Home agent."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Storage ────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "patient_data"
DATA_DIR.mkdir(exist_ok=True)

# ── Safety ─────────────────────────────────────────────────────────────────
# Phrases that signal the model may be giving medical advice.
# conversation_agent rejects any model-written patient message containing these.
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

# Patient-facing conversational check-in (needs AI assist enabled and configured as above).
# A fixed coverage checklist (what must be covered) and the recorded answers stay deterministic; the model
# decides how and in what order to ask, adapts follow-up questions to the replies, and acknowledges them.
AI_CONVERSATION_ENABLED = os.getenv("AI_CONVERSATION_ENABLED", "false").lower() == "true"
AI_MODEL_CONVERSATION = os.getenv("AI_MODEL_CONVERSATION", "claude-sonnet-5-5")  # plans each turn: needs judgment, but stays fast
AI_EFFORT_CONVERSATION = os.getenv("AI_EFFORT_CONVERSATION", "low")                # low | medium | high
