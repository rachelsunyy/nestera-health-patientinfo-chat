"""Clinician page: today's roster, then one patient's summary, trends and questions."""

import json
import re
from datetime import date, datetime

import pandas as pd
import streamlit as st

import ui_theme
from agents.summary_agent import SummaryAgent
from agents.trends import IMPROVING, VITAL_LABELS, WINDOW, WORSENING, assess_trend
from data.models import DoctorQuestions, PatientRecord
from views.shared import SAMPLE_DIR, get_db, patient_names

# Roster order: patients who need attention, then those not started, then routine.
TRIAGE_RANK = {"Escalate": 0, "Schedule visit": 1, None: 2, "Routine review": 3}


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


def checkin_time(checkin) -> str:
    return datetime.fromisoformat(checkin.timestamp).strftime("%-I:%M %p")


def open_patient(patient_id: str | None) -> None:
    st.session_state.clinician_patient_id = patient_id
    if patient_id is None:
        st.query_params.clear()


def roster_row(pid: str, name: str, today: str) -> dict:
    rec = db.get_patient(pid)
    todays = db.get_checkins_for_date(pid, today)
    summ = db.get_summary(pid, todays[-1].id) if todays else None
    action = summ.recommended_action if summ else None
    return {
        "id": pid,
        "name": name,
        "diagnosis": rec.primary_diagnosis,
        "status_html": ui_theme.chip("Completed" if todays else "Not started", "green" if todays else "gray")
        + (f'<div class="nh-sub">{len(todays)} check-ins today</div>' if len(todays) > 1 else ""),
        "action_html": (
            ui_theme.chip(action, ui_theme.action_tone(action))
            if action else '<span style="color:#7A8794">—</span>'
        ),
        "done": bool(todays),
        "attention": action not in (None, "Routine review"),
        "rank": TRIAGE_RANK.get(action or ("Routine review" if todays else None), 1),
    }


def register_patient() -> None:
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

    sample_path = SAMPLE_DIR / "patient_001.json"
    if sample_path.exists():
        st.markdown("**Required JSON format**")
        st.code(sample_path.read_text(), language="json")


def show_roster(names: dict[str, str]) -> None:
    today = date.today().isoformat()
    ui_theme.hero("Clinician Dashboard", f"{date.today().strftime('%A, %B %d, %Y')}  ·  Today's check-in overview")
    if not names:
        st.info("No patients are registered yet. Register one below.")
    else:
        rows = sorted((roster_row(pid, name, today) for pid, name in names.items()),
                      key=lambda r: (r["rank"], r["name"]))
        n_done = sum(r["done"] for r in rows)
        n_attn = sum(r["attention"] for r in rows)
        ui_theme.kpi_row([
            ("Patients", len(rows), ""),
            ("Check-ins complete", f"{n_done} / {len(rows)}", "green" if n_done == len(rows) else ""),
            ("Need attention", n_attn, "red" if n_attn else "green"),
        ])
        with st.container(key="roster"):
            st.columns([6, 1])[0].markdown(ui_theme.roster_header(), unsafe_allow_html=True)
            for r in rows:
                with st.container(key=f"roster_row_{r['id']}"):
                    info, action = st.columns([6, 1], vertical_alignment="center")
                    info.markdown(ui_theme.roster_row(r), unsafe_allow_html=True)
                    action.button("Open", key=f"open_{r['id']}", on_click=open_patient, args=(r["id"],))
    st.write("")
    with st.expander("➕ Register a new patient", expanded=not names):
        register_patient()


def show_patient(selected_id: str) -> None:
    record = db.get_patient(selected_id)
    st.button("Back to roster", icon=":material/arrow_back:", type="tertiary", on_click=open_patient, args=(None,))
    ui_theme.hero(record.name, f"Patient detail  ·  {date.today().strftime('%A, %B %d, %Y')}")
    ui_theme.detail_cards([
        ("Patient ID", record.patient_id),
        ("Primary diagnosis", record.primary_diagnosis),
        ("Admitted", record.admission_date),
    ])
    st.write("")

    tab_summary, tab_trends, tab_questions = st.tabs(["📋 Clinical Summary", "📈 Trends", "❓ Add Questions"])
    today = date.today().isoformat()

    with tab_summary:
        todays = db.get_checkins_for_date(selected_id, today)
        if todays:
            latest = todays[-1]
            if len(todays) > 1:
                st.caption(f"{len(todays)} check-ins today. Showing the latest, from {checkin_time(latest)}.")
            existing = db.get_summary(selected_id, latest.id)
            if existing:
                show_summary(existing)
            else:
                st.info("Check-in completed. Generating clinical note…")
                try:
                    show_summary(SummaryAgent(selected_id, db).generate(latest.id))
                except Exception as e:
                    st.error(f"Could not generate summary: {e}")
        else:
            st.info(
                f"**{record.name}** has not completed today's check-in yet ({today}). "
                "The summary will appear here automatically once they finish."
            )

        history = db.get_recent_checkins(selected_id, n=5)
        if history:
            with st.expander("View recent check-in responses"):
                for ci in history:
                    st.markdown(f"**{ci.date} at {checkin_time(ci)}**")
                    for r in ci.responses:
                        st.markdown(f"- **Q:** {r.question}  \n  **A:** {r.answer}")
                    st.divider()

    with tab_trends:
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
                {VITAL_LABELS[k]: {p.label: p.vitals[k] for p in report.points if k in p.vitals}
                 for k in VITAL_LABELS if any(k in p.vitals for p in report.points)}
            )
            for col in chart.columns:
                st.caption(col)
                st.line_chart(chart[col].dropna())
            st.caption(
                "Trend rules and bands are prototype values, not clinically validated. "
                "Readings are taken from the patient's own answers."
            )

    with tab_questions:
        st.subheader(f"Add questions for {record.name}'s next check-in")
        st.caption(
            "These questions will appear first in the chatbot, "
            "before the standard personalized questions."
        )
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


db = get_db()
names = patient_names(db)
st.set_page_config(page_title="Clinician Dashboard · Nestera Health")
ui_theme.brand_header()

if "clinician_patient_id" not in st.session_state:
    linked = st.query_params.get("patient")
    st.session_state.clinician_patient_id = linked if linked in names else None
    if linked and linked not in names:
        st.info(f"No patient with id {linked}. Showing today's roster.")

selected = st.session_state.clinician_patient_id
if selected in names:
    show_patient(selected)
else:
    show_roster(names)
