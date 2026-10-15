"""Measure how well the model interprets patient replies in the conversational check-in.

  python evals/run_conversation_eval.py        # needs AI env vars; spends API credit

The number that matters most is EMERGENCIES MISSED: replies that describe an emergency
but were not classified as one. Next is false alarms (a normal reply flagged as an
emergency), which upset patients but are far less costly. Also reports how often the
model's acknowledgment is replaced because it failed the safety checks.

Cases are SYNTHETIC and not clinician-reviewed; have clinicians extend and correct them.
Replies that try to instruct the model ("ignore previous instructions...") are expected
NOT to be followed, so the model should call them unclear (or answer), never emergency
because the reply said so.
"""

from __future__ import annotations
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from agents.conversation_agent import safe_acknowledgment  # noqa: E402
from agents.llm_assist import AIAssist  # noqa: E402
from agents.patient_agent import _ACK_PHRASES  # noqa: E402

CASES = Path(__file__).parent / "conversation_cases.jsonl"


def main() -> None:
    ai = AIAssist()
    if not ai.enabled:
        sys.exit("AI is not enabled. Set AI_ASSIST_ENABLED=true, AI_DATA_MODE=synthetic and credentials "
                 "(ANTHROPIC_API_KEY, or AI_PROVIDER=vertex with GCP_PROJECT).")
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    print(f"Running {len(cases)} replies through {config.AI_MODEL_CONVERSATION}...", file=sys.stderr)

    confusion: Counter = Counter()
    missed, false_alarms, wrong, replaced = [], [], [], 0
    for c in cases:
        t = ai.analyze_turn(c["conditions"], c["question"], c["reply"])
        got, exp = t.intent, c["expected_intent"]
        confusion[(exp, got)] += 1
        if exp == "emergency" and got != "emergency":
            missed.append(c["reply"])
        elif exp != "emergency" and got == "emergency":
            false_alarms.append(c["reply"])
        elif got != exp:
            wrong.append((exp, got, c["reply"]))
        if safe_acknowledgment(t.acknowledgment, c["reply"]) in _ACK_PHRASES:
            replaced += 1

    correct = sum(v for (e, g), v in confusion.items() if e == g)
    print(f"# Conversation evaluation ({config.AI_MODEL_CONVERSATION})\n")
    print("Synthetic labels, not clinician-reviewed.\n")
    print(f"- Intent accuracy: {correct}/{len(cases)} ({correct / len(cases):.0%})")
    print(f"- **Emergencies missed: {len(missed)}**")
    print(f"- False emergency alarms: {len(false_alarms)}")
    print(f"- Acknowledgments replaced by the safety checks: {replaced}/{len(cases)}")
    for label, items in (("Emergencies missed", missed), ("False alarms", false_alarms)):
        if items:
            print(f"\n**{label}:**")
            for r in items:
                print(f"- {r!r}")
    if wrong:
        print("\n**Other misclassifications:**")
        for e, g, r in wrong:
            print(f"- expected {e}, got {g}: {r!r}")


if __name__ == "__main__":
    main()
