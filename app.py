"""FastAPI application — entry point for Cloud Run deployment.

Endpoints:
  POST /patients/register                      — register a patient record
  GET  /patients                               — list all patient IDs
  GET  /patients/{patient_id}                  — get a patient's record

  POST /doctor/questions/{patient_id}          — doctor adds questions for today
  GET  /doctor/questions/{patient_id}          — see today's doctor questions

  POST /session/start/{patient_id}             — start a check-in session
  POST /session/respond/{session_id}           — patient sends a message
  GET  /session/{session_id}/status            — see session progress

  POST /summary/{patient_id}                   — generate today's clinical summary
  GET  /summary/{patient_id}                   — retrieve today's summary

Run locally:
  uvicorn app:app --reload --port 8080

On Cloud Run:
  CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
"""

from __future__ import annotations
import os
import uuid
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel

from config import DATA_DIR
from data.models import PatientRecord, DoctorQuestions, ClinicalSummary
from database.patient_db import MockPatientDatabase, GCSPatientDatabase, FirestorePatientDatabase
from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent


# ── Database selection ─────────────────────────────────────────────────────
# Local dev:   no env vars → MockPatientDatabase (JSON files on disk)
# Cloud Run:   set GCS_BUCKET=hah-agent-data → GCSPatientDatabase
#              set USE_FIRESTORE=true + GCP_PROJECT=... → FirestorePatientDatabase
if os.getenv("USE_FIRESTORE", "false").lower() == "true":
    db = FirestorePatientDatabase(project_id=os.environ["GCP_PROJECT"])
elif os.getenv("GCS_BUCKET"):
    db = GCSPatientDatabase(bucket_name=os.environ["GCS_BUCKET"])
else:
    db = MockPatientDatabase()


# ── In-memory session store ────────────────────────────────────────────────
# Maps session_id → PatientAgent instance.
# For production with multiple Cloud Run instances, replace with Firestore/Redis.
_sessions: dict[str, PatientAgent] = {}


app = FastAPI(
    title="Hospital-At-Home Agent",
    description="Patient check-in collection agent powered by MedGemma",
    version="0.1.0",
)


# ── Request/response schemas ───────────────────────────────────────────────

class MessageRequest(BaseModel):
    message: str

class SessionStartResponse(BaseModel):
    session_id: str
    opening_message: str

class SessionReplyResponse(BaseModel):
    session_id: str
    agent_message: str
    session_complete: bool

class DoctorQuestionsRequest(BaseModel):
    questions: list[str]
    added_by: str = ""


# ── Patient management ─────────────────────────────────────────────────────

@app.post("/patients/register", status_code=201)
def register_patient(record: PatientRecord):
    db.save_patient(record)
    return {"patient_id": record.patient_id, "name": record.name}

@app.get("/patients")
def list_patients():
    return {"patient_ids": db.list_patient_ids()}

@app.get("/patients/{patient_id}")
def get_patient(patient_id: str):
    try:
        return db.get_patient(patient_id)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


# ── Doctor questions ───────────────────────────────────────────────────────

@app.post("/doctor/questions/{patient_id}", status_code=201)
def add_doctor_questions(patient_id: str, body: DoctorQuestionsRequest):
    today = date.today().isoformat()
    dq = DoctorQuestions(
        patient_id=patient_id,
        date=today,
        questions=body.questions,
        added_by=body.added_by,
    )
    db.save_doctor_questions(dq)
    return {"patient_id": patient_id, "date": today, "questions_saved": len(body.questions)}

@app.get("/doctor/questions/{patient_id}")
def get_doctor_questions(patient_id: str):
    today = date.today().isoformat()
    questions = db.get_doctor_questions(patient_id, today)
    return {"patient_id": patient_id, "date": today, "questions": questions}


# ── Check-in sessions ──────────────────────────────────────────────────────

@app.post("/session/start/{patient_id}", response_model=SessionStartResponse)
def start_session(patient_id: str):
    agent = PatientAgent(patient_id, db)
    try:
        opening = agent.start_session()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))

    session_id = str(uuid.uuid4())
    _sessions[session_id] = agent
    return SessionStartResponse(session_id=session_id, opening_message=opening)

@app.post("/session/respond/{session_id}", response_model=SessionReplyResponse)
def respond(session_id: str, body: MessageRequest):
    agent = _sessions.get(session_id)
    if agent is None:
        raise HTTPException(404, f"Session '{session_id}' not found or already completed")

    reply, done = agent.respond(body.message)
    if done:
        del _sessions[session_id]

    return SessionReplyResponse(
        session_id=session_id,
        agent_message=reply,
        session_complete=done,
    )

@app.get("/session/{session_id}/status")
def session_status(session_id: str):
    agent = _sessions.get(session_id)
    if agent is None:
        return {"session_id": session_id, "active": False}
    return {
        "session_id": session_id,
        "active": True,
        "questions_total": len(agent.questions),
        "questions_answered": agent._current_q_index - 1,
    }


# ── Clinical summaries ─────────────────────────────────────────────────────

@app.post("/summary/{patient_id}", response_model=ClinicalSummary)
def generate_summary(patient_id: str):
    try:
        summary = SummaryAgent(patient_id, db).generate()
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(404, str(e))
    return summary

@app.get("/summary/{patient_id}")
def get_summary(patient_id: str, checkin_date: str | None = None):
    d = checkin_date or date.today().isoformat()
    summary = db.get_summary(patient_id, d)
    if summary is None:
        raise HTTPException(404, f"No summary for {patient_id} on {d}")
    return summary


# ── Health check ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}
