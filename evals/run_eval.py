"""Measure how well the triage pipeline recommends an action on labeled check-ins.

  python evals/run_eval.py                    # rules only (free, no key needed)
  python evals/run_eval.py --ai               # rules + AI tiers (needs AI env vars, spends API credit)
  python evals/run_eval.py --ai --triage-model claude-sonnet-5-5   # compare a different triage model
  python evals/run_eval.py --ai --out evals/reports/run1.md

Labels in dataset.jsonl are SYNTHETIC and were written without clinician input.
Have clinicians review and correct them before trusting any number from this tool.

What matters most is UNDER-TRIAGE (predicting a lower action than expected, e.g.
Routine when the case needed Escalate). Over-triage costs clinician time; under-triage
can miss a patient who is getting worse. Report both, weigh the first more heavily.
"""

from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from agents.llm_assist import AIAssist  # noqa: E402
from agents.summary_agent import _detect_flags  # noqa: E402
from data.models import CheckInResponse  # noqa: E402

ACTIONS = ["Routine review", "Schedule visit", "Escalate"]
RANK = {a: i for i, a in enumerate(ACTIONS)}
DATASET = Path(__file__).parent / "dataset.jsonl"


def load_cases(path: Path = DATASET) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def predict(case: dict, ai: AIAssist | None) -> tuple[str, str]:
    """Return (rules_action, final_action) for one case."""
    responses = [CheckInResponse(**r) for r in case["responses"]]
    flags, rules_action = _detect_flags(responses)
    if ai is None or not ai.enabled:
        return rules_action, rules_action
    out = ai.assist(case["conditions"], responses, flags, rules_action, with_overview=False)
    return rules_action, out.action


def summarize(cases: list[dict], preds: list[str]) -> dict:
    confusion = {e: Counter() for e in ACTIONS}
    under, over = [], []
    for case, pred in zip(cases, preds):
        exp = case["expected_action"]
        confusion[exp][pred] += 1
        if RANK[pred] < RANK[exp]:
            under.append((case["id"], exp, pred))
        elif RANK[pred] > RANK[exp]:
            over.append((case["id"], exp, pred))
    n = len(cases)
    correct = sum(1 for c, p in zip(cases, preds) if c["expected_action"] == p)
    recall = {}
    for a in ACTIONS:
        total = sum(confusion[a].values())
        recall[a] = (confusion[a][a] / total) if total else None
    return {"n": n, "accuracy": correct / n, "confusion": confusion, "recall": recall,
            "under": under, "over": over}


def render(label: str, s: dict) -> str:
    lines = [f"## {label}", "",
             f"- Cases: {s['n']}",
             f"- Exact match: {s['accuracy']:.0%}",
             f"- **Under-triaged (missed severity): {len(s['under'])}**",
             f"- Over-triaged (extra caution): {len(s['over'])}",
             "- Recall by expected action: " + ", ".join(
                 f"{a} {('n/a' if r is None else f'{r:.0%}')}" for a, r in s["recall"].items()),
             "", "| expected \\ predicted | " + " | ".join(ACTIONS) + " |", "|---|---|---|---|"]
    for e in ACTIONS:
        lines.append(f"| {e} | " + " | ".join(str(s["confusion"][e][p]) for p in ACTIONS) + " |")
    if s["under"]:
        lines += ["", "**Under-triaged cases:**"] + [f"- `{i}`: expected {e}, got {p}" for i, e, p in s["under"]]
    if s["over"]:
        lines += ["", "**Over-triaged cases:**"] + [f"- `{i}`: expected {e}, got {p}" for i, e, p in s["over"]]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ai", action="store_true", help="also run the AI tiers (spends API credit)")
    ap.add_argument("--dataset", type=Path, default=DATASET)
    ap.add_argument("--triage-model"); ap.add_argument("--review-model")
    ap.add_argument("--out", type=Path, help="write the markdown report here")
    args = ap.parse_args()

    cases = load_cases(args.dataset)
    rules = [predict(c, None)[0] for c in cases]
    sections = [render("Rules only", summarize(cases, rules))]

    if args.ai:
        if args.triage_model:
            config.AI_MODEL_TRIAGE = args.triage_model
        if args.review_model:
            config.AI_MODEL_REVIEW = args.review_model
        ai = AIAssist()
        if not ai.enabled:
            sys.exit("AI is not enabled. Set AI_ASSIST_ENABLED=true, AI_DATA_MODE=synthetic and credentials "
                     "(ANTHROPIC_API_KEY, or AI_PROVIDER=vertex with GCP_PROJECT).")
        print(f"Running {len(cases)} cases through triage ({config.AI_MODEL_TRIAGE}) and, when needed, "
              f"review ({config.AI_MODEL_REVIEW})...", file=sys.stderr)
        final = [predict(c, ai)[1] for c in cases]
        sections.append(render(f"Rules + AI (triage {config.AI_MODEL_TRIAGE}, review {config.AI_MODEL_REVIEW})",
                               summarize(cases, final)))

    report = ("# Triage evaluation\n\n"
              "Synthetic labels, not clinician-reviewed. See evals/run_eval.py.\n\n" + "\n\n".join(sections) + "\n")
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report)


if __name__ == "__main__":
    main()
