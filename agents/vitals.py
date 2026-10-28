"""Numeric vital-sign checks on patient answers.

The check-in asks patients for readings (SpO2, temperature, blood pressure,
blood glucose, breathing rate). This module pulls the numbers out of the free
text answer and compares them to the thresholds below.

IMPORTANT: these thresholds are conservative general-purpose DEMO values. They
must be reviewed and set by the clinical team before any real-world use, and
should ideally be personalized per patient (e.g. a COPD patient's SpO2 baseline
is lower than the default here).
"""

from __future__ import annotations
import re
from dataclasses import dataclass

SCHEDULE = "Schedule visit"
ESCALATE = "Escalate"

# ── Thresholds (edit here) ─────────────────────────────────────────────────
SPO2_ESCALATE_BELOW = 90        # %
SPO2_SCHEDULE_BELOW = 92        # %
TEMP_SCHEDULE_F = 100.4         # °F  (38.0 °C)
TEMP_ESCALATE_F = 103.0         # °F  (39.4 °C)
TEMP_LOW_SCHEDULE_F = 95.0      # °F  (35.0 °C)
BP_ESCALATE_SYS, BP_ESCALATE_DIA = 180, 120
BP_SCHEDULE_SYS, BP_SCHEDULE_DIA = 160, 100
BP_LOW_ESCALATE_SYS = 80
BP_LOW_SCHEDULE_SYS = 90
GLUCOSE_ESCALATE_LOW, GLUCOSE_SCHEDULE_LOW = 54, 70       # mg/dL
GLUCOSE_SCHEDULE_HIGH, GLUCOSE_ESCALATE_HIGH = 250, 300   # mg/dL
RESP_SCHEDULE_ABOVE, RESP_ESCALATE_ABOVE = 24, 30         # breaths/min

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_BP = re.compile(r"\b(\d{2,3})\s*(?:/|over)\s*(\d{2,3})\b")


@dataclass
class VitalFlag:
    message: str
    severity: str


def _f_to_c(f: float) -> float:
    return (f - 32) * 5 / 9


def _numbers(text: str, low: float, high: float) -> list[float]:
    return [v for v in (float(m) for m in _NUMBER.findall(text)) if low <= v <= high]


def _check_spo2(answer: str) -> VitalFlag | None:
    text = _BP.sub(" ", answer)
    values = _numbers(text, 50, 100)
    if not values:
        return None
    v = min(values)
    shown = f"{v:g}%"
    if v < SPO2_ESCALATE_BELOW:
        return VitalFlag(f"Low oxygen saturation: {shown} (below {SPO2_ESCALATE_BELOW}%)", ESCALATE)
    if v < SPO2_SCHEDULE_BELOW:
        return VitalFlag(f"Borderline oxygen saturation: {shown} (below {SPO2_SCHEDULE_BELOW}%)", SCHEDULE)
    return None


def _check_temperature(answer: str) -> VitalFlag | None:
    values = _numbers(answer, 30, 110)
    if not values:
        return None
    # Pick the most abnormal reading; 30-45 is read as °C, 90-110 as °F, the rest is ambiguous.
    flags: list[VitalFlag] = []
    for v in values:
        if 30 <= v <= 45:
            f, shown = v * 9 / 5 + 32, f"{v:g} °C"
        elif 90 <= v <= 110:
            f, shown = v, f"{v:g} °F"
        else:
            continue
        if f >= TEMP_ESCALATE_F:
            flags.append(VitalFlag(f"High fever: {shown}", ESCALATE))
        elif f >= TEMP_SCHEDULE_F:
            flags.append(VitalFlag(f"Fever: {shown}", SCHEDULE))
        elif f < TEMP_LOW_SCHEDULE_F:
            flags.append(VitalFlag(f"Low temperature: {shown}", SCHEDULE))
    return _worst(flags)


def _check_bp(answer: str) -> VitalFlag | None:
    flags: list[VitalFlag] = []
    for m in _BP.finditer(answer):
        sys_, dia = int(m.group(1)), int(m.group(2))
        if not (50 <= sys_ <= 300 and 30 <= dia <= 200 and sys_ > dia):
            continue
        shown = f"{sys_}/{dia} mmHg"
        if sys_ >= BP_ESCALATE_SYS or dia >= BP_ESCALATE_DIA:
            flags.append(VitalFlag(f"Severely high blood pressure: {shown}", ESCALATE))
        elif sys_ >= BP_SCHEDULE_SYS or dia >= BP_SCHEDULE_DIA:
            flags.append(VitalFlag(f"High blood pressure: {shown}", SCHEDULE))
        elif sys_ < BP_LOW_ESCALATE_SYS:
            flags.append(VitalFlag(f"Severely low blood pressure: {shown}", ESCALATE))
        elif sys_ < BP_LOW_SCHEDULE_SYS:
            flags.append(VitalFlag(f"Low blood pressure: {shown}", SCHEDULE))
    return _worst(flags)


def _check_glucose(answer: str) -> VitalFlag | None:
    flags: list[VitalFlag] = []
    for v in _numbers(answer, 20, 700):
        shown = f"{v:g} mg/dL"
        if v < GLUCOSE_ESCALATE_LOW:
            flags.append(VitalFlag(f"Severely low blood sugar: {shown}", ESCALATE))
        elif v < GLUCOSE_SCHEDULE_LOW:
            flags.append(VitalFlag(f"Low blood sugar: {shown}", SCHEDULE))
        elif v > GLUCOSE_ESCALATE_HIGH:
            flags.append(VitalFlag(f"Severely high blood sugar: {shown}", ESCALATE))
        elif v > GLUCOSE_SCHEDULE_HIGH:
            flags.append(VitalFlag(f"High blood sugar: {shown}", SCHEDULE))
    return _worst(flags)


def _check_resp_rate(answer: str) -> VitalFlag | None:
    flags: list[VitalFlag] = []
    for v in _numbers(answer, 4, 80):
        shown = f"{v:g} breaths/min"
        if v > RESP_ESCALATE_ABOVE:
            flags.append(VitalFlag(f"Very fast breathing rate: {shown}", ESCALATE))
        elif v > RESP_SCHEDULE_ABOVE:
            flags.append(VitalFlag(f"Fast breathing rate: {shown}", SCHEDULE))
    return _worst(flags)


def _worst(flags: list[VitalFlag]) -> VitalFlag | None:
    if not flags:
        return None
    return max(flags, key=lambda f: f.severity == ESCALATE)


# (question keywords, checker). First rule whose keyword appears in the question wins.
_RULES = [
    (("spo2", "oxygen"), _check_spo2),
    (("temperature",), _check_temperature),
    (("blood pressure",), _check_bp),
    (("check your blood sugar", "glucose"), _check_glucose),
    (("breathing rate", "respiratory rate"), _check_resp_rate),
]


_TOPIC_RULES = {
    "spo2": _check_spo2,
    "temperature": _check_temperature,
    "blood_pressure": _check_bp,
    "blood_sugar_reading": _check_glucose,
    "resp_rate": _check_resp_rate,
}


def check_vitals(question: str, answer: str, topic: str = "") -> VitalFlag | None:
    """Return a flag if the answer to a vital-sign question is out of range.

    `topic` (set by the conversational check-in) is authoritative when present, because
    the question text may have been reworded. Otherwise the question wording decides.
    """
    a = answer.lower().replace("\u00b0", " ")
    if topic and topic != "followup":
        checker = _TOPIC_RULES.get(topic)
        return checker(a) if checker else None
    q = question.lower()
    for keywords, checker in _RULES:
        if any(k in q for k in keywords):
            return checker(a)
    return None


# ── Numeric readings (used for trend tracking) ─────────────────────────────

_KEY_RULES = [
    (("spo2", "oxygen"), "spo2"),
    (("temperature",), "temperature"),
    (("blood pressure",), "blood_pressure"),
    (("check your blood sugar", "glucose"), "blood_sugar_reading"),
    (("breathing rate", "respiratory rate"), "resp_rate"),
]


def vital_key(question: str, topic: str = "") -> str | None:
    """Which vital sign a question asks about (same resolution rules as `check_vitals`)."""
    if topic and topic != "followup":
        return topic if topic in _TOPIC_RULES else None
    q = question.lower()
    for keywords, key in _KEY_RULES:
        if any(k in q for k in keywords):
            return key
    return None


def vital_reading(key: str, answer: str) -> float | None:
    """The single most concerning number in an answer, or None if no usable reading.

    Units: SpO2 %, temperature °F (°C answers are converted), blood pressure = systolic
    mmHg, blood sugar mg/dL, breathing rate breaths/min. When an answer holds several
    numbers, SpO2 takes the lowest, temperature the one furthest from 98.6 °F, and the
    others the highest, matching how the threshold checks pick their worst value.
    """
    a = answer.lower().replace("°", " ")
    if key == "spo2":
        values = _numbers(_BP.sub(" ", a), 50, 100)
        return min(values) if values else None
    if key == "temperature":
        fahrenheit = [v * 9 / 5 + 32 if v <= 45 else v for v in _numbers(a, 30, 110) if v <= 45 or v >= 90]
        return max(fahrenheit, key=lambda f: abs(f - 98.6)) if fahrenheit else None
    if key == "blood_pressure":
        systolic = [int(m.group(1)) for m in _BP.finditer(a)
                    if 50 <= int(m.group(1)) <= 300 and 30 <= int(m.group(2)) <= 200
                    and int(m.group(1)) > int(m.group(2))]
        return float(max(systolic)) if systolic else None
    if key == "blood_sugar_reading":
        values = _numbers(a, 20, 700)
        return max(values) if values else None
    if key == "resp_rate":
        values = _numbers(a, 4, 80)
        return max(values) if values else None
    return None
