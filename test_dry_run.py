"""Dry-run test: patches MedGemma with a stub so the full pipeline can be
exercised without a GPU or HuggingFace credentials.

Run with:
  cd hospital_at_home_agent
  python test_dry_run.py
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Stub the MedGemma client before any agents import it ──────────────────
STUB_RESPONSES = {
    "question_gen": (
        "1. What is your current oxygen saturation reading on your pulse oximeter?\n"
        "2. Have you had any coughing spells today, and if so, are you producing any mucus?\n"
        "3. Have you measured your blood glucose today? If so, what were the fasting and post-meal readings?"
    ),
    "checkin_transition": (
        "Thank you for sharing that. I've noted your response.\n\n"
        "Next question: "
    ),
    "summary": """## Clinical Summary — 2026-10-02

### 1. Overall Status
Patient reports moderate improvement in respiratory symptoms with stable vital signs.

### 2. Symptom Report
- SpO2: 95% (up from 93% yesterday)
- Mild productive cough, decreased frequency
- No fever today (temp 98.6°F)
- Blood glucose fasting 118 mg/dL, post-lunch 145 mg/dL
- Pain: 2/10 chest tightness
- Sleep: 6 hours, interrupted by cough
- All medications taken as scheduled

### 3. Changes from Prior Days
- **Improvement**: SpO2 trending up (+2% over 2 days)
- **New**: Slight decrease in appetite today
- **Stable**: Blood pressure 128/82 (within target)

### 4. Flagged Items
- SpO2 still below 96% target — monitor closely
- Reduced appetite may affect medication adherence and glucose control
- Disrupted sleep from cough — consider timing of cough suppressant

### 5. Recommended Action
Schedule visit

### 6. Full Check-in Transcript

| Question | Patient Response |
|---|---|
| Oxygen saturation? | 95% |
| Coughing spells? | Yes, less frequent, small amount of clear mucus |
| Blood glucose? | Fasting 118, post-lunch 145 |
| Overall feeling? | A bit better than yesterday but still tired |
| Pain? | 2/10 chest tightness |
| Shortness of breath? | Mild when walking to bathroom |
| Appetite? | Not very hungry today |
| Sleep? | 6 hours, woke up a few times coughing |
| Medications taken? | Yes, all of them |
| Vital readings? | Temp 98.6, BP 128/82, SpO2 95% |
| Falls or dizziness? | No |
| Anything else? | Daughter visited, helped with lunch |
""",
}

_call_count = {"n": 0}

def _mock_chat(messages, **kwargs):
    _call_count["n"] += 1
    content = " ".join(str(m.get("content", "")) for m in messages).lower()

    if "generate 3 specific" in content:
        return STUB_RESPONSES["question_gen"]
    if "summary" in content or "clinical" in content:
        return STUB_RESPONSES["summary"]
    # Checkin transition
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
    )
    next_q_start = last_user.find("then ask:")
    if next_q_start != -1:
        next_q = last_user[next_q_start + len("then ask:"):].strip().strip("'\"")
        return f"Thank you for that information.\n\n{next_q}"
    return "Thank you. Let's continue."


# ── Simulate a check-in with scripted patient answers ─────────────────────
PATIENT_ANSWERS = [
    "95% on my pulse oximeter",
    "Yes, coughing less today, clear mucus",
    "Fasting was 118, after lunch about 145",
    "A bit better than yesterday but still tired",
    "2 out of 10, some chest tightness",
    "Mild when I walk to the bathroom",
    "Not very hungry today",
    "6 hours, woke up coughing a few times",
    "Yes, I took all of them with breakfast",
    "Temperature 98.6, blood pressure 128 over 82, oxygen 95",
    "No falls or dizziness",
    "My daughter visited and helped with lunch",
]


def run_dry_run():
    # Import modules first so patch() can find them
    import models.medgemma_client as mc_mod
    import agents.patient_agent as pa_mod
    import agents.summary_agent as sa_mod

    mock_client = MagicMock()
    mock_client.chat = MagicMock(side_effect=_mock_chat)

    # Inject the mock into every module that holds a reference to `client`
    mc_mod.client = mock_client
    pa_mod.llm = mock_client
    sa_mod.llm = mock_client

    if True:  # kept indented for readability / easy revert to context manager
        from data.models import PatientRecord
        from data.store import save_patient_record

        # Load sample patient
        record_path = Path(__file__).parent / "sample_data" / "patient_001.json"
        record = PatientRecord.model_validate(json.loads(record_path.read_text()))
        save_patient_record(record)
        print(f"\n✓ Patient loaded: {record.name}\n")

        from agents.patient_agent import PatientAgent
        from agents.summary_agent import SummaryAgent

        # ── Check-in session ───────────────────────────────────────────────
        agent = PatientAgent(record)
        opening = agent.start_session()
        print("=" * 60)
        print("PATIENT CHECK-IN SESSION")
        print("=" * 60)
        print(f"\nAgent: {opening}\n")

        answer_iter = iter(PATIENT_ANSWERS)
        done = False
        while not done:
            try:
                patient_input = next(answer_iter)
            except StopIteration:
                patient_input = "Nothing else, thank you."
            print(f"Patient: {patient_input}")
            reply, done = agent.respond(patient_input)
            print(f"Agent:   {reply}\n")

        print("\n✓ Check-in complete and saved.\n")

        # ── Summary generation ─────────────────────────────────────────────
        print("=" * 60)
        print("CLINICIAN SUMMARY")
        print("=" * 60)
        summary_agent = SummaryAgent(record)
        summary = summary_agent.generate()
        print(summary.summary_markdown)
        print(f"\nFlagged items: {summary.flagged_items}")
        print(f"Recommended action: {summary.recommended_action}")
        print(f"\n✓ Summary saved. Total LLM calls: {_call_count['n']}")


if __name__ == "__main__":
    run_dry_run()
