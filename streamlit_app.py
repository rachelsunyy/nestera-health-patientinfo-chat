"""Hospital-At-Home — Streamlit interface.

Workflow:
  1. Doctor uploads patient JSON → patient appears in system
  2. Patient opens app, selects name → chatbot asks personalized questions
  3. Patient answers → check-in saved automatically
  4. Summary is auto-generated the moment patient finishes
  5. Doctor opens dashboard → sees clinical note built from patient's exact responses
"""

import json
import os
import re
from datetime import date
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Hospital-At-Home",
    page_icon="🏥",
    layout="wide",
)

# ── Database ───────────────────────────────────────────────────────────────
from database.patient_db import MockPatientDatabase, GCSPatientDatabase
from data.models import PatientRecord, DoctorQuestions
from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent


@st.cache_resource
def get_db():
    bucket = os.getenv("GCS_BUCKET")
    if bucket:
        return GCSPatientDatabase(bucket)
    db = MockPatientDatabase()
    # Auto-load demo patients if DB is empty
    for sample_file in sorted(
        (Path(__file__).parent / "sample_data").glob("patient_*.json")
    ):
        try:
            record = PatientRecord.model_validate_json(sample_file.read_text())
            if record.patient_id not in db.list_patient_ids():
                db.save_patient(record)
        except Exception:
            pass
    return db


db = get_db()


def patient_label(patient_id: str) -> str:
    """Show a patient's name in pickers instead of the raw ID."""
    try:
        return db.get_patient(patient_id).name
    except Exception:
        return patient_id


# ── Helpers ────────────────────────────────────────────────────────────────

def show_summary(summary) -> None:
    color = {
        "Routine review": "green",
        "Schedule visit": "orange",
        "Escalate": "red",
    }.get(summary.recommended_action, "gray")
    st.markdown(
        f"### Recommended Action: :{color}[**{summary.recommended_action}**]"
    )
    if summary.flagged_items:
        st.error("⚠️ Items requiring clinician attention")
        for item in summary.flagged_items:
            st.markdown(f"- {item}")

    # The stored note repeats the action and flagged items already shown above
    note = re.sub(
        r"### ⚠️ Items Requiring Attention\n.*?(?=\n### )", "",
        summary.summary_markdown, flags=re.S,
    )
    note = re.sub(r"### Recommended Action:[^\n]*\n", "", note)
    st.markdown(note)
    st.caption(f"Note generated: {summary.generated_at}")


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🏥 Hospital-At-Home")
    st.divider()
    view = st.radio("I am a …", ["Patient", "Doctor / Nurse"])
    st.divider()


# ══════════════════════════════════════════════════════════════════════════════
#  PATIENT VIEW
# ══════════════════════════════════════════════════════════════════════════════

if view == "Patient":
    patient_ids = db.list_patient_ids()

    if not patient_ids:
        st.info("No patients are registered yet. A doctor or care coordinator must register you first.")
        st.stop()

    with st.sidebar:
        selected_id = st.selectbox("Select your name", patient_ids, format_func=patient_label)

    # Reset when patient changes
    if st.session_state.get("p_patient_id") != selected_id:
        st.session_state.p_patient_id = selected_id
        st.session_state.p_messages = []
        st.session_state.p_agent = None
        st.session_state.p_done = False

    # Start session instantly (no LLM, no spinner)
    if st.session_state.p_agent is None:
        try:
            agent = PatientAgent(selected_id, db)
            opening = agent.start_session()
            st.session_state.p_agent = agent
            st.session_state.p_messages = [{"role": "assistant", "content": opening}]
        except Exception as e:
            st.error(f"Could not load your information: {e}")
            st.stop()

    record = st.session_state.p_agent.record
    st.title(f"Daily Check-In — {record.name}")
    st.caption(
        f"Today: {date.today().strftime('%B %d, %Y')}  •  "
        f"Care team: {record.care_team_contact}"
    )
    st.divider()

    # Render conversation
    for msg in st.session_state.p_messages:
        avatar = "🏥" if msg["role"] == "assistant" else "🙋"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # Completion state
    if st.session_state.p_done:
        st.success(
            "✅ **Check-in complete!** Your care team has been notified "
            "and will review your responses."
        )
        if st.button("Start a new check-in", type="secondary"):
            st.session_state.p_agent = None
            st.session_state.p_messages = []
            st.session_state.p_done = False
            st.rerun()
        st.stop()

    # Chat input
    user_input = st.chat_input("Type your answer here and press Enter…")
    if user_input:
        st.session_state.p_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="🙋"):
            st.markdown(user_input)

        reply, done = st.session_state.p_agent.respond(user_input)

        with st.chat_message("assistant", avatar="🏥"):
            st.markdown(reply)
        st.session_state.p_messages.append({"role": "assistant", "content": reply})
        st.session_state.p_done = done

        # Auto-generate clinical summary the moment the patient finishes
        if done:
            try:
                SummaryAgent(selected_id, db).generate()
            except Exception:
                pass  # Summary can still be generated manually from doctor view

        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  DOCTOR / NURSE VIEW
# ══════════════════════════════════════════════════════════════════════════════

else:
    st.title("Clinician Dashboard")
    patient_ids = db.list_patient_ids()
    has_patients = bool(patient_ids)

    if has_patients:
        with st.sidebar:
            selected_id = st.selectbox("Patient", patient_ids, format_func=patient_label)
        record = db.get_patient(selected_id)
        col1, col2, col3 = st.columns(3)
        col1.metric("Patient", record.name)
        col2.metric("Primary Diagnosis", record.primary_diagnosis)
        col3.metric("Admitted", record.admission_date)
        st.divider()

    tab_summary, tab_questions, tab_register = st.tabs(
        ["📋 Clinical Summary", "❓ Add Questions", "➕ Register Patient"]
    )

    # ── Clinical Summary ───────────────────────────────────────────────────
    with tab_summary:
        if not has_patients:
            st.info("Register a patient first (use the 'Register Patient' tab).")
        else:
            today = date.today().isoformat()
            existing = db.get_summary(selected_id, today)

            if existing:
                show_summary(existing)
            else:
                checkin = db.get_checkin(selected_id, today)
                if checkin:
                    # Check-in exists but summary hasn't been generated yet
                    st.info("Check-in completed. Generating clinical note…")
                    try:
                        summary = SummaryAgent(selected_id, db).generate()
                        show_summary(summary)
                    except Exception as e:
                        st.error(f"Could not generate summary: {e}")
                else:
                    st.info(
                        f"**{record.name}** has not completed today's check-in yet ({today}). "
                        "The summary will appear here automatically once they finish."
                    )

            # Show recent check-in history
            history = db.get_recent_checkins(selected_id, n=5)
            if history:
                with st.expander("View recent check-in responses"):
                    for ci in history:
                        st.markdown(f"**{ci.date}**")
                        for r in ci.responses:
                            st.markdown(f"- **Q:** {r.question}  \n  **A:** {r.answer}")
                        st.divider()

    # ── Add Doctor Questions ───────────────────────────────────────────────
    with tab_questions:
        if not has_patients:
            st.info("Register a patient first.")
        else:
            st.subheader(f"Add questions for {record.name}'s next check-in")
            st.caption(
                "These questions will appear first in the chatbot, "
                "before the standard personalized questions."
            )

            today = date.today().isoformat()
            existing_qs = db.get_doctor_questions(selected_id, today)
            if existing_qs:
                st.markdown("**Already added for today:**")
                for q in existing_qs:
                    st.markdown(f"- {q}")
                st.divider()

            added_by = st.text_input("Your name", placeholder="Dr. Smith")
            new_q = st.text_area(
                "Enter questions — one per line",
                placeholder=(
                    "Did you notice any new swelling in your legs?\n"
                    "Did you weigh yourself before breakfast today?"
                ),
                height=150,
            )
            if st.button("Save questions", type="primary"):
                questions = [q.strip() for q in new_q.strip().splitlines() if q.strip()]
                if not questions:
                    st.error("Please enter at least one question.")
                else:
                    db.save_doctor_questions(DoctorQuestions(
                        patient_id=selected_id,
                        questions=questions,
                        added_by=added_by or "Clinician",
                    ))
                    st.success(f"✅ {len(questions)} question(s) saved for {record.name}.")

    # ── Register Patient ───────────────────────────────────────────────────
    with tab_register:
        st.subheader("Register a new patient")
        uploaded = st.file_uploader("Upload patient record JSON", type="json")
        if uploaded:
            try:
                new_record = PatientRecord.model_validate(json.loads(uploaded.read()))
                db.save_patient(new_record)
                st.success(f"✅ Registered: {new_record.name} ({new_record.patient_id})")
                st.cache_resource.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Invalid file: {e}")

        st.divider()
        st.subheader("Required JSON format")
        sample_path = Path(__file__).parent / "sample_data" / "patient_001.json"
        if sample_path.exists():
            st.code(sample_path.read_text(), language="json")
