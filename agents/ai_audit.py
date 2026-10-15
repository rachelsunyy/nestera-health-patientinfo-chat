"""Append-only audit log of AI model calls.

One JSON line per call. Records WHAT happened (when, which model, which tier,
how long, how many tokens, success or failure, data mode) but never the
content of the request or the response, and only a one-way hash of the patient
reference. Lives next to the patient data (git-ignored).
"""

from __future__ import annotations
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import config

log = logging.getLogger(__name__)


def patient_ref(patient_id: str) -> str:
    """Stable, non-reversible reference to a patient for log correlation."""
    salt = os.getenv("AI_AUDIT_SALT", "")
    return hashlib.sha256(f"{salt}:{patient_id}".encode()).hexdigest()[:16]


def audit_path() -> Path:
    return Path(config.DATA_DIR) / "ai_audit.jsonl"


def record(*, tier: str, model: str, outcome: str, patient: str, latency_ms: int,
           usage=None, stop_reason: str | None = None, error: str | None = None) -> None:
    """Write one audit entry. Never raises: auditing must not break a check-in."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tier": tier,
        "model": model,
        "provider": config.AI_PROVIDER,
        "data_mode": config.AI_DATA_MODE,
        "outcome": outcome,                       # ok | refused | error
        "latency_ms": latency_ms,
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "stop_reason": stop_reason,
        "error_type": error,
        "patient_ref": patient,
    }
    try:
        with audit_path().open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        log.warning("Could not write AI audit entry", exc_info=True)
