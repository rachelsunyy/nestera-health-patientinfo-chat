"""Use NoteChat (Wang et al., 2024) patient speech to stress-test the triage rules.

NoteChat (https://arxiv.org/abs/2310.15959, Hugging Face `akemiH/NoteChat`) holds 10,000 synthetic
doctor-patient conversations generated from published case reports. It has NO urgency labels, so it cannot
be scored automatically. This tool does three things instead:

  python -m data.notechat_import --src external_data/notechat/our_revised_v2.csv --audit
      Run the keyword/vitals rules over every patient reply and report how often they fire and on what.
      A firing is NOT an error: these patients are mostly sick. It shows where to look.

  python -m data.notechat_import --src ... --sheet external_data/notechat_label_sheet.csv --n 200
      Write a blind sample for the team or a clinician to label (the rules' output is not shown).

  python -m data.notechat_import --labels external_data/notechat_label_sheet.csv --out external_data/notechat_cases.jsonl
      Turn the labeled rows into eval cases that evals/run_eval.py can score (--dataset ...).

Licence: the dataset card states none, and it derives from published case reports (PMC-Patients is
CC BY-NC-SA). Treat it as non-commercial research data: keep the raw file and anything derived from it out of
the repository (external_data/ is git-ignored) and ask Nestera before using it in a product.
"""

from __future__ import annotations
import argparse
import csv
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.summary_agent import _ACTION_PRIORITY, _CONCERN_PATTERNS, _detect_flags, _is_negated  # noqa: E402
from data.models import CheckInResponse  # noqa: E402

ACTIONS = ["Routine review", "Schedule visit", "Escalate"]
MIN_WORDS = 6          # shorter replies ("Yes.", "Okay, thanks") carry nothing to triage
_TURN = re.compile(r"^(Doctor|Patient)\s*:\s*(.*)$")
csv.field_size_limit(10**9)


def parse_turns(conversation: str) -> list[tuple[str, str]]:
    """Split a transcript into (speaker, text). Lines without a speaker continue the previous turn."""
    turns: list[list[str]] = []
    for line in conversation.splitlines():
        if not line.strip():
            continue
        m = _TURN.match(line.strip())
        if m:
            turns.append([m.group(1), m.group(2).strip()])
        elif turns:
            turns[-1][1] += " " + line.strip()
    return [(s, t) for s, t in turns]


def replies(path: Path):
    """Yield {id, question, reply} for every patient reply that follows a doctor turn."""
    with path.open(encoding="utf8") as f:
        for n, row in enumerate(csv.DictReader(f)):
            turns = parse_turns(row["conversation"])
            for i in range(1, len(turns)):
                (sp0, q), (sp1, a) = turns[i - 1], turns[i]
                if sp0 == "Doctor" and sp1 == "Patient" and len(a.split()) >= MIN_WORDS:
                    yield {"id": f"nc{n:05d}_{i:03d}", "question": q, "reply": a}


def matched_phrases(answer: str) -> list[str]:
    text = answer.lower().replace("’", "'")
    return [p for p, _ in _CONCERN_PATTERNS
            for m in [re.search(rf"\b{re.escape(p)}\b", text)] if m and not _is_negated(text, m.start())]


def rules_action(item: dict) -> str:
    return _detect_flags([CheckInResponse(question=item["question"], answer=item["reply"])])[1]


def audit(path: Path, limit: int | None) -> None:
    n, actions, phrases, examples = 0, Counter(), Counter(), {}
    for item in replies(path):
        a = rules_action(item)
        n += 1
        actions[a] += 1
        for p in matched_phrases(item["reply"]):
            phrases[p] += 1
            examples.setdefault(p, item["reply"])
        if limit and n >= limit:
            break
    print(f"{n} patient replies of {MIN_WORDS}+ words")
    for a in ACTIONS:
        print(f"  {a:15s} {actions[a]:6d}  ({actions[a] / n:.1%})")
    print("\nMost common trigger phrases (and one example each) — read these for over-triggering:")
    for p, c in phrases.most_common(12):
        print(f"  {c:5d}  {p!r}: {examples[p][:140]}")


def write_sheet(path: Path, out: Path, n: int, seed: int) -> None:
    """Blind sample: half where the rules fire, half where they stay quiet (so misses can be found too)."""
    rng = random.Random(seed)
    fired, quiet = [], []
    for item in replies(path):
        (fired if rules_action(item) != "Routine review" else quiet).append(item)
    sample = rng.sample(fired, min(n // 2, len(fired))) + rng.sample(quiet, min(n - n // 2, len(quiet)))
    rng.shuffle(sample)
    with out.open("w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["id", "doctor_question", "patient_reply", "expected_action", "notes"])
        for item in sample:
            w.writerow([item["id"], item["question"], item["reply"], "", ""])
    print(f"Wrote {len(sample)} rows to {out}. Fill expected_action with one of: {', '.join(ACTIONS)}.\n"
          "Judge only what the patient says, as if it were today's home check-in answer. Leave blank if unsure.")


def labels_to_cases(sheet: Path, out: Path) -> None:
    cases, skipped = [], 0
    for row in csv.DictReader(sheet.open(encoding="utf8")):
        label = row["expected_action"].strip()
        if label not in ACTIONS:
            skipped += 1
            continue
        cases.append({"id": row["id"], "conditions": ["Not specified"], "expected_action": label,
                      "note": row["notes"] or "NoteChat patient reply", "category": "notechat_patient_speech",
                      "source": "notechat", "split": "test",
                      "responses": [{"question": row["doctor_question"], "answer": row["patient_reply"]}]})
    out.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n")
    print(f"Wrote {len(cases)} labeled cases to {out} ({skipped} rows skipped: no valid label). "
          f"Labels: {dict(Counter(c['expected_action'] for c in cases))}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, help="NoteChat CSV (columns: data, conversation)")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--limit", type=int, help="stop the audit after this many replies")
    ap.add_argument("--sheet", type=Path, help="write a blind labeling sheet here")
    ap.add_argument("--n", type=int, default=200, help="rows in the labeling sheet")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--labels", type=Path, help="a filled labeling sheet to convert to eval cases")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.audit:
        audit(args.src, args.limit)
    if args.sheet:
        write_sheet(args.src, args.sheet, args.n, args.seed)
    if args.labels:
        labels_to_cases(args.labels, args.out or Path("notechat_cases.jsonl"))
    if not (args.audit or args.sheet or args.labels):
        ap.print_help()


if __name__ == "__main__":
    main()
