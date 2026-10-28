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
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Nestera Health · Daily Check-In",
    page_icon="assets/nestera-mark.svg",
    layout="centered",
)

# ── Database ───────────────────────────────────────────────────────────────
from database.patient_db import MockPatientDatabase, GCSPatientDatabase
from data.models import PatientRecord, DoctorQuestions
import config
from agents.conversation_agent import ConversationalPatientAgent
from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent
from agents.trends import IMPROVING, VITAL_LABELS, WINDOW, WORSENING, assess_trend
import ui_theme

ui_theme.inject_css()


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
    ai_chip = (" &nbsp; " + ui_theme.chip("AI-assisted", "gray")) if summary.ai_models else ""
    st.markdown(
        "**Recommended action** &nbsp; "
        + ui_theme.chip(summary.recommended_action, ui_theme.action_tone(summary.recommended_action))
        + ai_chip,
        unsafe_allow_html=True,
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
    try:
        generated = datetime.fromisoformat(summary.generated_at).strftime("%b %d, %Y at %-I:%M %p")
    except ValueError:
        generated = summary.generated_at
    st.caption(f"Note generated: {generated}")


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    ui_theme.brand_header()
    st.divider()
    view = st.radio("View as", ["Patient", "Doctor / Nurse"])
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
            agent_class = ConversationalPatientAgent if config.AI_CONVERSATION_ENABLED else PatientAgent
            agent = agent_class(selected_id, db)
            opening = agent.start_session()
            st.session_state.p_agent = agent
            st.session_state.p_messages = [{"role": "assistant", "content": opening}]
        except Exception as e:
            st.error(f"Could not load your information: {e}")
            st.stop()

    record = st.session_state.p_agent.record
    ui_theme.hero(
        f"Daily Check-In — {record.name}",
        f"{date.today().strftime('%A, %B %d, %Y')}  ·  Care team: {record.care_team_contact}",
    )
    answered, total = st.session_state.p_agent.progress
    if st.session_state.p_done:
        answered = total
    st.progress(answered / total if total else 0.0, text=f"{answered} of {total} questions answered")
    ui_theme.emergency_notice(record.care_team_contact)

    # Render conversation
    for msg in st.session_state.p_messages:
        avatar = "🏥" if msg["role"] == "assistant" else "🙋"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # Completion state
    if st.session_state.p_done:
        if getattr(st.session_state.p_agent, "ended_early", False):
            st.warning("Your check-in was ended early so you can get help. What you shared has been saved for your care team.")
        else:
            st.success(
                "✅ **Check-in complete!** Your responses have been saved "
                "and your care team will review them."
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
    today = date.today().isoformat()
    patient_ids = db.list_patient_ids()
    has_patients = bool(patient_ids)

    ui_theme.hero("Clinician Dashboard", f"{date.today().strftime('%A, %B %d, %Y')}  ·  Today's check-in overview")

    if has_patients:
        rows = []
        for pid in patient_ids:
            rec = db.get_patient(pid)
            done = db.get_checkin(pid, today) is not None
            summ = db.get_summary(pid, today) if done else None
            rows.append({
                "id": pid,
                "name": rec.name,
                "diagnosis": rec.primary_diagnosis,
                "status_html": ui_theme.chip("Completed" if done else "Not started", "green" if done else "gray"),
                "action_html": (
                    ui_theme.chip(summ.recommended_action, ui_theme.action_tone(summ.recommended_action))
                    if summ else '<span style="color:#7A8794">—</span>'
                ),
                "_done": done,
                "_attention": bool(summ and summ.recommended_action != "Routine review"),
            })
        n_done = sum(r["_done"] for r in rows)
        n_attn = sum(r["_attention"] for r in rows)
        ui_theme.kpi_row([
            ("Patients", len(rows), ""),
            ("Check-ins complete", f"{n_done} / {len(rows)}", "green" if n_done == len(rows) else ""),
            ("Need attention", n_attn, "red" if n_attn else "green"),
        ])
        ui_theme.roster_table(rows)
        st.write("")

        with st.sidebar:
            selected_id = st.selectbox("Patient", patient_ids, format_func=patient_label)
        record = db.get_patient(selected_id)
        st.subheader(f"Patient detail — {record.name}")
        ui_theme.detail_cards([
            ("Patient", record.name),
            ("Primary diagnosis", record.primary_diagnosis),
            ("Admitted", record.admission_date),
        ])
        st.write("")

    tab_summary, tab_trends, tab_questions, tab_register = st.tabs(
        ["📋 Clinical Summary", "📈 Trends", "❓ Add Questions", "➕ Register Patient"]
    )

    # ── Clinical Summary ───────────────────────────────────────────────────
    with tab_summary:
        if not has_patients:
            st.info("Register a patient first (use the 'Register Patient' tab).")
        else:
            today = date.today().isoformat()
            existing = db.get_summary(selected_id, today)
            checkin_today = db.get_checkin(selected_id, today)
            if existing and checkin_today and checkin_today.timestamp > existing.generated_at:
                existing = None  # check-in was redone after the note was written

            if existing:
                show_summary(existing)
            else:
                checkin = checkin_today
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

    # ── Trends across days ─────────────────────────────────────────────────
    with tab_trends:
        if not has_patients:
            st.info("Register a patient first.")
        else:
            report = assess_trend(db.get_recent_checkins(selected_id, n=WINDOW + 5))
            tone = {WORSENING: "red", IMPROVING: "green"}.get(report.status, "gray")
            st.markdown(
                f"**Trajectory over the last {len(report.points)} check-ins** &nbsp; "
                + ui_theme.chip(report.status, tone),
                unsafe_allow_html=True,
            )
            for reason in report.reasons:
                st.markdown(f"- {reason}")
            if len(report.points) >= 2:
                chart = pd.DataFrame(
                    {VITAL_LABELS[k]: {p.date: p.vitals[k] for p in report.points if k in p.vitals}
                     for k in VITAL_LABELS if any(k in p.vitals for p in report.points)}
                )
                for col in chart.columns:
                    st.caption(col)
                    st.line_chart(chart[col].dropna())
                st.caption(
                    "Trend rules and bands are prototype values, not clinically validated. "
                    "Readings are taken from the patient's own answers."
                )

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
