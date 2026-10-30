"""Build evals/dataset_v2.jsonl: the original 37 cases plus several hundred more.

  python evals/build_dataset.py            # rewrite dataset_v2.jsonl (deterministic, seeded)

Where the cases come from
  - dataset.jsonl (the original 37) is copied in unchanged, so earlier results stay reproducible.
  - case_bank.py holds hand-written patient phrasings with expected actions.
  - The numeric vital-sign sweeps and the routine check-ins are generated here from templates.

Independence of the labels
  Expected actions come from the clinical meaning of each case, never from the output of the rules
  or a model. The numeric labels below are a separate copy of the thresholds documented in the README,
  so a disagreement with agents/vitals.py shows up as a failing case instead of being hidden.
  Do not tune the rules or prompts on the "test" split.

Every case carries a `category` (for per-category reporting), a `source` and a `split`
("dev" or "test", fixed by a hash of the id). All labels are synthetic and not clinician-reviewed.
"""

from __future__ import annotations
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from agents.patient_agent import _build_questions  # noqa: E402
from data.models import Condition, Medication, PatientRecord  # noqa: E402
import case_bank as bank  # noqa: E402

E, S, R = bank.E, bank.S, bank.R
RANK = {R: 0, S: 1, E: 2}
SEED = 20261029
OUT = Path(__file__).parent / "dataset_v2.jsonl"
ORIGINAL = Path(__file__).parent / "dataset.jsonl"

# ── Patient profiles (questions come from the real question builder) ──────────────────────────
ALL_VITALS = ["oxygen saturation (SpO2)", "temperature", "blood pressure", "blood glucose", "respiratory rate"]
MEDS = [Medication(name="Example drug", dose="10mg", frequency="daily")]


def profile(name: str, conditions: list[str], tags: set[str]) -> dict:
    rec = PatientRecord(
        patient_id="eval", name="Eval Patient", date_of_birth="1950-01-01", care_team_contact="n/a",
        admission_date="2026-01-01", primary_diagnosis=conditions[0],
        conditions=[Condition(name=c) for c in conditions], medications=MEDS, monitoring_parameters=ALL_VITALS)
    return {"name": name, "conditions": conditions, "tags": tags, "questions": _build_questions(rec, [])}


PROFILES = [
    profile("pna_dm_htn", ["Community-acquired pneumonia", "Type 2 diabetes mellitus", "Hypertension"],
            {"pneumonia", "diabetes", "hypertension"}),
    profile("hf", ["Heart failure", "Hypertension", "Type 2 diabetes mellitus"],
            {"heart failure", "hypertension", "diabetes"}),
    profile("copd", ["COPD exacerbation"], {"copd"}),
    profile("stroke", ["Stroke", "Hypertension"], {"stroke", "hypertension"}),
    profile("ckd", ["Chronic kidney disease", "Hypertension", "Type 2 diabetes mellitus"],
            {"kidney", "hypertension", "diabetes"}),
]

VITAL_QUESTIONS = {
    "spo2": "Did you measure your oxygen level (SpO2) today? If yes, what was the reading?",
    "temp": "Did you take your temperature today? If yes, what was the reading?",
    "bp": "Did you check your blood pressure today? If yes, what was the reading?",
    "glucose": "Did you check your blood sugar today? If yes, what were the readings?",
    "resp": "Did you count or measure your breathing rate today? If yes, what was it?",
}

OPEN_QUESTION = "Is there anything else you would like your care team to know?"

_KIND_RULES = [
    ("oxygen level", "spo2"), ("take your temperature", "temp"), ("blood pressure", "bp"),
    ("check your blood sugar", "glucose"), ("breathing rate", "resp"), ("shakiness", "sugar_low"),
    ("weighed yourself", "weight"), ("weigh yourself", "weight"), ("cough", "cough"),
    ("fever or chills", "fever"), ("rescue inhaler", "inhaler"), ("weakness, numbness", "neuro"),
    ("fluid", "fluid"), ("swelling", "swelling"), ("medications", "meds"), ("scale of 1 to 10", "wellbeing"),
    ("falls", "falls"), ("anything else", "other"), ("breathing", "breathing"),
]


def kind_of(question: str) -> str:
    q = question.lower()
    return next((k for needle, k in _KIND_RULES if needle in q), "other")


BENIGN_POOL = {
    "cough": ["Better, hardly coughing", "About the same, dry cough", "Much less coughing today",
              "Same as yesterday, nothing new", "Clear mucus, less than before"],
    "breathing": ["Comfortable", "Breathing easy today", "Fine, no trouble at all",
                  "Comfortable at rest and walking", "Normal for me"],
    "fever": ["No fever or chills", "None", "Nothing like that"],
    "sugar_low": ["No, felt normal", "No shakiness at all", "Nope, steady all day"],
    "meds": ["Yes, all of them", "Took everything on time", "Yes, morning and evening doses"],
    "wellbeing": ["7, a bit better", "8", "6, about the same as yesterday", "9, much better"],
    "falls": ["Nope, everything's fine at home", "All good, I feel safe", "No issues at home"],
    "other": ["Nothing else", "No, that's all", "All good, thanks"],
    "swelling": ["No new swelling", "Legs look the same as usual", "Swelling is a little less"],
    "weight": ["182, same as yesterday", "176, down half a pound", "190, no change"],
    "neuro": ["No, nothing like that", "No new weakness or numbness"],
    "fluid": ["About the usual amount", "Drinking normally"],
    "inhaler": ["Just once this morning", "Didn't need it today", "Once after my walk"],
}


def benign_answer(kind: str, rng: random.Random) -> str:
    if kind == "spo2":
        return rng.choice(["{}%", "{} on room air", "It was {}", "{} percent"]).format(rng.randint(95, 99))
    if kind == "temp":
        return rng.choice(["{:.1f}", "{:.1f} F", "It was {:.1f}"]).format(rng.uniform(97.4, 99.1))
    if kind == "bp":
        return f"{rng.randint(108, 134)}/{rng.randint(66, 84)}"
    if kind == "glucose":
        return f"{rng.randint(90, 130)} this morning and {rng.randint(110, 165)} after dinner"
    if kind == "resp":
        return str(rng.randint(13, 20))
    return rng.choice(BENIGN_POOL[kind])


def make_case(cid: str, category: str, prof: dict, overrides: dict[str, str], expected: str, note: str,
              source: str, rng: random.Random) -> dict:
    """A full check-in: every question gets a benign answer except the ones in `overrides` (kind -> answer)."""
    questions = list(prof["questions"])
    kinds = [kind_of(q) for q in questions]
    for kind in list(overrides):
        if kind in kinds:
            continue
        if kind in VITAL_QUESTIONS:                 # vital question cut by the 10-question cap: add it back
            questions.append(VITAL_QUESTIONS[kind]); kinds.append(kind)
        elif "other" not in kinds:                  # open-ended question cut by the cap: add it back
            questions.append(OPEN_QUESTION); kinds.append("other")
    fallback = {(k if k in kinds else "other"): v for k, v in overrides.items()}
    assert len(fallback) == len(overrides), f"two target answers collide on one question: {cid}"
    overrides = fallback
    responses = []
    for q, k in zip(questions, kinds):
        responses.append({"question": q, "answer": overrides.get(k) or benign_answer(k, rng)})
    answers = {r["answer"] for r in responses}
    assert all(v in answers for v in overrides.values()), f"target answer missing from case {cid}"
    return {"id": cid, "conditions": prof["conditions"], "expected_action": expected, "note": note,
            "responses": responses, "category": category, "source": source}


def compatible(entry_profile: str) -> list[dict]:
    return [p for p in PROFILES if entry_profile == "any" or entry_profile in p["tags"]]


# ── Numeric sweeps (labels from a separate copy of the documented thresholds) ─────────────────
def spo2_label(v): return E if v < 90 else S if v < 92 else R
def temp_label(f): return E if f >= 103 else S if (f >= 100.4 or f < 95) else R
def bp_label(s, d): return E if (s >= 180 or d >= 120 or s < 80) else S if (s >= 160 or d >= 100 or s < 90) else R
def glucose_label(g): return E if (g < 54 or g > 300) else S if (g < 70 or g > 250) else R
def resp_label(r): return E if r > 30 else S if r > 24 else R


def numeric_cases(rng: random.Random) -> list[tuple[str, str, str, str, str]]:
    """(category, kind, answer, expected, note)"""
    out = []
    spo2_frames = ["{}%", "{} on room air", "It was {} percent", "Sat was {}", "{}"]
    for i, v in enumerate([99, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88, 86, 84, 80]):
        out.append(("numeric_spo2", "spo2", spo2_frames[i % 5].format(v), spo2_label(v), f"SpO2 {v}"))
    for i, f in enumerate([97.8, 98.6, 99.2, 99.9, 100.3, 100.4, 100.8, 101.6, 102.4, 102.9, 103.0, 104.1, 94.2, 93.5]):
        out.append(("numeric_temp", "temp", ["{} F", "{}", "{}°F", "It's {}"][i % 4].format(f), temp_label(f), f"Temp {f} F"))
    for c in [36.6, 37.4, 37.9, 38.0, 38.4, 39.0, 39.4, 40.1]:
        out.append(("numeric_temp", "temp", f"{c} C", temp_label(c * 9 / 5 + 32), f"Temp {c} C"))
    for i, (s, d) in enumerate([(118, 76), (132, 84), (145, 92), (158, 98), (160, 90), (150, 100), (164, 96),
                                (172, 104), (179, 119), (180, 100), (150, 120), (196, 118), (112, 70),
                                (92, 58), (89, 56), (86, 50), (79, 48), (74, 44)]):
        frame = ["{}/{}", "{} over {}", "It was {}/{} this morning", "BP {}/{}"][i % 4]
        out.append(("numeric_bp", "bp", frame.format(s, d), bp_label(s, d), f"BP {s}/{d}"))
    for i, g in enumerate([98, 126, 180, 240, 250, 251, 275, 300, 301, 340, 69, 70, 65, 60, 54, 53, 48, 40]):
        out.append(("numeric_glucose", "glucose", ["{}", "{} mg/dL", "Morning reading was {}", "{} fasting"][i % 4].format(g),
                    glucose_label(g), f"Glucose {g}"))
    out += [("numeric_glucose", "glucose", "110 in the morning and 45 this afternoon", E, "Two readings, one severe low"),
            ("numeric_glucose", "glucose", "320 before lunch, 210 after", E, "Two readings, one severe high"),
            ("numeric_glucose", "glucose", "105 and 98", R, "Two normal readings")]
    for mmol in [6.1, 6.5, 3.5, 2.8, 15.0, 18.0]:
        mg = mmol * 18.0
        out.append(("numeric_glucose_mmol", "glucose", f"{mmol} mmol/L", glucose_label(mg), f"Glucose {mmol} mmol/L (~{mg:.0f} mg/dL)"))
    for r in [14, 18, 22, 24, 25, 28, 30, 31, 36]:
        out.append(("numeric_resp", "resp", str(r), resp_label(r), f"Resp rate {r}"))
    return out


# ── Explicit wording the keyword rules are designed to catch ──────────────────────────────────
KEYWORD = [
    ("other", "Yes, I had chest pain this morning for about twenty minutes", E),
    ("breathing", "Some chest pain when I climbed the stairs, had to stop", E),
    ("other", "Chest pain, it's still there right now", E),
    ("other", "A feeling of chest tightness since lunch that won't ease up", E),
    ("breathing", "Chest tightness and I'm wheezing", E),
    ("breathing", "I can't breathe properly, it's getting scary", E),
    ("breathing", "I cannot breathe lying down", E),
    ("other", "I passed out in the garden this afternoon", E),
    ("other", "My wife says I fainted in the kitchen", E),
    ("other", "Bleeding from the wound, soaked through the gauze twice", E),
    ("other", "Nose bleeding for over an hour and it won't stop", E),
    ("breathing", "Yes, I'm short of breath walking to the bathroom", S),
    ("breathing", "A bit of shortness of breath on the stairs today", S),
    ("cough", "Worse than yesterday, more mucus", S),
    ("wellbeing", "4, I'm worse today", S),
    ("other", "I think I'm getting worse, more tired each day", S),
    ("falls", "Yes, I fell in the bathroom this morning", S),
    ("falls", "I fell getting out of bed but didn't hit my head", S),
    ("meds", "I forgot my evening pills last night", S),
    ("meds", "I didn't take the water pill, it makes me run to the bathroom", S),
    ("meds", "Did not take my metformin yesterday", S),
    ("meds", "I skipped this morning's dose, felt queasy", S),
    ("sugar_low", "Yes, very dizzy and shaky around noon", S),
    ("other", "I've been very dizzy when standing", S),
    ("other", "Feeling confused this afternoon, kept losing my train of thought", S),
    ("other", "My wife says I've been confused since last night", S),
    ("swelling", "My left leg is more swollen than the right and than yesterday", S),
    ("swelling", "Feet more swollen today", S),
    ("falls", "Had a fall in the hallway, sore but walking", S),
    ("other", "Shortness of breath and I fell this morning", S),
    ("other", "Worse cough and I forgot my antibiotic once", S),
    ("other", "Chest pain and worse shortness of breath", E),
    ("breathing", "Short of breath and can't breathe lying flat", E),
    ("other", "Fainted briefly and bleeding from a cut that won't stop", E),
]


# ── Assembly ──────────────────────────────────────────────────────────────────────────────────
def split_of(cid: str) -> str:
    return "test" if int(hashlib.md5(cid.encode()).hexdigest(), 16) % 10 < 3 else "dev"


def build_cases() -> list[dict]:
    rng = random.Random(SEED)
    cases: list[dict] = []
    for line in ORIGINAL.read_text().splitlines():
        if line.strip():
            c = json.loads(line)
            c.update(category="original_v1", source="original")
            cases.append(c)

    counters: dict[str, int] = {}

    def add(category, prof, overrides, expected, note, source):
        counters[category] = counters.get(category, 0) + 1
        cases.append(make_case(f"{category}_{counters[category]:03d}", category, prof, overrides, expected, note, source, rng))

    def rotate(idx: int, entry_profile: str) -> dict:
        opts = compatible(entry_profile)
        return opts[idx % len(opts)]

    # routine check-ins: random benign answers across all profiles
    for i in range(60):
        add("routine", PROFILES[i % len(PROFILES)], {}, R, "All answers benign", "template")

    for i, (cat, kind, answer, expected, note) in enumerate(numeric_cases(rng)):
        add(cat, PROFILES[i % len(PROFILES)], {kind: answer}, expected, note, "template")

    for name, entries in [("keyword", [(k, a, x, "any") for k, a, x in KEYWORD]),
                          ("informal_escalate", bank.INFORMAL_ESCALATE),
                          ("informal_schedule", bank.INFORMAL_SCHEDULE),
                          ("benign_trap", bank.BENIGN),
                          ("typo_shorthand", bank.TYPO_SHORTHAND)]:
        for i, (kind, answer, expected, prof) in enumerate(entries):
            add(name, rotate(i, prof), {kind: answer}, expected, answer[:60], "authored")

    for name, entries in [("injection", bank.INJECTION), ("contradictory", bank.CONTRADICTORY), ("rambling", bank.RAMBLING)]:
        for i, (kind, answer, expected) in enumerate(entries):
            add(name, PROFILES[i % len(PROFILES)], {kind: answer}, expected, answer[:60], "authored")

    # multi-signal check-ins: two or three findings in one check-in; the label is the most severe one
    pools = [("informal_escalate", bank.INFORMAL_ESCALATE), ("informal_schedule", bank.INFORMAL_SCHEDULE),
             ("keyword", [(k, a, x, "any") for k, a, x in KEYWORD]), ("benign_trap", bank.BENIGN)]
    for i in range(40):
        prof = PROFILES[i % len(PROFILES)]
        picks, used_kinds = [], set()
        for _ in range(rng.choice([2, 2, 3])):
            for _try in range(30):
                _, pool = rng.choice(pools)
                kind, answer, expected, pp = rng.choice(pool)
                kinds = {kind_of(q) for q in prof["questions"]}
                eff = kind if kind in kinds else "other"
                if (pp == "any" or pp in prof["tags"]) and eff not in used_kinds:
                    used_kinds.add(eff); picks.append((kind, answer, expected)); break
        if len(picks) < 2:
            continue
        expected = max((p[2] for p in picks), key=RANK.get)
        add("multi_signal", prof, {k: a for k, a, _ in picks}, expected, " + ".join(p[1][:30] for p in picks), "authored")

    for c in cases:
        c["split"] = split_of(c["id"])
    return cases


def main() -> None:
    cases = build_cases()
    OUT.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n")

    from collections import Counter
    print(f"wrote {len(cases)} cases to {OUT.name}")
    print("labels:", dict(Counter(c["expected_action"] for c in cases)))
    print("splits:", dict(Counter(c["split"] for c in cases)))
    for cat, n in Counter(c["category"] for c in cases).items():
        print(f"  {cat:24s} {n}")


if __name__ == "__main__":
    main()
