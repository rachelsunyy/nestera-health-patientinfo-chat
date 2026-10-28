"""Longitudinal trend tracking across daily check-ins.

Deterministic and model-free. Each stored check-in is reduced to a `DayPoint`
(its recommended action, any reported vital-sign readings, and counts of
"worse"/"better" symptom reports). The latest day is then compared with the
earlier days in the window to label the patient Improving, Stable or Worsening,
with plain-language reasons the clinician can verify.

IMPORTANT: the bands and margins below are DEMO values chosen for a prototype.
Like the thresholds in `vitals.py`, they need clinical review before real use.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field

from agents.markers import EMERGENCY_MARKER
from agents.vitals import vital_key, vital_reading

WORSENING, IMPROVING, STABLE, INSUFFICIENT = "Worsening", "Improving", "Stable", "Not enough data"
WINDOW = 5      # most recent check-ins considered, including the latest

# key: (label, unit, lower normal limit, upper normal limit, change that counts as a real move)
# "Distance from normal" is how far a reading sits outside [low, high]; 0 means inside the band.
_VITALS = {
    "spo2":                {"label": "Oxygen saturation", "unit": "%",      "low": 95.0,  "high": 100.0, "margin": 1.0},
    "temperature":         {"label": "Temperature",       "unit": " °F",    "low": 97.0,  "high": 99.5,  "margin": 0.7},
    "blood_pressure":      {"label": "Systolic BP",       "unit": " mmHg",  "low": 100.0, "high": 130.0, "margin": 10.0},
    "blood_sugar_reading": {"label": "Blood sugar",       "unit": " mg/dL", "low": 70.0,  "high": 180.0, "margin": 30.0},
    "resp_rate":           {"label": "Breathing rate",    "unit": "/min",   "low": 12.0,  "high": 20.0,  "margin": 2.0},
}
VITAL_LABELS = {k: f"{v['label']} ({v['unit'].strip()})" for k, v in _VITALS.items()}

# Slow drifts inside the normal band that still matter: key -> (adverse direction, drift size)
_DRIFT = {"spo2": (-1, 3.0), "temperature": (+1, 1.0), "resp_rate": (+1, 4.0)}

_WORSE = ("not better", "no better", "not improving", "worse", "worsening", "more swollen", "more short of breath",
          "more tired", "more dizzy", "more pain", "getting worse")
_BETTER = ("better", "improved", "improving", "resolved")


@dataclass
class DayPoint:
    date: str
    action: str
    vitals: dict[str, float] = field(default_factory=dict)
    worse: int = 0      # answers reporting a symptom as worse
    better: int = 0     # answers reporting a symptom as better


@dataclass
class TrendReport:
    status: str
    reasons: list[str]
    points: list[DayPoint]

    @property
    def actionable(self) -> bool:
        return self.status == WORSENING


def _count_phrases(answer: str, phrases: tuple[str, ...]) -> int:
    from agents.summary_agent import _is_negated      # imported here: summary_agent imports this module
    text = answer.lower().replace("’", "'")
    hits = 0
    for p in phrases:
        for m in re.finditer(rf"\b{re.escape(p)}\b", text):
            if not _is_negated(text, m.start()):
                hits += 1
                break
    return hits


def day_point(checkin) -> DayPoint:
    """Reduce one stored check-in to the signals trend tracking compares."""
    from agents.summary_agent import _detect_flags
    _, action = _detect_flags(checkin.responses)
    point = DayPoint(date=checkin.date, action=action)
    for r in checkin.responses:
        if r.question == EMERGENCY_MARKER:
            continue
        key = vital_key(r.question, r.topic)
        if key:
            value = vital_reading(key, r.answer)
            if value is not None:
                point.vitals[key] = value
            continue
        if _count_phrases(r.answer, _WORSE):
            point.worse += 1
        elif _count_phrases(r.answer, _BETTER):
            point.better += 1
    return point


def _distance(key: str, value: float) -> float:
    spec = _VITALS[key]
    return max(0.0, spec["low"] - value, value - spec["high"])


def _fmt(key: str, value: float) -> str:
    return f"{value:g}{_VITALS[key]['unit']}"


def _vital_signals(points: list[DayPoint]) -> tuple[list[str], list[str]]:
    """(worsening reasons, improving reasons) from numeric readings."""
    worse: list[str] = []
    better: list[str] = []
    for key, spec in _VITALS.items():
        series = [(p.date, p.vitals[key]) for p in points if key in p.vitals]
        if len(series) < 2 or series[-1][0] != points[-1].date:
            continue                    # need a reading today and at least one earlier one
        latest, prior = series[-1][1], [v for _, v in series[:-1]]
        base_dist = sum(_distance(key, v) for v in prior) / len(prior)
        dist = _distance(key, latest)
        trail = " → ".join(_fmt(key, v) for _, v in series)
        if dist > base_dist + spec["margin"]:
            worse.append(f"{spec['label']} moving outside the normal range: {trail}")
            continue
        if key in _DRIFT:
            direction, size = _DRIFT[key]
            change = direction * latest - min(direction * v for v in prior)   # move away from the best earlier reading
            if change >= size:
                worse.append(f"{spec['label']} drifting the wrong way: {trail}")
                continue
        if dist < base_dist - spec["margin"]:
            better.append(f"{spec['label']} returning toward normal: {trail}")
    return worse, better


def assess_trend(checkins: list, window: int = WINDOW) -> TrendReport:
    """Label the patient's trajectory from check-ins (any order); the newest one is 'today'."""
    ordered = sorted(checkins, key=lambda c: c.date)[-window:]
    points = [day_point(c) for c in ordered]
    if len(points) < 2:
        return TrendReport(INSUFFICIENT, ["Trend tracking needs at least two check-ins."], points)

    rank = {"Routine review": 0, "Schedule visit": 1, "Escalate": 2}
    latest, previous = points[-1], points[:-1]
    worse, better = _vital_signals(points)

    prev_peak = max(rank[p.action] for p in previous)
    if rank[latest.action] > prev_peak:
        worse.append(f"Recommended action rose to {latest.action} (previously at most {_label(prev_peak)})")
    elif rank[latest.action] < rank[previous[-1].action] and rank[latest.action] == 0:
        better.append(f"Recommended action eased to {latest.action} (was {previous[-1].action} yesterday)")

    recent = points[-3:]
    if latest.worse and sum(1 for p in recent if p.worse) >= 2:
        worse.append(f"Patient reported symptoms as worse on {sum(1 for p in recent if p.worse)} of the last {len(recent)} check-ins")
    elif latest.worse > previous[-1].worse:
        worse.append("Patient reports more symptoms getting worse than at the last check-in")
    if latest.better > latest.worse and previous[-1].worse and not worse:
        better.append("Patient reports symptoms improving after reporting them worse previously")

    if worse:
        return TrendReport(WORSENING, worse, points)
    if better:
        return TrendReport(IMPROVING, better, points)
    return TrendReport(STABLE, ["No meaningful change across the last "
                                f"{len(points)} check-ins."], points)


def _label(priority: int) -> str:
    return ("Routine review", "Schedule visit", "Escalate")[priority]
